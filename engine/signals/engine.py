"""Hibrit sinyal motoru.

1) Teknik göstergelerden kural tabanlı bir aday karar + güven üretir (ön-filtre).
   Bu katman tamamen LLM'den BAĞIMSIZDIR: klasik göstergeler (RSI, EMA, MACD,
   Bollinger, Stochastic, ADX, ATR, CCI, Williams %R, MFI, OBV, VWAP) ve
   TradingView'de popüler gelişmiş göstergeler (Supertrend, Ichimoku, Parabolic
   SAR, Keltner/Donchian, Awesome Oscillator, TTM Squeeze, WaveTrend) birlikte
   ağırlıklı bir skora dönüştürülür. ADX bir trend-gücü filtresi olarak çalışır.
2) LLM mevcutsa kararı doğrulatır/iyileştirir; iki katman birleştirilir (hibrit).
   LLM yoksa saf teknik karar kullanılır (fail-safe).
"""
from __future__ import annotations

from engine.indicators.technical import compute_snapshot
from engine.models import TechnicalSnapshot, TradeSignal
from engine.signals import llm


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _rule_decision(t: TechnicalSnapshot) -> tuple[str, float]:
    """LLM'siz, çok-göstergeli kural seti -> (action, confidence).

    Üç blok birleştirilir:
      • trend takip (EMA/MACD/Supertrend/PSAR/Ichimoku/DMI)
      • salınım / aşırı alım-satım (RSI/StochRSI/Stoch/Williams/CCI/MFI/BB%B/WT)
      • momentum (momentum/ROC/Awesome/Squeeze)
    ADX trend gücüne göre trend bloğunun ağırlığı ölçeklenir (choppy piyasada
    trend sinyallerine daha az güvenilir -> aşırı işlemi azaltır).
    """
    # --- Trend bloğu (-1..+1) ---
    trend = 0.0
    trend += 0.25 if t.ema_fast > t.ema_slow else -0.25
    trend += 0.20 if t.macd > t.macd_signal else -0.20
    trend += 0.25 * t.supertrend_dir          # +1/-1
    trend += 0.10 * t.psar_dir                 # +1/-1
    if t.ichimoku_kijun:
        trend += 0.10 if t.price > t.ichimoku_kijun else -0.10
    trend += 0.10 if t.plus_di > t.minus_di else -0.10
    trend = _clamp(trend)

    # --- Salınım bloğu (aşırı satım -> +, aşırı alım -> -) ---
    osc = 0.0
    if t.rsi < 30:
        osc += 0.25
    elif t.rsi > 70:
        osc -= 0.25
    if t.stoch_rsi < 20:
        osc += 0.15
    elif t.stoch_rsi > 80:
        osc -= 0.15
    if t.stoch_k < 20:
        osc += 0.10
    elif t.stoch_k > 80:
        osc -= 0.10
    if t.williams_r < -80:
        osc += 0.10
    elif t.williams_r > -20:
        osc -= 0.10
    if t.cci < -100:
        osc += 0.10
    elif t.cci > 100:
        osc -= 0.10
    if t.mfi < 20:
        osc += 0.10
    elif t.mfi > 80:
        osc -= 0.10
    if t.bb_pct_b < 5:
        osc += 0.10
    elif t.bb_pct_b > 95:
        osc -= 0.10
    if t.wavetrend1 < -60:
        osc += 0.10
    elif t.wavetrend1 > 60:
        osc -= 0.10
    osc = _clamp(osc)

    # --- Momentum bloğu (-1..+1) ---
    mom = 0.0
    if t.momentum > 1.0:
        mom += 0.40
    elif t.momentum < -1.0:
        mom -= 0.40
    mom += 0.30 if t.awesome > 0 else -0.30
    if t.squeeze_momentum > 0:
        mom += 0.30
    elif t.squeeze_momentum < 0:
        mom -= 0.30
    mom = _clamp(mom)

    # --- ADX trend-gücü kapısı ---
    # ADX>=25 güçlü trend -> trend bloğu tam ağırlık; ADX düşükse kıs.
    trend_strength = _clamp(t.adx / 25.0, 0.0, 1.0)
    w_trend = 0.45 * trend_strength
    w_mom = 0.30
    w_osc = 0.25 + 0.45 * (1.0 - trend_strength)  # zayıf trendde salınıma yaslan

    score = w_trend * trend + w_mom * mom + w_osc * osc
    score = _clamp(score)

    if score >= 0.35:
        return "BUY", min(1.0, abs(score))
    if score <= -0.35:
        return "SELL", min(1.0, abs(score))
    return "HOLD", 1.0 - abs(score)


def _returns(closes: list[float]) -> list[float]:
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1]:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100)
    return out


def generate_signal(chain_id: int, base: str, quote: str,
                    closes: list[float],
                    highs: list[float] | None = None,
                    lows: list[float] | None = None,
                    volumes: list[float] | None = None) -> TradeSignal:
    tech = compute_snapshot(closes, highs, lows, volumes)
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
        trend_dir = "yukarı" if tech.supertrend_dir >= 0 else "aşağı"
        rationale = (
            f"RSI={tech.rsi:.0f}, StochRSI={tech.stoch_rsi:.0f}, "
            f"ADX={tech.adx:.0f}, Supertrend={trend_dir}, "
            f"BB%B={tech.bb_pct_b:.0f}, mom={tech.momentum:.1f}%"
        )
        source = "technical"

    return TradeSignal(
        chain_id=chain_id, base=base, quote=quote,
        action=action, confidence=confidence,
        technical=tech, rationale=rationale, source=source,
    )
