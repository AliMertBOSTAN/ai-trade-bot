"""Risk-ayarlı performans metrikleri (saf, bağımlılıksız).

Tüm fonksiyonlar saf ve test edilebilir. Equity eğrisi ve/veya işlem PnL'lerinden
Sharpe, Sortino, max drawdown, Calmar, kazanma oranı, profit factor, expectancy.
"""
from __future__ import annotations

import math

# Yıllıklandırma için periyot/yıl (saatlik mumda ~ 24*365; günlükte 252).
# Backtest tarafı interval'e göre geçirebilir; varsayılan 252 (günlük benzeri).
DEFAULT_PERIODS_PER_YEAR = 252


def returns_from_equity(equity: list[float]) -> list[float]:
    """Equity serisinden periyot getirileri (basit getiri)."""
    out = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev > 0:
            out.append((equity[i] - prev) / prev)
    return out


def sharpe(returns: list[float], periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
           risk_free: float = 0.0) -> float:
    """Yıllıklandırılmış Sharpe oranı."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free / periods_per_year for r in returns]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return mean / std * math.sqrt(periods_per_year)


def sortino(returns: list[float], periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
            risk_free: float = 0.0) -> float:
    """Yıllıklandırılmış Sortino (sadece aşağı yön oynaklığını cezalandırır)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free / periods_per_year for r in returns]
    mean = sum(excess) / len(excess)
    downside = [min(0.0, r) for r in excess]
    dvar = sum(d ** 2 for d in downside) / len(excess)
    dstd = math.sqrt(dvar)
    if dstd == 0:
        return 0.0
    return mean / dstd * math.sqrt(periods_per_year)


def max_drawdown(equity: list[float]) -> float:
    """En büyük tepe-dip düşüş oranı (0..1)."""
    peak = -math.inf
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def calmar(equity: list[float], periods_per_year: int = DEFAULT_PERIODS_PER_YEAR) -> float:
    """Calmar = yıllıklandırılmış getiri / max drawdown."""
    if len(equity) < 2 or equity[0] <= 0:
        return 0.0
    total_ret = equity[-1] / equity[0] - 1.0
    years = (len(equity) - 1) / periods_per_year
    ann = (1.0 + total_ret) ** (1.0 / years) - 1.0 if years > 0 else total_ret
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return ann / mdd


def trade_stats(pnls: list[float]) -> dict:
    """İşlem PnL listesinden kazanma oranı, profit factor, expectancy.

    pnls: kapanan işlemlerin (SELL) gerçekleşen PnL'leri (USD).
    """
    n = len(pnls)
    if n == 0:
        return {"win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "trades": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)  # pozitif
    win_rate = len(wins) / n
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (
        math.inf if gross_win > 0 else 0.0)
    expectancy = sum(pnls) / n
    return {
        "win_rate": win_rate,
        "profit_factor": profit_factor if profit_factor != math.inf else 999.0,
        "expectancy": expectancy,
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "trades": n,
    }


def summarize(equity: list[float], trade_pnls: list[float] | None = None,
              periods_per_year: int = DEFAULT_PERIODS_PER_YEAR) -> dict:
    """Tam performans özeti (equity + isteğe bağlı işlem PnL'leri)."""
    rets = returns_from_equity(equity)
    start = equity[0] if equity else 0.0
    final = equity[-1] if equity else 0.0
    total_return_pct = ((final - start) / start * 100) if start > 0 else 0.0
    out = {
        "total_return_pct": total_return_pct,
        "final_equity_usd": final,
        "sharpe": round(sharpe(rets, periods_per_year), 3),
        "sortino": round(sortino(rets, periods_per_year), 3),
        "max_drawdown_pct": round(max_drawdown(equity) * 100, 3),
        "calmar": round(calmar(equity, periods_per_year), 3),
    }
    if trade_pnls is not None:
        ts = trade_stats(trade_pnls)
        out.update({
            "win_rate": round(ts["win_rate"], 4),
            "profit_factor": round(ts["profit_factor"], 3),
            "expectancy_usd": round(ts["expectancy"], 4),
            "trades": ts["trades"],
        })
    return out
