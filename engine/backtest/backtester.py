"""Geçmiş mumlar üzerinde strateji backtest'i.

Rolling pencere ile teknik sinyal üretir (LLM kapalı - hız ve determinizm),
paper broker muhasebesiyle simüle eder ve performans metrikleri döndürür.
"""
from __future__ import annotations

import math

from engine.config.settings import RiskConfig
from engine.indicators.technical import compute_snapshot
from engine.models import TradeOrder, TradeSignal
from engine.risk.manager import RiskManager
from engine.signals.engine import _rule_decision
from engine.trading.paper_broker import PaperBroker
from engine.trading.portfolio import Portfolio


def _mk_signal(base, quote, action, conf, tech) -> TradeSignal:
    return TradeSignal(chain_id=0, base=base, quote=quote, action=action,
                       confidence=conf, technical=tech, rationale="backtest",
                       source="technical")


def run_backtest(candles: list[dict], base: str, quote: str,
                 starting_cash: float, risk: RiskConfig) -> dict:
    closes = [c["close"] for c in candles]
    if len(closes) < 40:
        raise ValueError("Backtest için en az 40 mum gerekli")

    portfolio = Portfolio(starting_cash)
    broker = PaperBroker(portfolio, risk)
    rm = RiskManager(risk)
    key = f"0:{base}"

    equity_curve: list[dict] = []
    trades: list[TradeOrder] = []
    win_sells = 0
    total_sells = 0

    warmup = 30
    for i in range(warmup, len(closes)):
        window = closes[: i + 1]
        price = closes[i]
        tech = compute_snapshot(window)
        action, conf = _rule_decision(tech)

        portfolio.mark({key: price})

        # açık pozisyonda stop-loss / take-profit önceliklidir
        pos = portfolio.positions.get(key)
        if pos and rm.check_stop_take(pos, price):
            action, conf = "SELL", 1.0

        if action != "HOLD" and conf >= risk.min_confidence:
            decision = rm.evaluate(_mk_signal(base, quote, action, conf, tech),
                                   portfolio.positions, portfolio.cash_usd)
            if decision.approved:
                if action == "BUY":
                    amount = decision.size_usd / price
                else:
                    amount = pos.amount if pos else 0.0
                if amount > 0:
                    entry = pos.avg_entry if (action == "SELL" and pos) else 0.0
                    order = TradeOrder(mode="paper", chain_id=0, dex="backtest",
                                       base=base, quote=quote, side=action,
                                       amount=amount, price=price)
                    broker.execute(order)
                    trades.append(order)
                    if action == "SELL":
                        total_sells += 1
                        if order.filled_price > entry:
                            win_sells += 1

        equity_curve.append({"t": candles[i]["t"], "equity": portfolio.equity_usd()})

    eqs = [e["equity"] for e in equity_curve]
    final = eqs[-1] if eqs else starting_cash
    total_return = (final - starting_cash) / starting_cash * 100

    peak = -math.inf
    max_dd = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    rets = [(eqs[j] - eqs[j - 1]) / eqs[j - 1]
            for j in range(1, len(eqs)) if eqs[j - 1] > 0]
    sharpe = 0.0
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        std = math.sqrt(var)
        if std > 0:
            sharpe = mean / std * math.sqrt(252)

    win_rate = (win_sells / total_sells) if total_sells else 0.0

    return {
        "trades": [t.to_dict() for t in trades],
        "equity_curve": equity_curve,
        "total_return_pct": total_return,
        "max_drawdown_pct": max_dd * 100,
        "win_rate": win_rate,
        "sharpe": sharpe,
        "final_equity_usd": final,
    }
