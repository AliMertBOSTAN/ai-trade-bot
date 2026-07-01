"""Walk-forward (ileri-yürüyen) backtest + parametre taraması.

Aşırı-uyumu yakalamak için: veriyi sıralı kat'lara böler, her kat'ın IN-SAMPLE
kısmında en iyi parametreyi seçer, ardından görülmemiş OUT-OF-SAMPLE kısmında
test eder. Sadece in-sample iyi ama OOS kötüyse strateji aşırı uyumludur.
"""
from __future__ import annotations

import dataclasses

from engine.backtest.backtester import run_backtest
from engine.config.settings import RiskConfig


def _score(result: dict) -> float:
    return result.get("sharpe", 0.0) * 0.6 + result.get("total_return_pct", 0.0) / 100 * 0.4


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
                 interval: str = "1h") -> dict:
    """n_folds sıralı kat üzerinde walk-forward değerlendirme."""
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
        best_conf, _ = grid_search(train, base, quote, starting_cash,
                                   base_risk, min_conf_grid, interval)
        risk = dataclasses.replace(base_risk, min_confidence=best_conf)
        oos = run_backtest(test, base, quote, starting_cash, risk, interval)
        folds.append({
            "fold": k,
            "chosen_min_confidence": best_conf,
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
