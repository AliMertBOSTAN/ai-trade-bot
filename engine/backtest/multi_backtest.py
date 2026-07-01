"""Coklu-strateji, rejim-degisimli backtest (short destekli).

Her stratejiye toplam sermayenin bir dilimi (alt-portfoy) verilir. Her barda
piyasa rejimi tespit edilir; yalnizca rejime UYAN stratejiler islem acar.
Birlesik equity = alt-portfoylerin toplami. Cikti: birlesik metrikler +
per-strateji atif. allow_short=True ile stratejiler short da acabilir.
"""
from __future__ import annotations

from engine.analytics import metrics as _metrics
from engine.backtest.backtester import _PERIODS_PER_YEAR
from engine.config.settings import RiskConfig
from engine.indicators.technical import compute_snapshot
from engine.models import TradeOrder, TradeSignal
from engine.risk.manager import RiskManager
from engine.strategy import registry
from engine.strategy.base import StrategyContext
from engine.strategy.manager import StrategyManager
from engine.strategy.router import select_active
from engine.trading.paper_broker import PaperBroker
from engine.trading.portfolio import Portfolio


def _mk_signal(base, quote, action, conf, tech) -> TradeSignal:
    return TradeSignal(chain_id=0, base=base, quote=quote, action=action,
                       confidence=conf, technical=tech, rationale="multi",
                       source="strategy")


def run_multi_backtest(candles: list[dict], base: str, quote: str,
                       total_cash: float, manager: StrategyManager,
                       risk: RiskConfig, interval: str = "1h",
                       allow_short: bool = False) -> dict:
    import engine.strategy.strategies  # noqa: F401  (kayitlari yukle)

    closes = [c["close"] for c in candles]
    highs = [c.get("high", c["close"]) for c in candles]
    lows = [c.get("low", c["close"]) for c in candles]
    volumes = [c.get("volume", 0.0) for c in candles]
    if len(closes) < 50:
        raise ValueError("Coklu backtest icin en az 50 mum gerekli")

    key = f"0:{base}"
    rm = RiskManager(risk, allow_short=allow_short)
    weights = manager.normalized_weights()

    subs: dict[str, dict] = {}
    for name, w in weights.items():
        pf = Portfolio(total_cash * w, allow_short=allow_short)
        subs[name] = {"pf": pf, "broker": PaperBroker(pf, risk),
                      "strat": registry.create(name), "pnls": [], "trades": 0}

    combined_curve: list[dict] = []
    warmup = 40
    regime_hist: dict[str, int] = {}

    for i in range(warmup, len(closes)):
        price = closes[i]
        tech = compute_snapshot(closes[:i + 1], highs[:i + 1], lows[:i + 1], volumes[:i + 1])
        regime, active = select_active(manager, tech)
        regime_hist[regime] = regime_hist.get(regime, 0) + 1

        for sub in subs.values():
            sub["pf"].mark({key: price})

        for name in active:
            sub = subs[name]
            pf = sub["pf"]
            pos = pf.positions.get(key)

            forced = None
            if pos and rm.check_stop_take(pos, price):
                forced = "BUY" if pos.amount < 0 else "SELL"  # short kapat=BUY

            ctx = StrategyContext(
                base=base, quote=quote, chain_id=0, closes=closes[:i + 1],
                highs=highs[:i + 1], lows=lows[:i + 1], volumes=volumes[:i + 1],
                tech=tech, price=price, cash_allocated=pf.cash_usd)
            sig = sub["strat"].evaluate(ctx)
            action = forced or sig.action
            conf = 1.0 if forced else sig.confidence
            if action == "HOLD" or conf < risk.min_confidence:
                continue

            decision = rm.evaluate(_mk_signal(base, quote, action, conf, tech),
                                   pf.positions, pf.cash_usd)
            if not decision.approved:
                continue
            if action == "BUY":
                amount = abs(pos.amount) if (pos and pos.amount < 0) else decision.size_usd / price
            else:
                amount = pos.amount if (pos and pos.amount > 0) else decision.size_usd / price
            if amount <= 0:
                continue
            order = TradeOrder(mode="paper", chain_id=0, dex="multi", base=base,
                               quote=quote, side=action, amount=amount, price=price)
            before = pf.realized_pnl_usd
            sub["broker"].execute(order)
            sub["trades"] += 1
            d = pf.realized_pnl_usd - before
            if abs(d) > 1e-9:
                sub["pnls"].append(d)

        combined = sum(sub["pf"].equity_usd() for sub in subs.values())
        combined_curve.append({"t": candles[i]["t"], "equity": combined})

    eqs = [total_cash] + [e["equity"] for e in combined_curve]
    ppy = _PERIODS_PER_YEAR.get(interval, 8760)
    all_pnls = [p for s in subs.values() for p in s["pnls"]]
    summary = _metrics.summarize(eqs, trade_pnls=all_pnls, periods_per_year=ppy)

    attribution = []
    for name, sub in subs.items():
        start = total_cash * weights[name]
        final = sub["pf"].equity_usd()
        attribution.append({
            "strategy": name,
            "alloc_pct": round(weights[name] * 100, 1),
            "final_equity_usd": round(final, 2),
            "return_pct": round((final - start) / start * 100, 2) if start > 0 else 0.0,
            "trades": sub["trades"],
        })

    return {
        "equity_curve": combined_curve,
        "total_return_pct": summary["total_return_pct"],
        "max_drawdown_pct": summary["max_drawdown_pct"],
        "sharpe": summary["sharpe"],
        "sortino": summary["sortino"],
        "calmar": summary["calmar"],
        "win_rate": summary.get("win_rate", 0.0),
        "profit_factor": summary.get("profit_factor", 0.0),
        "num_closed_trades": summary.get("trades", 0),
        "final_equity_usd": summary["final_equity_usd"],
        "attribution": attribution,
        "regime_distribution": regime_hist,
    }
