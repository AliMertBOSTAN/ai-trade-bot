"""Minimum-kenar (edge) kapısı + paper→live terfi kriterleri.

İki finansal güvenlik:
  1) Beklenen kâr, toplam maliyeti (slippage+ücret+gas) + tampon kadar aşmıyorsa
     işlem AÇMA → ekonomik olmayan işlemleri kökten eler.
  2) Canlıya (live) geçiş için kâğıt (paper) performans eşiği → kanıtlanmamış
     stratejiyi gerçek fonla çalıştırmayı engeller.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EdgeResult:
    ok: bool
    net_edge_usd: float
    reason: str


def expected_edge_usd(expected_move_pct: float, notional_usd: float) -> float:
    """Beklenen brüt kâr (USD) = beklenen yüzde hareket × nominal."""
    return abs(expected_move_pct) / 100.0 * notional_usd


def evaluate_edge(expected_move_pct: float, notional_usd: float,
                  total_cost_usd: float, buffer_usd: float = 1.0,
                  buffer_pct: float = 0.0) -> EdgeResult:
    """Beklenen kâr > maliyet + tampon mı? Değilse işlem reddedilir."""
    gross = expected_edge_usd(expected_move_pct, notional_usd)
    required = total_cost_usd + buffer_usd + buffer_pct / 100.0 * notional_usd
    net = gross - total_cost_usd
    if gross <= required:
        return EdgeResult(False, net,
                          f"kenar yetersiz: brüt {gross:.2f}$ ≤ maliyet+tampon "
                          f"{required:.2f}$")
    return EdgeResult(True, net, f"kenar yeterli: net ~{net:.2f}$")


@dataclass
class PromotionCriteria:
    min_trades: int = 30
    min_sharpe: float = 1.0
    min_win_rate: float = 0.45
    min_profit_factor: float = 1.2
    require_positive_expectancy: bool = True
    max_drawdown_pct: float = 25.0


@dataclass
class PromotionResult:
    ready: bool
    reasons: list[str]


def evaluate_promotion(stats: dict, crit: PromotionCriteria | None = None) -> PromotionResult:
    """Kâğıt performans istatistiklerine göre live'a hazır mı?

    stats: backtest/paper özeti (sharpe, win_rate, profit_factor, expectancy_usd,
    max_drawdown_pct, trades/num_closed_trades).
    """
    c = crit or PromotionCriteria()
    reasons: list[str] = []
    trades = stats.get("trades", stats.get("num_closed_trades", 0))

    if trades < c.min_trades:
        reasons.append(f"yetersiz işlem ({trades}<{c.min_trades})")
    if stats.get("sharpe", 0.0) < c.min_sharpe:
        reasons.append(f"Sharpe düşük ({stats.get('sharpe', 0):.2f}<{c.min_sharpe})")
    if stats.get("win_rate", 0.0) < c.min_win_rate:
        reasons.append(f"kazanma oranı düşük ({stats.get('win_rate', 0):.2f}<{c.min_win_rate})")
    if stats.get("profit_factor", 0.0) < c.min_profit_factor:
        reasons.append(
            f"profit factor düşük ({stats.get('profit_factor', 0):.2f}<{c.min_profit_factor})")
    if c.require_positive_expectancy and stats.get("expectancy_usd", 0.0) <= 0:
        reasons.append("beklenti (expectancy) pozitif değil")
    if stats.get("max_drawdown_pct", 100.0) > c.max_drawdown_pct:
        reasons.append(
            f"max drawdown yüksek ({stats.get('max_drawdown_pct', 0):.1f}%>{c.max_drawdown_pct}%)")

    return PromotionResult(ready=not reasons, reasons=reasons)
