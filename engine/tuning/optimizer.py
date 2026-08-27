"""Sembol bazlı otomatik parametre ayarı + JSON depolama.

Walk-forward ile aşırı-uyumu önleyerek her sembol için en iyi eşikleri
(min_confidence, stop_loss, take_profit) seçer ve diske kaydeder. Bot açılışta
varsa bu ayarları yükler; yoksa varsayılan RiskConfig kullanılır (fail-safe).

Depolama: DATA_DIR/tuned_params.json
  { "ETH": {"min_confidence": 0.73, "stop_loss_pct": 0.05, "take_profit_pct": 0.1,
            "robust": true, "avg_oos_return_pct": 4.2, "ts": 1700000000000}, ... }
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import time

from engine.backtest.backtester import run_backtest
from engine.backtest.walk_forward import _score, walk_forward
from engine.config.settings import RiskConfig

log = logging.getLogger("tuning")


def _path() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "data"), "tuned_params.json")


def load_all() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_tuned(symbol: str) -> dict | None:
    return load_all().get(symbol.upper())


def _save(symbol: str, params: dict) -> None:
    data = load_all()
    data[symbol.upper()] = params
    p = _path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def optimize_symbol(candles: list[dict], symbol: str, quote: str,
                    starting_cash: float, base_risk: RiskConfig,
                    interval: str = "1h",
                    min_conf_grid: list[float] | None = None,
                    stop_grid: list[float] | None = None,
                    take_grid: list[float] | None = None,
                    save: bool = True) -> dict:
    """min_confidence x stop_loss x take_profit ızgarasında en iyi paramı seç.

    Önce tüm-veri ızgara taramasıyla en iyi kombinasyonu bulur, sonra
    walk-forward ile sağlamlığını (robust) doğrular ve kaydeder.
    """
    min_conf_grid = min_conf_grid or [0.55, 0.62, 0.70, 0.73, 0.80]
    stop_grid = stop_grid or [base_risk.stop_loss_pct]
    take_grid = take_grid or [base_risk.take_profit_pct]

    best = None
    best_score = -1e18
    for mc in min_conf_grid:
        for sl in stop_grid:
            for tp in take_grid:
                risk = dataclasses.replace(base_risk, min_confidence=mc,
                                           stop_loss_pct=sl, take_profit_pct=tp)
                try:
                    res = run_backtest(candles, symbol, quote, starting_cash,
                                       risk, interval)
                except ValueError:
                    continue
                s = _score(res)
                if s > best_score:
                    best_score = s
                    best = {"min_confidence": mc, "stop_loss_pct": sl,
                            "take_profit_pct": tp,
                            "in_sample_return_pct": res["total_return_pct"],
                            "in_sample_sharpe": res["sharpe"]}
    if best is None:
        return {"ok": False, "reason": "ızgara sonuç vermedi"}

    # Sağlamlık doğrulaması (walk-forward, sadece min_confidence boyutunda)
    robust = False
    avg_oos = 0.0
    try:
        wf = walk_forward(candles, symbol, quote, starting_cash, base_risk,
                          min_conf_grid, interval=interval)
        robust = wf.get("robust", False)
        avg_oos = wf.get("avg_oos_return_pct", 0.0)
    except ValueError:
        pass

    params = {**best, "robust": robust, "avg_oos_return_pct": avg_oos,
              "ts": int(time.time() * 1000), "ok": True}
    if save:
        _save(symbol, params)
        log.info("tuned %s -> %s", symbol, params)
    return params


def optimize_symbol_atr(candles: list[dict], symbol: str, quote: str,
                        starting_cash: float, base_risk: RiskConfig,
                        interval: str = "1h",
                        param_grid: dict[str, list] | None = None,
                        save: bool = True) -> dict:
    """ATR (canlı-eşdeğer) modda çok-boyutlu ızgara + walk-forward sağlamlık.

    min_confidence × trail_mult × atr_stop_mult × cooldown_bars × risk_pct
    taranır (varsayılan: walk_forward.DEFAULT_PARAM_GRID). Kazanan parametreler
    walk-forward ile out-of-sample doğrulanır ve tuned_params.json'a yazılır;
    orchestrator _maybe_trade sembol-bazlı min_confidence kapısını otomatik
    kullanır. Ölçümler: docs/BACKTEST_IMPROVEMENTS.md
    """
    from engine.backtest.walk_forward import (DEFAULT_PARAM_GRID,
                                              grid_search_params)
    grid = param_grid or DEFAULT_PARAM_GRID
    best_params, best_res = grid_search_params(
        candles, symbol, quote, starting_cash, base_risk, grid, interval)
    if not best_params:
        return {"ok": False, "reason": "ızgara sonuç vermedi"}

    robust = False
    avg_oos = 0.0
    try:
        wf = walk_forward(candles, symbol, quote, starting_cash, base_risk,
                          min_conf_grid=[base_risk.min_confidence],
                          interval=interval, param_grid=grid)
        robust = wf.get("robust", False)
        avg_oos = wf.get("avg_oos_return_pct", 0.0)
    except ValueError:
        pass

    params = {"mode": "atr", **best_params,
              "in_sample_return_pct": best_res.get("total_return_pct", 0.0),
              "in_sample_sharpe": best_res.get("sharpe", 0.0),
              "robust": robust, "avg_oos_return_pct": avg_oos,
              "ts": int(time.time() * 1000), "ok": True}
    if save:
        _save(symbol, params)
        log.info("tuned(atr) %s -> %s", symbol, params)
    return params


def apply_tuned(base_risk: RiskConfig, symbol: str) -> RiskConfig:
    """Kayıtlı ayar varsa RiskConfig'e uygula; yoksa olduğu gibi döndür."""
    t = get_tuned(symbol)
    if not t:
        return base_risk
    return dataclasses.replace(
        base_risk,
        min_confidence=t.get("min_confidence", base_risk.min_confidence),
        stop_loss_pct=t.get("stop_loss_pct", base_risk.stop_loss_pct),
        take_profit_pct=t.get("take_profit_pct", base_risk.take_profit_pct))
