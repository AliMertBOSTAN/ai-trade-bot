"""Hibrit sinyal motoru.

1) Teknik gostergelerden kural tabanli bir aday karar + guven uretir (on-filtre).
   Bu katman tamamen LLM'den BAGIMSIZDIR.
2) LLM mevcutsa karari dogrulatir/iyilestirir; iki katman birlestirilir (hibrit).
   LLM yoksa saf teknik karar kullanilir (fail-safe).
"""
from __future__ import annotations

import time

from engine.config.settings import settings
from engine.indicators.technical import compute_snapshot
from engine.marketdata import news as market_news
from engine.models import TechnicalSnapshot, TradeSignal
from engine.signals import llm
from engine.ml.model import MLSignal, blend_confidence
from engine.strategy.regime import mtf_confirm

W_TECHNICAL = 0.70
W_NEWS = 0.30

_LLM_MIN_CONF = 0.55
_LLM_COOLDOWN_S = 900
_llm_last: dict[str, tuple[str, float]] = {}

# Opsiyonel ML modeli (egitilmediyse None -> davranis degismez)
_ml_model: MLSignal | None = None
_ML_BLEND_WEIGHT = 0.25


def set_ml_model(model: MLSignal | None) -> None:
    """Egitilmis ML modelini etkinlestir/devre disi birak."""
    global _ml_model
    _ml_model = model


def load_ml_model(path: str) -> bool:
    """Diskten ML modeli yukle. Basarisizsa sessizce False."""
    global _ml_model
    try:
        _ml_model = MLSignal.load(path)
        return True
    except Exception:
        _ml_model = None
        return False


def ml_active() -> bool:
    return _ml_model is not None


def _should_consult_llm(base: str, action: str, rule_conf: float) -> bool:
    """LLM cagrisi gercekten degerli mi? (token israfini onler.)"""
    if settings.llm_provider == "none" or action == "HOLD":
        return False
    if rule_conf < _LLM_MIN_CONF:
        return False
    prev = _llm_last.get(base)
    now = time.time()
    if prev and prev[0] == action and (now - prev[1]) < _LLM_COOLDOWN_S:
        return False
    _llm_last[base] = (action, now)
    return True


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _rule_decision(t: TechnicalSnapshot) -> tuple[str, float]:
    """LLM'siz, cok-gostergeli kural seti -> (action, confidence)."""
    # --- Trend blogu (-1..+1) ---
    trend = 0.0
    trend += 0.25 if t.ema_fast > t.ema_slow else -0.25
    trend += 0.20 if t.macd > t.macd_signal else -0.20
    trend += 0.25 * t.supertrend_dir
    trend += 0.10 * t.psar_dir
    if t.ichimoku_kijun:
        trend += 0.10 if t.price > t.ichimoku_kijun else -0.10
    trend += 0.10 if t.plus_di > t.minus_di else -0.10
    trend += 0.15 * t.smc_trend
    trend += 0.10 * t.ma_cross_dir
    trend += 0.12 * t.swing_trend     # Dow yapisi (HH+HL / LH+LL)
    trend = _clamp(trend)

    # --- Salinim blogu (asiri satim -> +, asiri alim -> -) ---
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
    osc += 0.15 * t.rsi_div
    osc = _clamp(osc)

    # --- Momentum blogu (-1..+1) ---
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
    mom += 0.10 * t.fvg_bias
    mom = _clamp(mom)

    # --- ADX trend-gucu kapisi ---
    trend_strength = _clamp(t.adx / 25.0, 0.0, 1.0)
    w_trend = 0.45 * trend_strength
    w_mom = 0.30
    w_osc = 0.25 + 0.45 * (1.0 - trend_strength)

    score = w_trend * trend + w_mom * mom + w_osc * osc
    score = _clamp(score)

    # --- guven kalibrasyonu ---
    # Guven yalniz |skor|'a degil; bloklarin UYUMUNA (trend+mom+osc ayni yonde mi)
    # ve trend gucune (ADX) de baglidir. Guclu/hizali kurulumlar yuksek guven (0.73+)
    # alir; karisik/zayif sinyaller dusuk kalip esikle elenir.
    sgn = 1.0 if score >= 0 else -1.0
    blocks = (trend, mom, osc)
    agree = sum(1 for b in blocks if abs(b) > 0.05 and (b > 0) == (sgn > 0))
    align = agree / 3.0
    adx_factor = _clamp(t.adx / 40.0, 0.0, 1.0)
    conf = _clamp(0.50 * abs(score) + 0.30 * align + 0.20 * adx_factor, 0.0, 1.0)

    # --- rejim kapisi: olu/yonsuz piyasa (cok dusuk ADX) trend-takip whipsaw'a
    # yol acar -> islem ACMA (HOLD). Yataydaki asiri-islem zararini onler.
    if t.adx < 18.0:
        return "HOLD", 1.0 - abs(score)

    # --- aksiyon esigi (choppy piyasada asiri islemi azalt) ---
    act_thr = 0.35 + 0.10 * (1.0 - trend_strength)

    if score >= act_thr:
        return "BUY", conf
    if score <= -act_thr:
        return "SELL", conf
    return "HOLD", 1.0 - abs(score)


