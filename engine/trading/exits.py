"""Gelişmiş çıkış yönetimi: ATR stop, trailing stop, kademeli TP, başabaş, zaman.

Sabit %5/%10 yerine oynaklığa uyarlı ve kârı koruyan çıkışlar. ExitManager bir
pozisyonun yaşam döngüsü boyunca durum tutar (en yüksek fiyat, kısmi alımlar) ve
her fiyat güncellemesinde bir çıkış kararı önerir.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExitConfig:
    atr_stop_mult: float = 2.0        # ilk stop = giriş - mult*ATR
    trail_mult: float = 2.5           # trailing stop = tepe - mult*ATR
    take_profit_atr: float = 3.0      # ilk kısmi TP hedefi (ATR cinsinden)
    partial_tp_fraction: float = 0.5  # hedefe ulaşınca pozisyonun yarısını al
    breakeven_atr: float = 1.0        # bu kadar ATR kâra geçince stop'u girişe çek
    max_bars: int = 0                 # >0 ise bu kadar bar sonra zaman-tabanlı çıkış


@dataclass
class ExitState:
    entry: float
    atr: float
    side: str = "long"               # şimdilik long (spot); short ileride
    highest: float = field(default=0.0)
    partial_done: bool = False
    breakeven_moved: bool = False
    bars_held: int = 0

    def __post_init__(self):
        if self.highest == 0.0:
            self.highest = self.entry


@dataclass
class ExitDecision:
    action: str                       # "HOLD" | "EXIT" | "PARTIAL"
    fraction: float = 1.0             # kapatılacak oran
    reason: str = ""


class ExitManager:
    def __init__(self, cfg: ExitConfig | None = None):
        self.cfg = cfg or ExitConfig()

    def stop_price(self, st: ExitState) -> float:
        """Geçerli stop fiyatı: trailing (tepe-bazlı) ile ilk ATR stop'un yükseği."""
        c = self.cfg
        initial = st.entry - c.atr_stop_mult * st.atr
        trail = st.highest - c.trail_mult * st.atr
        stop = max(initial, trail)
        if st.breakeven_moved:
            stop = max(stop, st.entry)
        return stop

    def update(self, st: ExitState, price: float) -> ExitDecision:
        """Bir fiyat güncellemesinde çıkış kararı önerir ve durumu günceller."""
        c = self.cfg
        st.bars_held += 1
        st.highest = max(st.highest, price)

        # başabaşa çekme
        if not st.breakeven_moved and price >= st.entry + c.breakeven_atr * st.atr:
            st.breakeven_moved = True

        # zaman-tabanlı çıkış
        if c.max_bars > 0 and st.bars_held >= c.max_bars:
            return ExitDecision("EXIT", 1.0, f"zaman aşımı ({st.bars_held} bar)")

        # stop / trailing
        if price <= self.stop_price(st):
            reason = "trailing-stop" if st.highest > st.entry else "stop-loss"
            return ExitDecision("EXIT", 1.0, reason)

        # kademeli kâr alma (bir kez)
        if not st.partial_done and price >= st.entry + c.take_profit_atr * st.atr:
            st.partial_done = True
            return ExitDecision("PARTIAL", c.partial_tp_fraction, "kısmi kâr (TP1)")

        return ExitDecision("HOLD", 0.0, "")
