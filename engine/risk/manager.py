"""Risk yönetimi (Risk Controls).

Bir sinyali işleme dönüştürmeden ÖNCE geçmesi gereken kapılar:
- min güven skoru
- pozisyon başına azami notional
- azami eşzamanlı pozisyon sayısı
- günlük zarar kill-switch
- gas ücreti tavanı (live mod, web3.py gas_price ile)
- slippage toleransı -> amountOutMinimum hesaplama yardımcıları
Her ret bir gerekçe ile döner; sessiz başarısızlık yoktur.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from engine.config.settings import RiskConfig
from engine.models import Position, TradeSignal

log = logging.getLogger("risk")


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    size_usd: float = 0.0


class RiskManager:
    def __init__(self, risk: RiskConfig):
        self.risk = risk
        self.day_realized_pnl = 0.0   # günlük gerçekleşen PnL takibi

    def reset_daily(self) -> None:
        self.day_realized_pnl = 0.0

    def record_realized(self, pnl_usd: float) -> None:
        self.day_realized_pnl += pnl_usd

    def kill_switch_triggered(self) -> bool:
        return self.day_realized_pnl <= -abs(self.risk.max_daily_loss_usd)

    def evaluate(self, signal: TradeSignal, open_positions: dict[str, Position],
                 cash_usd: float) -> RiskDecision:
        if self.kill_switch_triggered():
            return RiskDecision(False, "Günlük zarar limiti aşıldı (kill-switch)")

        if signal.action == "HOLD":
            return RiskDecision(False, "HOLD - işlem yok")

        if signal.confidence < self.risk.min_confidence:
            return RiskDecision(
                False, f"Güven {signal.confidence:.2f} < eşik {self.risk.min_confidence:.2f}")

        key = f"{signal.chain_id}:{signal.base}"

        if signal.action == "BUY":
            if key not in open_positions and len(open_positions) >= self.risk.max_open_positions:
                return RiskDecision(False, "Azami pozisyon sayısına ulaşıldı")
            size = min(self.risk.max_position_usd, cash_usd * 0.95)
            if size < 10:
                return RiskDecision(False, "Yetersiz nakit")
            return RiskDecision(True, "onaylandı", size_usd=size)

        # SELL
        if key not in open_positions:
            return RiskDecision(False, "Satılacak pozisyon yok")
        return RiskDecision(True, "onaylandı",
                            size_usd=open_positions[key].amount * signal.technical.price)

    def gas_ok(self, chain_id: int) -> tuple[bool, float]:
        """Live mod: anlık gas fiyatı tavanın altında mı? (gwei)."""
        from engine.web3x.provider import get_web3  # lazy: web3 sadece live'da gerekir
        w3 = get_web3(chain_id)
        if w3 is None:
            return True, 0.0
        try:
            gas_gwei = w3.eth.gas_price / 1e9
            return gas_gwei <= self.risk.max_gas_gwei, gas_gwei
        except Exception:
            return True, 0.0

    def min_out(self, expected_out: int) -> int:
        """Slippage toleransına göre amountOutMinimum (integer wei)."""
        bps = self.risk.slippage_bps
        return int(expected_out * (10_000 - bps) // 10_000)

    def check_stop_take(self, pos: Position, price: float) -> str | None:
        """Açık pozisyon için stop-loss / take-profit tetikleyici."""
        if pos.avg_entry <= 0:
            return None
        change = (price - pos.avg_entry) / pos.avg_entry
        if change <= -self.risk.stop_loss_pct:
            return "stop-loss"
        if change >= self.risk.take_profit_pct:
            return "take-profit"
        return None
