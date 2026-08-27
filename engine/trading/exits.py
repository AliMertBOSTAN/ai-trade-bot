"""Gelişmiş çıkış yönetimi: ATR stop, trailing stop, kademeli TP, başabaş, zaman.

Sabit %5/%10 yerine oynaklığa uyarlı ve kârı koruyan çıkışlar. ExitManager bir
pozisyonun yaşam döngüsü boyunca durum tutar (en yüksek/en düşük fiyat, kısmi
alımlar) ve her fiyat güncellemesinde bir çıkış kararı önerir.

İki yön de desteklenir: side="long" (spot/perp) ve side="short" (backtest/perp;
spot DEX'te short yapılamaz). Short tarafta tüm eşikler aynalıdır: trailing
en düşük fiyatı izler, kâr fiyat DÜŞÜNCE oluşur.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExitConfig:
    atr_stop_mult: float = 2.0        # ilk stop = giriş ∓ mult*ATR (yöne göre)
    trail_mult: float = 2.5           # trailing stop = uç fiyat ∓ mult*ATR
    take_profit_atr: float = 3.0      # ilk kısmi TP hedefi (ATR cinsinden)
    partial_tp_fraction: float = 0.5  # hedefe ulaşınca pozisyonun yarısını al
    breakeven_atr: float = 1.0        # bu kadar ATR kâra geçince stop'u girişe çek
    max_bars: int = 0                 # >0 ise bu kadar bar sonra zaman-tabanlı çıkış


@dataclass
class ExitState:
    entry: float
    atr: float
    side: str = "long"               # "long" | "short"
    highest: float = field(default=0.0)   # long trailing ucu
    lowest: float = field(default=0.0)    # short trailing ucu
    partial_done: bool = False
    breakeven_moved: bool = False
    bars_held: int = 0

    def __post_init__(self):
        if self.highest == 0.0:
            self.highest = self.entry
        if self.lowest == 0.0:
            self.lowest = self.entry


@dataclass
class ExitDecision:
    action: str                       # "HOLD" | "EXIT" | "PARTIAL"
    fraction: float = 1.0             # kapatılacak oran
    reason: str = ""


class ExitManager:
    def __init__(self, cfg: ExitConfig | None = None):
        self.cfg = cfg or ExitConfig()

    def stop_price(self, st: ExitState) -> float:
        """Geçerli stop fiyatı (yön-farkında).

        Long: trailing (tepe-bazlı) ile ilk ATR stop'un YÜKSEĞİ (fiyat altında).
        Short: trailing (dip-bazlı) ile ilk ATR stop'un DÜŞÜĞÜ (fiyat üstünde).
        """
        c = self.cfg
        if st.side == "short":
            initial = st.entry + c.atr_stop_mult * st.atr
            trail = st.lowest + c.trail_mult * st.atr
            stop = min(initial, trail)
            if st.breakeven_moved:
                stop = min(stop, st.entry)
            return stop
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
        short = st.side == "short"
        if short:
            st.lowest = min(st.lowest, price)
        else:
            st.highest = max(st.highest, price)

        # başabaşa çekme (yeterince kâra geçince stop girişe alınır)
        if not st.breakeven_moved:
            if short and price <= st.entry - c.breakeven_atr * st.atr:
                st.breakeven_moved = True
            elif not short and price >= st.entry + c.breakeven_atr * st.atr:
                st.breakeven_moved = True

        # zaman-tabanlı çıkış
        if c.max_bars > 0 and st.bars_held >= c.max_bars:
            return ExitDecision("EXIT", 1.0, f"zaman aşımı ({st.bars_held} bar)")

        # stop / trailing
        stop = self.stop_price(st)
        if (short and price >= stop) or (not short and price <= stop):
            in_profit = st.lowest < st.entry if short else st.highest > st.entry
            reason = "trailing-stop" if in_profit else "stop-loss"
            return ExitDecision("EXIT", 1.0, reason)

        # kademeli kâr alma (bir kez)
        if not st.partial_done:
            tp_hit = (price <= st.entry - c.take_profit_atr * st.atr) if short \
                else (price >= st.entry + c.take_profit_atr * st.atr)
            if tp_hit:
                st.partial_done = True
                return ExitDecision("PARTIAL", c.partial_tp_fraction, "kısmi kâr (TP1)")

        return ExitDecision("HOLD", 0.0, "")
