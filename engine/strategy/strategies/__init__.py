"""Yerleşik stratejileri içe aktarıp kaydeder."""
from engine.strategy.registry import register
from engine.strategy.strategies.breakout import BreakoutStrategy
from engine.strategy.strategies.funding_arb import FundingArbStrategy
from engine.strategy.strategies.hybrid import HybridStrategy
from engine.strategy.strategies.mean_reversion import MeanReversionStrategy
from engine.strategy.strategies.trend import TrendFollowingStrategy

register(TrendFollowingStrategy)
register(MeanReversionStrategy)
register(BreakoutStrategy)
register(HybridStrategy)
register(FundingArbStrategy)

__all__ = [
    "TrendFollowingStrategy",
    "MeanReversionStrategy",
    "BreakoutStrategy",
    "HybridStrategy",
    "FundingArbStrategy",
]
