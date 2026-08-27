"""Walk-forward (ileri-yürüyen) backtest + parametre taraması.

Aşırı-uyumu yakalamak için: veriyi sıralı kat'lara böler, her kat'ın IN-SAMPLE
kısmında en iyi parametreyi seçer, ardından görülmemiş OUT-OF-SAMPLE kısmında
test eder. Sadece in-sample iyi ama OOS kötüyse strateji aşırı uyumludur.
"""
from __future__ import annotations

import dataclasses
import itertools

from engine.backtest.backtester import run_backtest
from engine.config.settings import RiskConfig
from engine.trading.exits import ExitConfig


def _score(result: dict) -> float:
    return result.get("sharpe", 0.0) * 0.6 + result.get("total_return_pct", 0.0) / 100 * 0.4


# ATR (canlı-eşdeğer) mod için varsayılan parametre ızgarası. Küçük tutulur:
# her kat'ta in-sample taranır, kazanan OUT-OF-SAMPLE'da doğrulanır.
DEFAULT_PARAM_GRID: dict[str, list] = {
    "min_confidence": [0.60, 0.66, 0.73],
    "trail_mult": [2.5, 3.5],
    "atr_stop_mult": [2.0, 3.0],
    "cooldown_bars": [0, 16, 30],
    "risk_pct": [0.0, 0.01],
}


def _run_atr(candles: list[dict], base: str, quote: str, starting_cash: float,
             base_risk: RiskConfig, params: dict, interval: str) -> dict:
    """Tek parametre kombinasyonuyla ATR-modu backtest."""
    risk = dataclasses.replace(base_risk,
                               min_confidence=params["min_confidence"])
    ec = ExitConfig(atr_stop_mult=params.get("atr_stop_mult", 2.0),
                    trail_mult=params.get("trail_mult", 2.5))
    return run_backtest(candles, base, quote, starting_cash, risk, interval,
                        exit_style="atr", exit_cfg=ec,
                        cooldown_bars=int(params.get("cooldown_bars", 0)),
                        risk_pct=float(params.get("risk_pct", 0.0)),
                        htf_filter=str(params.get("htf_filter", "off")),
                        allow_short=bool(params.get("allow_short", False)))


def grid_search_params(candles: list[dict], base: str, quote: str,
                       starting_cash: float, base_risk: RiskConfig,
                       param_grid: dict[str, list] | None = None,
                       interval: str = "1h") -> tuple[dict, dict]:
    """Çok-boyutlu ızgara (ATR modu): en iyi (params, sonuç) döndürür."""
    grid = param_grid or DEFAULT_PARAM_GRID
    keys = list(grid.keys())
    best_params: dict = {}
    best_res: dict = {}
    best_score = -1e18
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        params.setdefault("min_confidence", base_risk.min_confidence)
        try:
            res = _run_atr(candles, base, quote, starting_cash,
                           base_risk, params, interval)
        except ValueError:
            continue
        s = _score(res)
        if s > best_score:
            best_score, best_params, best_res = s, params, res
    return best_params, best_res


def grid_search(candles: list[dict], base: str, quote: str, starting_cash: float,
                base_risk: RiskConfig, min_conf_grid: list[float],
                interval: str = "1h") -> tuple[float, dict]:
    """min_confidence ızgarasında en iyi parametreyi (skora göre) döndürür."""
    best_conf = min_conf_grid[0]
    best_res: dict | None = None
    best_score = -1e18
    for mc in min_conf_grid:
        risk = dataclasses.replace(base_risk, min_confidence=mc)
        try:
            res = run_backtest(candles, base, quote, starting_cash, risk, interval)
        except ValueError:
            continue
        s = _score(res)
        if s > best_score:
            best_score, best_conf, best_res = s, mc, res
    return best_conf, (best_res or {})


def walk_forward(candles: list[dict], base: str, quote: str, starting_cash: float,
                 base_risk: RiskConfig, min_conf_grid: list[float],
                 n_folds: int = 4, train_ratio: float = 0.6,
                 interval: str = "1h",
                 param_grid: dict[str, list] | None = None) -> dict:
    """n_folds sıralı kat üzerinde walk-forward değerlendirme.

    param_grid verilirse ATR (canlı-eşdeğer) modda çok-boyutlu ızgara taranır;
    verilmezse eski davranış (sabit SL/TP + min_confidence ızgarası) korunur.
    """
    n = len(candles)
    if n < 120:
        raise ValueError("Walk-forward için en az ~120 mum önerilir")

    fold_size = n // n_folds
    folds: list[dict] = []
    for k in range(n_folds):
        start = k * fold_size
        end = n if k == n_folds - 1 else (k + 1) * fold_size
        seg = candles[start:end]
        if len(seg) < 60:
            continue
        split = int(len(seg) * train_ratio)
        train, test = seg[:split], seg[split:]
        if len(train) < 40 or len(test) < 40:
            continue
        if param_grid is not None:
            best_params, _ = grid_search_params(train, base, quote,
                                                starting_cash, base_risk,
                                                param_grid, interval)
            if not best_params:
                continue
            oos = _run_atr(test, base, quote, starting_cash, base_risk,
                           best_params, interval)
            chosen: dict = dict(best_params)
        else:
            best_conf, _ = grid_search(train, base, quote, starting_cash,
                                       base_risk, min_conf_grid, interval)
            risk = dataclasses.replace(base_risk, min_confidence=best_conf)
            oos = run_backtest(test, base, quote, starting_cash, risk, interval)
            chosen = {"min_confidence": best_conf}
        folds.append({
            "fold": k,
            "chosen_min_confidence": chosen.get("min_confidence"),
            "chosen_params": chosen,
            "oos_return_pct": oos["total_return_pct"],
            "oos_sharpe": oos["sharpe"],
            "oos_max_dd_pct": oos["max_drawdown_pct"],
            "oos_trades": oos.get("num_closed_trades", 0),
        })

    if not folds:
        return {"folds": [], "avg_oos_return_pct": 0.0, "avg_oos_sharpe": 0.0,
                "positive_folds": 0, "total_folds": 0, "robust": False}

    avg_ret = sum(f["oos_return_pct"] for f in folds) / len(folds)
    avg_sharpe = sum(f["oos_sharpe"] for f in folds) / len(folds)
    positive = sum(1 for f in folds if f["oos_return_pct"] > 0)
    return {
        "folds": folds,
        "avg_oos_return_pct": round(avg_ret, 3),
        "avg_oos_sharpe": round(avg_sharpe, 3),
        "positive_folds": positive,
        "total_folds": len(folds),
        "robust": positive >= (len(folds) + 1) // 2,
    }
