"""Geçmiş mumlar üzerinde strateji backtest'i (maliyet-farkında).

Rolling pencere ile teknik sinyal üretir (LLM kapalı - hız/determinizm), paper
broker muhasebesiyle (slippage + DEX fee + gas) simüle eder ve risk-ayarlı
performans metrikleri döndürür.
"""
from __future__ import annotations

from engine.analytics import metrics as _metrics
from engine.config.settings import RiskConfig
from engine.indicators.technical import compute_snapshot
from engine.models import TradeOrder, TradeSignal
from engine.risk.manager import RiskManager
from engine.signals.engine import _rule_decision
from engine.trading.paper_broker import PaperBroker
from engine.trading.portfolio import Portfolio

# interval -> yıldaki periyot sayısı (Sharpe/Sortino/Calmar yıllıklandırması)
_PERIODS_PER_YEAR = {
    "1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520,
    "1h": 8760, "4h": 2190, "1d": 365,
}


def _mk_signal(base, quote, action, conf, tech) -> TradeSignal:
    return TradeSignal(chain_id=0, base=base, quote=quote, action=action,
                       confidence=conf, technical=tech, rationale="backtest",
                       source="technical")


def run_backtest(candles: list[dict], base: str, quote: str,
                 starting_cash: float, risk: RiskConfig,
                 interval: str = "1h") -> dict:
    closes = [c["close"] for c in candles]
    highs = [c.get("high", c["close"]) for c in candles]
    lows = [c.get("low", c["close"]) for c in candles]
    volumes = [c.get("volume", 0.0) for c in candles]
    if len(closes) < 40:
        raise ValueError("Backtest için en az 40 mum gerekli")

    portfolio = Portfolio(starting_cash)
    broker = PaperBroker(portfolio, risk)
    rm = RiskManager(risk)
    key = f"0:{base}"

    equity_curve: list[dict] = []
    trades: list[TradeOrder] = []
    trade_pnls: list[float] = []  # kapanan (SELL) işlemlerin gerçekleşen PnL'leri

    warmup = 30
    for i in range(warmup, len(closes)):
        window = closes[: i + 1]
        price = closes[i]
        tech = compute_snapshot(window, highs[: i + 1], lows[: i + 1], volumes[: i + 1])
        action, conf = _rule_decision(tech)

        portfolio.mark({key: price})

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
                    order = TradeOrder(mode="paper", chain_id=0, dex="backtest",
                                       base=base, quote=quote, side=action,
                                       amount=amount, price=price)
                    before = portfolio.realized_pnl_usd
                    broker.execute(order)
                    trades.append(order)
                    if action == "SELL":
                        trade_pnls.append(portfolio.realized_pnl_usd - before)

        equity_curve.append({"t": candles[i]["t"], "equity": portfolio.equity_usd()})

    eqs = [starting_cash] + [e["equity"] for e in equity_curve]
    ppy = _PERIODS_PER_YEAR.get(interval, 8760)
    summary = _metrics.summarize(eqs, trade_pnls=trade_pnls, periods_per_year=ppy)

    return {
        "trades": [t.to_dict() for t in trades],
        "equity_curve": equity_curve,
        "total_return_pct": summary["total_return_pct"],
        "max_drawdown_pct": summary["max_drawdown_pct"],
        "win_rate": summary.get("win_rate", 0.0),
        "sharpe": summary["sharpe"],
        "sortino": summary["sortino"],
        "calmar": summary["calmar"],
        "profit_factor": summary.get("profit_factor", 0.0),
        "expectancy_usd": summary.get("expectancy_usd", 0.0),
        "num_closed_trades": summary.get("trades", 0),
        "final_equity_usd": summary["final_equity_usd"],
    }
