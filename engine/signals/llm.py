"""LLM danışman katmanı (hibrit sinyalin AI bacağı).

Teknik gösterge özetini ve piyasa bağlamını LLM'e verir; yapılandırılmış
bir karar (action + confidence + rationale) ister. Sağlayıcı yoksa veya
hata olursa None döner -> motor teknik karara güvenir (fail-safe).
"""
from __future__ import annotations

import json
import logging

from engine.config.settings import settings
from engine.models import TechnicalSnapshot

log = logging.getLogger("signals.llm")

SYSTEM_PROMPT = (
    "Sen disiplinli bir kantitatif kripto trade danışmanısın. "
    "Sana bir tokenın teknik gösterge anlık görüntüsü ve kural tabanlı ön "
    "kararı verilir. Görevin: aşırı riskli sinyalleri filtrelemek ve nihai "
    "kararı vermek. SADECE şu JSON şemasında yanıt ver: "
    '{"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, '
    '"rationale": "tek cümle gerekçe"}. '
    "Belirsizlikte HOLD ver. Momentum ve trendle çelişen sinyallerde "
    "confidence düşür. Sana ayrıca SON MUMLARIN fiyat-aksiyonu (gövde/fitil, "
    "formasyon, swing yapısı) verilir; grafiği bir teknik analist gibi OKU ve "
    "mum yapısı göstergelerle çelişiyorsa bunu kararına/ gerekçene yansıt."
)


def _candle_summary(closes: list[float], highs: list[float] | None,
                    lows: list[float] | None, opens: list[float] | None = None,
                    n: int = 8) -> str:
    """Son N mumun fiyat-aksiyon özeti: yön, gövde/fitil, basit formasyonlar.

    open verilmezse open[i] ~= close[i-1] yaklasimi kullanilir.
    """
    if not closes or len(closes) < 3:
        return "Mum verisi yetersiz."
    c = closes
    h = highs or c
    low = lows or c
    o = opens or ([c[0]] + c[:-1])     # open[i] ~= onceki kapanis

    k = min(n, len(c))
    idx = range(len(c) - k, len(c))

    def candle_desc(i: int) -> str:
        op, cl, hi, lo = o[i], c[i], h[i], low[i]
        rng = max(hi - lo, 1e-9)
        body = abs(cl - op)
        up_wick = hi - max(op, cl)
        dn_wick = min(op, cl) - lo
        color = "yeşil" if cl >= op else "kırmızı"
        body_pct = round(body / rng * 100)
        return f"{color} g%{body_pct}"

    descs = [candle_desc(i) for i in idx]
    greens = sum(1 for i in idx if c[i] >= o[i])

    # basit formasyon: son mum
    i = len(c) - 1
    op, cl, hi, lo = o[i], c[i], h[i], low[i]
    rng = max(hi - lo, 1e-9)
    body = abs(cl - op)
    up_wick = hi - max(op, cl)
    dn_wick = min(op, cl) - lo
    pattern = "yok"
    if body / rng < 0.1:
        pattern = "doji (kararsızlık)"
    elif dn_wick > body * 2 and cl >= op:
        pattern = "çekiç/pin (alt fitil uzun, boğa)"
    elif up_wick > body * 2 and cl < op:
        pattern = "ters çekiç/kayan yıldız (üst fitil uzun, ayı)"
    elif len(c) >= 2:
        po, pc = o[i - 1], c[i - 1]
        if cl > op and pc < po and cl >= po and op <= pc:
            pattern = "yutan boğa (bullish engulfing)"
        elif cl < op and pc > po and cl <= po and op >= pc:
            pattern = "yutan ayı (bearish engulfing)"

    net = (c[-1] - c[len(c) - k]) / c[len(c) - k] * 100 if c[len(c) - k] else 0.0
    return (
        f"Son {k} mum (eski→yeni): {', '.join(descs)}\n"
        f"  {greens}/{k} yeşil · pencere değişim %{net:.2f} · son formasyon: {pattern}"
    )


