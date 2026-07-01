"""Strateji yapilandirmasi — env'den coklu-strateji StrategyManager kurar.

STRATEGIES ortam degiskeni bicimi (virgulle ayrilmis):
    "hybrid:1.0, trend:1.0, mean_reversion:0.5"
Her giris: ad[:agirlik]. Agirlik verilmezse 1.0. Bosversa varsayilan: dort spot strateji.
"""
from __future__ import annotations

import os

from engine.strategy.manager import StrategyManager
from engine.strategy import registry


def parse_strategies(spec: str) -> list[dict]:
    """'hybrid:1, trend:0.5' -> [{name, weight, enabled}] (gecersizleri atlar)."""
    import engine.strategy.strategies  # noqa: F401  (kayitlari yukle)
    out: list[dict] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, w = part.partition(":")
        name = name.strip()
        if not registry.is_registered(name):
            continue
        try:
            weight = float(w) if w.strip() else 1.0
        except ValueError:
            weight = 1.0
        out.append({"name": name, "weight": weight, "enabled": True})
    return out


# Env tanimli degilse varsayilan: dort spot strateji ayni anda aktif (esit agirlik).
# (funding_arb perp funding baglami gerektirir; spot orkestratorde HOLD'da kalacagindan
#  varsayilana DAHIL EDILMEZ — STRATEGIES ile acikca eklenebilir.)
_DEFAULT_STRATEGIES = [
    {"name": "hybrid", "weight": 1.0, "enabled": True},
    {"name": "trend", "weight": 1.0, "enabled": True},
    {"name": "mean_reversion", "weight": 1.0, "enabled": True},
    {"name": "breakout", "weight": 1.0, "enabled": True},
]


def default_manager() -> StrategyManager:
    """Env STRATEGIES'ten manager kurar; bos/gecersizse dort spot strateji aktif."""
    spec = os.getenv("STRATEGIES", "").strip()
    config = parse_strategies(spec) if spec else []
    if not config:
        config = list(_DEFAULT_STRATEGIES)
    return StrategyManager.from_config(config)