def decide(t: TechnicalSnapshot) -> tuple[str, float]:
    """Kural-tabanli (LLM'siz) kararin public arayuzu -> (action, confidence)."""
    return _rule_decision(t)


def rolling_markers(closes: list[float],
                    highs: list[float] | None = None,
                    lows: list[float] | None = None,
                    volumes: list[float] | None = None,
                    min_bars: int = 31) -> list[dict]:
    """Her mumda kural-tabanli karari hesaplar; aksiyon DEGISIMINDE isaret uretir."""
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
                    volumes: list[float] | None = None,
                    htf_closes: list[float] | None = None,
                    htf_highs: list[float] | None = None,
                    htf_lows: list[float] | None = None,
                    htf_volumes: list[float] | None = None) -> TradeSignal:
    tech = compute_snapshot(closes, highs, lows, volumes)
    rule_action, rule_conf = _rule_decision(tech)
    action = rule_action

    try:
        news = market_news.sentiment(base)
    except Exception:
        news = {"score": 0.0, "label": "notr", "count": 0, "matched": 0,
                "market": True, "headlines": []}
    news_score = float(news["score"])

    news_summary = (f"{news['label']} ({news_score:+.2f})"
                    + (f"; ornek: {news['headlines'][0]}" if news["headlines"] else ""))
    if _should_consult_llm(base, rule_action, rule_conf):
        _candles = {"closes": closes, "highs": highs or closes,
                    "lows": lows or closes,
                    "opens": ([closes[0]] + closes[:-1]) if closes else []}
        advice = llm.advise(base, quote, tech, rule_action, _returns(closes),
                            news_summary, candles=_candles)
    else:
        advice = None
    llm_action = advice.get("action") if advice else None
    llm_used = llm_action in ("BUY", "SELL", "HOLD")

    trend_dir = "yukari" if tech.supertrend_dir >= 0 else "asagi"
    tech_state = (f"RSI={tech.rsi:.0f}, ADX={tech.adx:.0f}, Supertrend={trend_dir}, "
                  f"BB%B={tech.bb_pct_b:.0f}, mom={tech.momentum:.1f}%")

    tech_component = rule_conf
    if action == "BUY":
        news_align = news_score
    elif action == "SELL":
        news_align = -news_score
    else:
        news_align = 0.0
    news_component = (1.0 + news_align) / 2.0

    if news["count"] > 0 and action != "HOLD":
        confidence = W_TECHNICAL * tech_component + W_NEWS * news_component
        weights = {"technical": W_TECHNICAL, "news": W_NEWS}
    else:
        confidence = tech_component
        weights = {"technical": 1.0, "news": 0.0}

    llm_note = "yok"
    if llm_used:
        if llm_action == action:
            confidence = min(1.0, confidence + 0.05)
            llm_note = "onayladi (+5%)"
        else:
            confidence = min(confidence, 0.50)
            llm_note = f"celiski -> {llm_action} (kisildi)"

    confidence = _clamp(confidence, 0.0, 1.0)

    # --- Opsiyonel ML harmanlama (model eğitildiyse) ---
    ml_prob = None
    ml_note = "yok"
    if _ml_model is not None and action in ("BUY", "SELL"):
        try:
            ml_prob = _ml_model.predict_up(tech)
            before = confidence
            confidence = blend_confidence(confidence, ml_prob, action,
                                          weight=_ML_BLEND_WEIGHT)
            ml_note = f"yukselis olasiligi={ml_prob:.2f} ({before:.2f}->{confidence:.2f})"
        except Exception:
            ml_prob = None
    confidence = _clamp(confidence, 0.0, 1.0)
    source = "hybrid" if llm_used else "technical"
    if _ml_model is not None:
        source = source + "+ml"

    # --- Cok-zaman-dilimi (MTF) onayi: ust-TF celisirse guveni kis ---
    mtf_note = "yok"
    if htf_closes is not None and len(htf_closes) >= 35 and action in ("BUY", "SELL"):
        try:
            htf_tech = compute_snapshot(htf_closes, htf_highs, htf_lows, htf_volumes)
            if mtf_confirm(action, htf_tech):
                confidence = min(1.0, confidence + 0.03)
                mtf_note = "ust-TF onayladi (+3%)"
            else:
                confidence = min(confidence, 0.50)
                mtf_note = "ust-TF celiskili (kisildi)"
        except Exception:
            pass
    confidence = _clamp(confidence, 0.0, 1.0)

    news_state = (f"haber {news['label']} ({news_score:+.2f}, {news['count']} baslik"
                  + (" - piyasa geneli" if news["market"] else "") + ")")
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
        "mlProb": round(ml_prob, 3) if ml_prob is not None else None,
        "mtfNote": mtf_note,
        "mlNote": ml_note,
        "finalConfidence": round(confidence, 3),
    }

    return TradeSignal(
        chain_id=chain_id, base=base, quote=quote,
        action=action, confidence=confidence,
        technical=tech, rationale=rationale, source=source,
        breakdown=breakdown,
    )
