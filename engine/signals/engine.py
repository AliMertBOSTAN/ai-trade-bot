"""Hibrit sinyal motoru.

1) Teknik göstergelerden kural tabanlı bir aday karar + güven üretir (ön-filtre).
2) LLM mevcutsa kararı doğrulatır/iyileştirir; iki katman birleştirilir (hibrit).
   LLM yoksa saf teknik karar kullanılır (fail-safe).
"""
from __future__ import annotations

from engine.indicators.technical import compute_snapshot
from engine.models import TechnicalSnapshot, TradeSignal
from engine.signals import llm


def _rule_decision(t: TechnicalSnapshot) -> tuple[str, float]:
    """Basit ama sağlam kural seti -> (action, confidence)."""
    score = 0.0
    # RSI aşırı bölgeleri
    if t.rsi < 30:
        score += 0.35
    elif t.rsi > 70:
        score -= 0.35
    # trend (EMA crossover)
    if t.ema_fast > t.ema_slow:
        score += 0.25
    else:
        score -= 0.25
    # MACD ivmesi
    if t.macd > t.macd_signal:
        score += 0.20
    else:
        score -= 0.20
    # momentum
    if t.momentum > 1.0:
        score += 0.20
    elif t.momentum < -1.0:
        score -= 0.20

    if score >= 0.4:
        return "BUY", min(1.0, abs(score))
    if score <= -0.4:
        return "SELL", min(1.0, abs(score))
    return "HOLD", 1.0 - abs(score)


def _returns(closes: list[float]) -> list[float]:
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1]:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100)
    return out


def generate_signal(chain_id: int, base: str, quote: str,
                    closes: list[float]) -> TradeSignal:
    tech = compute_snapshot(closes)
    rule_action, rule_conf = _rule_decision(tech)

    # LLM katmanı (hibrit)
    advice = llm.advise(base, quote, tech, rule_action, _returns(closes))

    if advice and advice.get("action") in ("BUY", "SELL", "HOLD"):
        llm_action = advice["action"]
        llm_conf = float(advice.get("confidence", 0.5))
        rationale = advice.get("rationale", "")
        # Hibrit füzyon: iki katman hemfikirse güveni yükselt, çelişirse düşür
        if llm_action == rule_action:
            action = rule_action
            confidence = min(1.0, 0.5 * rule_conf + 0.5 * llm_conf + 0.1)
        else:
            # çelişki -> daha temkinli olan LLM kararını al, güveni kıs
            action = llm_action
            confidence = max(0.0, 0.5 * llm_conf)
        source = "hybrid"
    else:
        action = rule_action
        confidence = rule_conf
        rationale = (
            f"RSI={tech.rsi:.0f}, "
            f"trend={'yukarı' if tech.ema_fast > tech.ema_slow else 'aşağı'}, "
            f"momentum={tech.momentum:.1f}%"
        )
        source = "technical"

    return TradeSignal(
        chain_id=chain_id, base=base, quote=quote,
        action=action, confidence=confidence,
        technical=tech, rationale=rationale, source=source,
    )
