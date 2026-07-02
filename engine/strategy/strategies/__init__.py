"""Yerleşik stratejileri içe aktarıp kaydeder."""
from engine.strategy.registry import register
from engine.strategy.strategies.breakout import BreakoutStrategy
from engine.strategy.strategies.funding_arb import FundingArbStrategy
from engine.strategy.strategies.hybrid import HybridStrategy
from engine.strategy.strategies.mean_reversion import MeanReversionStrategy
from engine.strategy.strategies.momentum import MomentumStrategy
from engine.strategy.strategies.pullback import PullbackStrategy
from engine.strategy.strategies.sentiment import SentimentStrategy
from engine.strategy.strategies.squeeze import SqueezeStrategy
from engine.strategy.strategies.trend import TrendFollowingStrategy

register(TrendFollowingStrategy)
register(MeanReversionStrategy)
register(BreakoutStrategy)
register(HybridStrategy)
register(FundingArbStrategy)
register(MomentumStrategy)
register(PullbackStrategy)
register(SqueezeStrategy)
register(SentimentStrategy)

__all__ = [
    "TrendFollowingStrategy",
    "MeanReversionStrategy",
    "BreakoutStrategy",
    "HybridStrategy",
    "FundingArbStrategy",
    "MomentumStrategy",
    "PullbackStrategy",
    "SqueezeStrategy",
    "SentimentStrategy",
]