def _build_user_prompt(base: str, quote: str, tech: TechnicalSnapshot,
                       rule_action: str, recent_returns: list[float],
                       news_summary: str = "",
                       candles: dict | None = None) -> str:
    trend = "yukarı" if tech.ema_fast > tech.ema_slow else "aşağı"
    st_dir = "yukarı" if tech.supertrend_dir >= 0 else "aşağı"
    news_line = f"Haber duyarlılığı: {news_summary}\n" if news_summary else ""
    candle_line = ""
    if candles and candles.get("closes"):
        candle_line = "== SON MUMLAR (fiyat-aksiyon) ==\n" + _candle_summary(
            candles.get("closes", []), candles.get("highs"),
            candles.get("lows"), candles.get("opens")) + "\n"
    return (
        f"Parite: {base}/{quote}\n"
        f"Fiyat: {tech.price:.6f}\n"
        f"RSI(14): {tech.rsi:.1f}  StochRSI: {tech.stoch_rsi:.0f}  "
        f"Stoch%K: {tech.stoch_k:.0f}\n"
        f"EMA12: {tech.ema_fast:.6f}  EMA26: {tech.ema_slow:.6f} (trend: {trend})\n"
        f"MACD: {tech.macd:.6f}  Signal: {tech.macd_signal:.6f}\n"
        f"ADX: {tech.adx:.0f} (+DI {tech.plus_di:.0f} / -DI {tech.minus_di:.0f})  "
        f"Supertrend: {st_dir}\n"
        f"Bollinger %B: {tech.bb_pct_b:.0f}  ATR: {tech.atr:.6f}  "
        f"MFI: {tech.mfi:.0f}\n"
        f"WaveTrend: {tech.wavetrend1:.0f}/{tech.wavetrend2:.0f}  "
        f"AO: {tech.awesome:.4f}  Squeeze: {'AÇIK' if tech.squeeze_on else 'kapalı'}\n"
        f"Momentum(10): {tech.momentum:.2f}%\n"
        f"{news_line}"
        f"Son getiriler (%): {[round(r, 2) for r in recent_returns[-8:]]}\n"
        f"{candle_line}"
        f"Kural tabanlı ön karar: {rule_action}\n\n"
        "Teknik tabloyu, SON MUMLARIN yapısını ve haber duyarlılığını birlikte "
        "değerlendir. Mum/fiyat-aksiyon göstergelerle çelişiyorsa belirt. "
        "Nihai kararını JSON olarak ver."
    )


def _parse(text: str) -> dict | None:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return None


def complete(system_prompt: str, user_prompt: str,
             max_tokens: int = 200) -> str | None:
    """Yapılandırılmış LLM çağrısı (sağlayıcı-bağımsız ortak katman).

    .env'deki LLM_PROVIDER + ilgili API key kullanılır. Sağlayıcı yok,
    key boş veya çağrı hatalıysa None döner (fail-safe). Hem sinyal
    danışmanı (advise) hem piyasa analisti (marketdata.analyst) bunu kullanır.
    """
    provider = settings.llm_provider
    try:
        if provider == "deepseek" and settings.deepseek_api_key:
            from openai import OpenAI
            client = OpenAI(api_key=settings.deepseek_api_key,
                            base_url=settings.deepseek_base_url)
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content or ""

        if provider == "anthropic" and settings.anthropic_api_key:
            import anthropic
            # base_url boşsa gerçek Claude; doluysa Anthropic-uyumlu sağlayıcı
            # (örn. DeepSeek: https://api.deepseek.com/anthropic). Aynı SDK,
            # aynı kod -> ileride Claude'a geçiş yalnızca .env değişikliği.
            kwargs = {"api_key": settings.anthropic_api_key}
            if settings.anthropic_base_url:
                kwargs["base_url"] = settings.anthropic_base_url
            client = anthropic.Anthropic(**kwargs)
            msg = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return msg.content[0].text

        if provider == "openai" and settings.openai_api_key:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            resp = client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content or ""
    except Exception as e:
        log.warning("LLM çağrı hatası: %s", e)
        return None

    return None


def advise(base: str, quote: str, tech: TechnicalSnapshot, rule_action: str,
           recent_returns: list[float], news_summary: str = "",
           candles: dict | None = None) -> dict | None:
    """{'action','confidence','rationale'} veya None döner.

    candles: {'closes','highs','lows','opens'} — verilirse AI mum analizi yapar.
    """
    user_prompt = _build_user_prompt(base, quote, tech, rule_action,
                                     recent_returns, news_summary, candles)
    text = complete(SYSTEM_PROMPT, user_prompt, max_tokens=200)
    if text is None:
        log.warning("LLM danışman yanıtı yok, teknik karara düşülüyor")
        return None
    return _parse(text)
