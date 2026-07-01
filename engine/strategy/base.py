"""Strateji arayüzü ve ortak veri yapıları.

Bir Strateji, bir piyasa bağlamı (StrategyContext) alır ve bir StrategySignal
döndürür. Stratejiler birbirinden BAĞIMSIZDIR; StrategyManager onları aynı anda
çalıştırır ve her birinin kendi sermaye dilimini yönetir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from engine.models import Position, TechnicalSnapshot

Action = str  # "BUY" | "SELL" | "HOLD"


@dataclass
class StrategyContext:
    """Bir stratejinin karar vermek için ihtiyaç duyduğu her şey."""
    base: str
    quote: str
    chain_id: int
    closes: list[float]
    highs: list[float]
    lows: list[float]
    volumes: list[float]
    tech: TechnicalSnapshot
    price: float
    # Bu stratejinin SADECE kendi dilimindeki açık pozisyonu (yoksa None)
    position: Position | None = None
    # Bu stratejiye tahsis edilmiş kullanılabilir nakit (USD)
    cash_allocated: float = 0.0
    # Haber sentiment skoru (-1..+1); strateji isterse kullanır
    news_score: float = 0.0
    # İsteğe bağlı: perp funding oranı (%/saat) — funding stratejileri için
    funding_pct: float | None = None
    bars_held: int = 0  # pozisyon kaç bardır açık (zaman-tabanlı çıkış için)


@dataclass
class StrategySignal:
    """Bir stratejinin tek bir enstrüman için kararı."""
    action: Action
    confidence: float                 # 0..1
    reason: str = ""
    strategy: str = ""                # StrategyManager doldurur
    # İsteğe bağlı strateji-özel boyut/çıkış ipuçları (manager/risk dikkate alır)
    size_usd: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    atr: float | None = None          # ATR tabanlı boyut/stop için


@dataclass
class StrategyParams:
    """Bir stratejinin ayarlanabilir parametreleri (ad -> değer)."""
    values: dict[str, float] = field(default_factory=dict)

    def get(self, key: str, default: float) -> float:
        return self.values.get(key, default)


class Strategy(Protocol):
    """Tüm stratejilerin uyması gereken arayüz."""

    name: str

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        """Bağlama göre BUY/SELL/HOLD kararı üretir."""
        ...


class BaseStrategy:
    """Kolaylık taban sınıfı: name + params tutar, evaluate'i alt sınıf yazar."""

    name: str = "base"

    def __init__(self, params: StrategyParams | None = None):
        self.params = params or StrategyParams()

    def p(self, key: str, default: float) -> float:
        return self.params.get(key, default)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:  # pragma: no cover
        raise NotImplementedError

    def _sig(self, action: Action, conf: float, reason: str = "",
             **extra) -> StrategySignal:
        return StrategySignal(action=action, confidence=max(0.0, min(1.0, conf)),
                              reason=reason, strategy=self.name, **extra)
