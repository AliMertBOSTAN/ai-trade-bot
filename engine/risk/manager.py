"""Risk yonetimi (Risk Controls).

Bir sinyali isleme donusturmeden ONCE gecmesi gereken kapilar. Her ret bir
gerekce ile doner; sessiz basarisizlik yoktur.

allow_short=True iken SELL, pozisyon yokken SHORT acabilir (backtest/perp).
Varsayilan long-only davranis (allow_short=False) DEGISMEZ.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from engine.config.settings import RiskConfig, settings
from engine.dex import gas
from engine.models import Position, TradeSignal

log = logging.getLogger("risk")


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    size_usd: float = 0.0


class RiskManager:
    def __init__(self, risk: RiskConfig, allow_short: bool = False):
        self.risk = risk
        self.allow_short = allow_short
        self.day_realized_pnl = 0.0

    def reset_daily(self) -> None:
        self.day_realized_pnl = 0.0

    def record_realized(self, pnl_usd: float) -> None:
        self.day_realized_pnl += pnl_usd

    def kill_switch_triggered(self) -> bool:
        return self.day_realized_pnl <= -abs(self.risk.max_daily_loss_usd)

    def _gas_ok(self, chain_id: int, size: float) -> bool:
        gas_cost = gas.gas_cost_usd(chain_id, gas.GAS_UNITS_SWAP)
        return not (settings.is_live and gas_cost > size * gas.MAX_GAS_FRACTION)

    def _edge_ok(self, tech) -> tuple[bool, str]:
        """Maliyet-farkinda giris kapisi (min_edge_ratio > 0 iken).

        Beklenen lehte hareket (edge_atr_mult x ATR / fiyat) tur maliyetinin
        (slippage + taker fee, iki yon) min_edge_ratio kati altindaysa yeni
        pozisyon ACMA — dusuk oynaklikta islem maliyeti kari yer (olcumler:
        docs/BACKTEST_IMPROVEMENTS.md). ATR/fiyat yoksa kapi pasiftir (fail-safe).
        """
        r = self.risk
        if r.min_edge_ratio <= 0 or tech is None:
            return True, ""
        price = float(getattr(tech, "price", 0.0) or 0.0)
        atr = float(getattr(tech, "atr", 0.0) or 0.0)
        if price <= 0 or atr <= 0:
            return True, ""
        # Tek kaynak: paper broker'in taker fee sabiti (canli DEX fee'ye yakin).
        from engine.trading.paper_broker import TAKER_FEE_PCT
        expected = r.edge_atr_mult * atr / price
        round_trip = 2.0 * (r.slippage_bps / 10_000.0) + 2.0 * TAKER_FEE_PCT
        if expected < r.min_edge_ratio * round_trip:
            return False, (f"Beklenen hareket %{expected * 100:.2f} < "
                           f"{r.min_edge_ratio:.1f}x maliyet %{round_trip * 100:.2f} "
                           f"- islem ekonomik degil")
        return True, ""

    def _intel_ok(self, signal: TradeSignal) -> tuple[bool, str]:
        """Piyasa yapisi kapisi (intel_block_score > 0 iken).

        Makro rejim + on-chain akis + Hyperliquid/whale panellerinin birlesik
        bias'i karara TERS ve esikten guclu ise YENI pozisyon acilmaz. Kapi
        yalnizca ACILISI etkiler; kapanis/cover her zaman serbesttir. Intel
        verisi yoksa (test, ag yok, INTEL_SIGNAL=0) kapi PASIFTIR (fail-safe).
        """
        thr = self.risk.intel_block_score
        if thr <= 0:
            return True, ""
        try:
            from engine.marketdata.intel import bias as intel_bias
            b = intel_bias.combined(signal.base)
        except Exception:  # noqa: BLE001
            return True, ""
        if not b.get("ok"):
            return True, ""
        raw = float(b.get("score") or 0.0)
        aligned = raw if signal.action == "BUY" else -raw
        if aligned <= -thr:
            return False, (f"Piyasa yapisi karara ters ({b.get('label')}, "
                           f"skor {raw:+.2f} <= -{thr:.2f}) - yeni pozisyon yok")
        return True, ""

    def evaluate(self, signal: TradeSignal, open_positions: dict[str, Position],
                 cash_usd: float) -> RiskDecision:
        if self.kill_switch_triggered():
            return RiskDecision(False, "Gunluk zarar limiti asildi (kill-switch)")
        if signal.action == "HOLD":
            return RiskDecision(False, "HOLD - islem yok")
        if signal.confidence < self.risk.min_confidence:
            return RiskDecision(
                False, f"Guven {signal.confidence:.2f} < esik {self.risk.min_confidence:.2f}")

        key = f"{signal.chain_id}:{signal.base}"
        pos = open_positions.get(key)

        if signal.action == "BUY":
            # mevcut short'u kapatma (cover) her zaman serbest
            if pos is not None and pos.amount < 0:
                return RiskDecision(True, "short kapat",
                                    size_usd=abs(pos.amount) * signal.technical.price)
            if key not in open_positions and len(open_positions) >= self.risk.max_open_positions:
                return RiskDecision(False, "Azami pozisyon sayisina ulasildi")
            edge_ok, edge_reason = self._edge_ok(signal.technical)
            if not edge_ok:
                return RiskDecision(False, edge_reason)
            intel_ok, intel_reason = self._intel_ok(signal)
            if not intel_ok:
                return RiskDecision(False, intel_reason)
            size = min(self.risk.max_position_usd, cash_usd * 0.95)
            if size < 10:
                return RiskDecision(False, "Yetersiz nakit")
            if not self._gas_ok(signal.chain_id, size):
                return RiskDecision(False, "Gas - islem ekonomik degil")
            return RiskDecision(True, "onaylandi", size_usd=size)

        # SELL
        if pos is not None and pos.amount > 0:
            # long kapat
            return RiskDecision(True, "long kapat",
                                size_usd=pos.amount * signal.technical.price)
        if not self.allow_short:
            return RiskDecision(False, "Satilacak pozisyon yok")
        # SHORT ac/ekle
        if pos is None and len(open_positions) >= self.risk.max_open_positions:
            return RiskDecision(False, "Azami pozisyon sayisina ulasildi")
        edge_ok, edge_reason = self._edge_ok(signal.technical)
        if not edge_ok:
            return RiskDecision(False, edge_reason)
        intel_ok, intel_reason = self._intel_ok(signal)
        if not intel_ok:
            return RiskDecision(False, intel_reason)
        # DIKKAT: short acilinca satis geliri NAKDI sisirir; cash*0.95 ile
        # boyutlamak her yeni short'u buyutur (gizli kaldirac). Tavan EQUITY
        # uzerinden hesaplanir — kaldiracsiz, long tarafiyla simetrik maruziyet.
        equity = cash_usd + sum(p.amount * p.last_price
                                for p in open_positions.values())
        size = min(self.risk.max_position_usd, max(0.0, equity) * 0.95)
        if size < 10:
            return RiskDecision(False, "Yetersiz sermaye (short)")
        if not self._gas_ok(signal.chain_id, size):
            return RiskDecision(False, "Gas - islem ekonomik degil")
        return RiskDecision(True, "short ac", size_usd=size)

    def gas_ok(self, chain_id: int) -> tuple[bool, float]:
        from engine.web3x.provider import get_web3
        w3 = get_web3(chain_id)
        if w3 is None:
            return True, 0.0
        try:
            gas_gwei = w3.eth.gas_price / 1e9
            return gas_gwei <= self.risk.max_gas_gwei, gas_gwei
        except Exception:
            return True, 0.0

    def min_out(self, expected_out: int) -> int:
        bps = self.risk.slippage_bps
        return int(expected_out * (10_000 - bps) // 10_000)

    def check_stop_take(self, pos: Position, price: float) -> str | None:
        """Stop-loss / take-profit. Short (amount<0) icin yon ters cevrilir."""
        if pos.avg_entry <= 0:
            return None
        change = (price - pos.avg_entry) / pos.avg_entry
        if pos.amount < 0:
            change = -change  # short: fiyat dususe gecince kar
        if change <= -self.risk.stop_loss_pct:
            return "stop-loss"
        if change >= self.risk.take_profit_pct:
            return "take-profit"
        return None
