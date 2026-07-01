"""Strateji kaydı: ada göre strateji oluşturma/listeleme.

Yeni strateji eklemek için: BaseStrategy'den türet, modülünde `register(MyStrategy)`
çağır (veya strategies/__init__ içinde topla). Manager bu kayıttan örnekler.
"""
from __future__ import annotations

from engine.strategy.base import BaseStrategy, StrategyParams

# ad -> strateji sınıfı
_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    """Bir strateji sınıfını kaydeder (dekoratör olarak da kullanılabilir)."""
    name = getattr(cls, "name", None)
    if not name or name == "base":
        raise ValueError(f"Strateji 'name' tanımlamalı: {cls}")
    _REGISTRY[name] = cls
    return cls


def available() -> list[str]:
    """Kayıtlı strateji adları."""
    return sorted(_REGISTRY.keys())


def create(name: str, params: dict[str, float] | None = None) -> BaseStrategy:
    """Ada göre strateji örneği üretir."""
    if name not in _REGISTRY:
        raise KeyError(f"Bilinmeyen strateji: '{name}'. Mevcut: {available()}")
    return _REGISTRY[name](StrategyParams(values=params or {}))


def is_registered(name: str) -> bool:
    return name in _REGISTRY
