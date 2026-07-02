"""StrategyManager — aynı anda birden çok stratejiyi sermaye tahsisiyle çalıştırır.

Her stratejiye toplam sermayenin bir AĞIRLIĞI (weight) verilir; ağırlıklar
normalize edilir. Manager her enstrüman için tüm etkin stratejileri çalıştırır,
her kararı strateji adıyla ETİKETLER ve stratejinin kendi nakit dilimini geçirir.

Böylece "aynı anda farklı stratejiler" gerçek anlamda izole çalışır: biri trend
takip ederken diğeri ortalamaya dönüş oynayabilir, sermayeleri ayrıdır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from engine.strategy import registry
from engine.strategy.base import BaseStrategy, StrategyContext, StrategySignal


# Kullanici-dostu strateji aciklamalari + uygun rejim (UI "detayli" gosterim).
STRATEGY_INFO: dict[str, dict] = {
    "trend": {
        "title": "Trend Takip",
        "desc": "Güçlü yönlü hareketleri yakalar (EMA kesişimi + ADX). "
                "Trend rejiminde (ADX yüksek) çalışır, yatay piyasada bekler.",
        "regime": "Trend (yukarı/aşağı)",
        "params": "ema_fast, ema_slow, adx_min",
    },
    "mean_reversion": {
        "title": "Ortalamaya Dönüş",
        "desc": "Aşırı alım/satım uçlarından ortalamaya dönüşü oynar "
                "(RSI + Bollinger). Yatay (range) rejimde en verimli.",
        "regime": "Yatay (range)",
        "params": "rsi_low, rsi_high, bb_dev",
    },
    "breakout": {
        "title": "Kırılım",
        "desc": "Direnç/destek kırılımlarında pozisyon açar (Donchian/aralık "
                "kırılımı + hacim). Trend başlangıçlarını hedefler.",
        "regime": "Trend (yukarı/aşağı)",
        "params": "lookback, vol_mult",
    },
    "hybrid": {
        "title": "Hibrit (Teknik + AI)",
        "desc": "Çok-göstergeli kural seti + (varsa) LLM onayı. Her rejimde "
                "çalışır; ADX'i içsel kullanır. Varsayılan ana strateji.",
        "regime": "Tüm rejimler",
        "params": "—",
    },
    "funding_arb": {
        "title": "Funding Arbitrajı",
        "desc": "Perp funding oranı uçlarını kullanır (Hyperliquid). Yön yerine "
                "funding tahsilatı/ödemesi mantığıyla pozisyon alır.",
        "regime": "Funding-tabanlı",
        "params": "funding_threshold",
    },
    "momentum": {
        "title": "Momentum (İvme)",
        "desc": "Fiyat değişim HIZI güçlüyse (10-bar ROC + Awesome Osc. + DI onayı) "
                "ivme yönünde işlem. Trendden farkı: EMA dizilimi beklemez, "
                "hızlanmayı erken yakalar.",
        "regime": "Trend (yukarı/aşağı)",
        "params": "roc_min, adx_min",
    },
    "pullback": {
        "title": "Geri Çekilme (Swing)",
        "desc": "Yapısal yükseliş trendinde (EMA + Dow swing) kısa vadeli dipleri "
                "ALIR, aşırı ısınmada kâr alır. Zirveden kovalamaz — trende "
                "ucuz noktadan katılır.",
        "regime": "Trend (yukarı)",
        "params": "rsi_dip, rsi_exit, adx_min",
    },
    "squeeze": {
        "title": "Sıkışma Patlaması",
        "desc": "Bollinger, Keltner içine girince (TTM squeeze) bekler; sıkışma "
                "AÇILINCA momentum yönünde girer (MACD + Supertrend onayı). "
                "Sıkışma sürerken asla işlem açmaz.",
        "regime": "Tüm rejimler",
        "params": "mom_min",
    },
    "sentiment": {
        "title": "Haber Duyarlılığı",
        "desc": "Belirgin pozitif haber + teknik onay → AL; belirgin negatif haber "
                "→ riskten kaçın (SAT). Haber tek başına yetmez, EMA yönü "
                "onaylamalı. Haber yoksa beklemede kalır.",
        "regime": "Tüm rejimler",
        "params": "score_min",
    },
}


@dataclass
class Allocation:
    """Bir stratejinin tahsisi: örnek + ağırlık + etkin mi."""
    strategy: BaseStrategy
    weight: float = 1.0
    enabled: bool = True


@dataclass
class StrategyManager:
    allocations: list[Allocation] = field(default_factory=list)

    # ---- kurulum ----
    @classmethod
    def from_config(cls, config: list[dict]) -> "StrategyManager":
        """config: [{"name": "trend", "weight": 1.0, "enabled": true, "params": {...}}, ...]"""
        # strategies paketini import ederek kayıtların yüklendiğinden emin ol
        import engine.strategy.strategies  # noqa: F401
        allocs: list[Allocation] = []
        for item in config:
            name = item["name"]
            strat = registry.create(name, item.get("params"))
            allocs.append(Allocation(
                strategy=strat,
                weight=float(item.get("weight", 1.0)),
                enabled=bool(item.get("enabled", True)),
            ))
        return cls(allocations=allocs)

    def add(self, name: str, weight: float = 1.0,
            params: dict | None = None, enabled: bool = True) -> None:
        import engine.strategy.strategies  # noqa: F401
        self.allocations.append(Allocation(
            strategy=registry.create(name, params), weight=weight, enabled=enabled))

    # ---- sermaye tahsisi ----
    def normalized_weights(self) -> dict[str, float]:
        """Etkin stratejilerin normalize edilmiş ağırlıkları (toplam = 1)."""
        active = [a for a in self.allocations if a.enabled]
        total = sum(a.weight for a in active) or 1.0
        return {a.strategy.name: a.weight / total for a in active}

    def capital_for(self, strategy_name: str, total_equity: float) -> float:
        return self.normalized_weights().get(strategy_name, 0.0) * total_equity

    # ---- değerlendirme ----
    def evaluate(self, ctx_factory, total_equity: float) -> list[StrategySignal]:
        """Her etkin strateji için, kendi sermaye dilimiyle bir bağlam üretip çalıştırır.

        ctx_factory(strategy_name, cash_allocated) -> StrategyContext
        (Çağıran taraf piyasa verisini/pozisyonu doldurur; manager sadece sermaye
        dilimini hesaplar ve etiketler.)
        Dönüş: HOLD olmayan, strateji-etiketli sinyaller.
        """
        weights = self.normalized_weights()
        out: list[StrategySignal] = []
        for a in self.allocations:
            if not a.enabled:
                continue
            cash = weights.get(a.strategy.name, 0.0) * total_equity
            ctx: StrategyContext = ctx_factory(a.strategy.name, cash)
            sig = a.strategy.evaluate(ctx)
            sig.strategy = a.strategy.name  # garanti etiket
            out.append(sig)
        return out

    # ---- kullanici kontrolu ----
    def _find(self, name: str) -> "Allocation | None":
        for a in self.allocations:
            if a.strategy.name == name:
                return a
        return None

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Stratejiyi aç/kapa. Yoksa (ama kayıtlıysa) ekleyip açar."""
        a = self._find(name)
        if a is None:
            if enabled and registry.is_registered(name):
                self.add(name, weight=1.0, enabled=True)
                return True
            return False
        a.enabled = enabled
        return True

    def set_weight(self, name: str, weight: float) -> bool:
        """Strateji ağırlığını ayarla (>=0). Yoksa kayıtlıysa ekler."""
        weight = max(0.0, float(weight))
        a = self._find(name)
        if a is None:
            if registry.is_registered(name):
                self.add(name, weight=weight, enabled=True)
                return True
            return False
        a.weight = weight
        return True

    def to_config(self) -> list[dict]:
        """Kalıcılık için yapılandırma (load: from_config)."""
        return [{"name": a.strategy.name, "weight": a.weight,
                 "enabled": a.enabled} for a in self.allocations]

    def active_names(self) -> list[str]:
        return [a.strategy.name for a in self.allocations if a.enabled]

    def describe(self) -> list[dict]:
        w = self.normalized_weights()
        out = []
        for a in self.allocations:
            info = STRATEGY_INFO.get(a.strategy.name, {})
            out.append({
                "name": a.strategy.name,
                "title": info.get("title", a.strategy.name),
                "description": info.get("desc", ""),
                "regime": info.get("regime", ""),
                "params": info.get("params", ""),
                "enabled": a.enabled,
                "weight": a.weight,
                "capital_fraction": round(w.get(a.strategy.name, 0.0), 4) if a.enabled else 0.0,
            })
        return out

    def available_info(self) -> list[dict]:
        """Tüm kayıtlı stratejilerin (aktif olmayanlar dahil) detayı."""
        active = {a.strategy.name for a in self.allocations}
        out = []
        for name in registry.available():
            info = STRATEGY_INFO.get(name, {})
            out.append({
                "name": name,
                "title": info.get("title", name),
                "description": info.get("desc", ""),
                "regime": info.get("regime", ""),
                "params": info.get("params", ""),
                "in_use": name in active,
            })
        return out
