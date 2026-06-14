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
from engine.marketdata import news as market_news
from engine.models import TechnicalSnapshot, TradeSignal
from engine.signals import llm

# Güven harmanı ağırlıkları (haber varsa). Toplam = 1.0
W_TECHNICAL = 0.70
W_NEWS = 0.30


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


def decide(t: TechnicalSnapshot) -> tuple[str, float]:
    """Kural-tabanlı (LLM'siz) kararın public arayüzü -> (action, confidence)."""
    return _rule_decision(t)


def rolling_markers(closes: list[float],
                    highs: list[float] | None = None,
                    lows: list[float] | None = None,
                    volumes: list[float] | None = None,
                    min_bars: int = 31) -> list[dict]:
    """Her mumda kural-tabanlı kararı hesaplar; aksiyon DEĞİŞİMİNDE işaret üretir.

    Chart üzerinde geçmiş BUY/SELL oklarını çizmek için kullanılır. Yalnızca
    custom indikatör katmanına dayanır (LLM yok) -> hızlı ve maliyetsiz.
    Dönüş: [{"index": int, "action": "BUY"|"SELL", "confidence": float}]
    """
    n = len(closes)
    markers: list[dict] = []
    prev: str | None = None
    for i in range(min_bars, n + 1):
        tech = compute_snapshot(
            closes[:i],
            highs[:i] if highs else None,
            lows[:i] if lows else None,
            volumes[:i] if volumes else None,
        )
        action, conf = _rule_decision(tech)
        if action in ("BUY", "SELL"):
            if action != prev:
                markers.append({"index": i - 1, "action": action,
                                "confidence": round(conf, 3)})
            prev = action
    return markers


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
    action = rule_action

    # --- Haber katmanı (LLM'siz sentiment) ---
    try:
        news = market_news.sentiment(base)
    except Exception:
        news = {"score": 0.0, "label": "nötr", "count": 0, "matched": 0,
                "market": True, "headlines": []}
    news_score = float(news["score"])

    # --- LLM katmanı (haber bağlamıyla; opsiyonel) ---
    news_summary = (f"{news['label']} ({news_score:+.2f})"
                    + (f"; örnek: {news['headlines'][0]}" if news["headlines"] else ""))
    advice = llm.advise(base, quote, tech, rule_action, _returns(closes), news_summary)
    llm_action = advice.get("action") if advice else None
    llm_used = llm_action in ("BUY", "SELL", "HOLD")

    # --- Teknik özet (her zaman gösterilir) ---
    trend_dir = "yukarı" if tech.supertrend_dir >= 0 else "aşağı"
    tech_state = (f"RSI={tech.rsi:.0f}, ADX={tech.adx:.0f}, Supertrend={trend_dir}, "
                  f"BB%B={tech.bb_pct_b:.0f}, mom={tech.momentum:.1f}%")

    # --- Güven harmanı: teknik (kural skoru) + haber (aksiyona hizalı) ---
    tech_component = rule_conf                      # 0..1
    if action == "BUY":
        news_align = news_score
    elif action == "SELL":
        news_align = -news_score
    else:
        news_align = 0.0
    news_component = (1.0 + news_align) / 2.0        # 0..1

    if news["count"] > 0 and action != "HOLD":
        confidence = W_TECHNICAL * tech_component + W_NEWS * news_component
        weights = {"technical": W_TECHNICAL, "news": W_NEWS}
    else:
        confidence = tech_component
        weights = {"technical": 1.0, "news": 0.0}

    # --- LLM modülasyonu (şeffaf): onay küçük artırır, çelişki işlemi kısar ---
    llm_note = "yok"
    if llm_used:
        if llm_action == action:
            confidence = min(1.0, confidence + 0.05)
            llm_note = "onayladı (+5%)"
        else:
            confidence = min(confidence, 0.50)
            llm_note = f"çelişki → {llm_action} (kısıldı)"

    confidence = _clamp(confidence, 0.0, 1.0)
    source = "hybrid" if llm_used else "technical"

    news_state = (f"haber {news['label']} ({news_score:+.2f}, {news['count']} başlık"
                  + (" · piyasa geneli" if news["market"] else "") + ")")
    rationale = f"{tech_state} | {news_state}"
    if llm_used and advice.get("rationale"):
        rationale = f"{advice['rationale']} || {rationale}"

    breakdown = {
        "technicalScore": round(tech_component, 3),
        "technicalState": tech_state,
        "newsScore": round(news_score, 3),
        "newsLabel": news["label"],
        "newsCount": news["count"],
        "newsMatched": news["matched"],
        "newsMarket": news["market"],
        "newsHeadlines": news["headlines"],
        "weights": weights,
        "llmUsed": llm_used,
        "llmAction": llm_action,
        "llmNote": llm_note,
        "finalConfidence": round(confidence, 3),
    }

    return TradeSignal(
        chain_id=chain_id, base=base, quote=quote,
        action=action, confidence=confidence,
        technical=tech, rationale=rationale, source=source,
        breakdown=breakdown,
    )
