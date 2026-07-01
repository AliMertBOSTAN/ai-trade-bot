"""AI piyasa analisti — GRAFIK yorumu + kalabalik (haber/internet) al-sat egilimi.

Bir varlik icin: grafik/teknik durumu (chart), CEX/DEX fiyat verisi (aggregator) ve
guncel haber basliklarini (news = internetin son gundemi) toplar; LLM'e verip
GRAFIGI yorumlatir ve haberlerden insanlarin AL mi SAT mi planladigini cikartir;
net bir egilim (AL/SAT/BEKLE) uretir.

LLM yoksa (.env: LLM_PROVIDER + API key) sezgisel fallback: teknik sinyal + haber
sentiment'inden bias uretir (bot asla LLM'e bagimli kalmaz).
"""
from __future__ import annotations

import json
import logging

from engine.marketdata import (aggregator, chart, derivatives, news,
                               onchain, whales)
from engine.models import now_ms
from engine.signals import llm

log = logging.getLogger("marketdata.analyst")

SYSTEM_PROMPT = (
    "Sen deneyimli bir kripto piyasa analistisin. Sana bir varligin GRAFIK/TEKNIK "
    "durumu, CEX/DEX fiyat verisi ve GUNCEL HABER basliklari (internetin/kalabaligin "
    "son gundemi) verilir. Gorevin iki bolumlu: (1) GRAFIGI yorumla (trend, momentum, "
    "asiri alim/satim, donus sinyalleri). (2) Haberlerden kalabaligin AL mi SAT mi "
    "planladigini cikar. Sonra ikisini birlestirip NET bir egilim ver: AL, SAT veya "
    "BEKLE. SADECE su JSON semasinda yanit ver: "
    '{"bias": "AL|SAT|BEKLE", "confidence": 0.0-1.0, '
    '"sentiment": "BULLISH|BEARISH|NEUTRAL", '
    '"chart_view": "grafik/teknik durumun 2-3 cumlelik yorumu", '
    '"crowd_view": "haberlere gore insanlar AL mi SAT mi planliyor (1-2 cumle)", '
    '"summary": "genel sonuc 1-2 cumle", '
    '"risks": ["kisa risk maddeleri"]}. '
    "Veri eksik/celiskili ise BEKLE ver ve confidence dusur. "
    "Bu yatirim tavsiyesi DEGILDIR; veri/grafik yorumudur."
)


def _technical_lines(feed: dict) -> list[str]:
    sig = feed.get("signal") or {}
    markers = feed.get("markers") or []
    out = ["== GRAFIK / TEKNIK (1s) =="]
    if sig:
        out.append(
            f"Kural sinyali: {sig.get('action', '?')} "
            f"(guven %{round(sig.get('confidence', 0) * 100)})")
        if sig.get("rationale"):
            out.append(f"Gostergeler: {sig['rationale']}")
        if sig.get("price"):
            out.append(f"Son fiyat: {sig['price']}")
    if markers:
        last = markers[-3:]
        seq = ", ".join(m.get("action", "?") for m in last)
        out.append(f"Son donus isaretleri: {seq}")
    if len(out) == 1:
        out.append("(grafik verisi yok)")
    return out


def _whale_lines(whale: dict) -> list[str]:
    if not whale:
        return []
    wp = whale.get("pressure") or {}
    out = ["", "== BALINA AKISI (buyuk emirler) =="]
    out.append(
        f"Baski: {whale.get('label', '?')} (skor {wp.get('score', 0):+.2f}) | "
        f"alim {wp.get('buy_usd', 0):,.0f}$ ({wp.get('buy_count', 0)} islem) vs "
        f"satim {wp.get('sell_usd', 0):,.0f}$ ({wp.get('sell_count', 0)} islem)")
    walls = whale.get("walls") or {}
    if walls.get("bids"):
        b = walls["bids"][0]
        out.append(f"En buyuk ALIS duvari: {b['price']:.4f} @ {b['usd']:,.0f}$ (destek)")
    if walls.get("asks"):
        a = walls["asks"][0]
        out.append(f"En buyuk SATIS duvari: {a['price']:.4f} @ {a['usd']:,.0f}$ (direnc)")
    return out


def _deriv_lines(deriv: dict) -> list[str]:
    if not deriv or not deriv.get("ok"):
        return []
    sq = deriv.get("squeeze") or {}
    out = ["", "== TUREV / LIKIDASYON (vadeli) =="]
    out.append(
        f"Funding {deriv.get('funding_pct', 0):+.4f}% | OI degisim "
        f"{deriv.get('oi_change_pct', 0):+.2f}% | L/S oran {deriv.get('ls_ratio', 0)}")
    out.append(f"Squeeze yonu: {sq.get('direction', 'notr')} (skor {sq.get('score', 0):+.2f})"
               + (" | LIKIDASYON KASKADI" if sq.get("cascade") else ""))
    for n in (sq.get("notes") or [])[:3]:
        out.append(f"  - {n}")
    return out


def _build_prompt(symbol: str, snap: dict, feed: dict, headlines: list[dict],
                  whale: dict | None = None, deriv: dict | None = None) -> str:
    lines = [f"VARLIK: {symbol.upper()}", ""]
    lines += _technical_lines(feed)
    lines += _whale_lines(whale or {})
    lines += _deriv_lines(deriv or {})

    lines += ["", "== PIYASA VERISI =="]
    if snap.get("cex"):
        c = snap["cex"]
        ob = c.get("order_book") or {}
        lines.append(
            f"Binance: {c['price']:.4f} USD | 24s {c['change_pct_24h']:+.2f}% | "
            f"hacim {c['volume_quote_24h']:,.0f} USD | "
            f"defter dengesizligi {ob.get('imbalance', 0):+.2f}")
    if snap.get("dex"):
        d = snap["dex"]
        lines.append(
            f"DEX ({d['dex']}@{d['chain']}): {d['price_usd']:.4f} USD | "
            f"likidite {d['liquidity_usd']:,.0f} USD")
    if snap.get("comparison"):
        lines.append(f"CEX/DEX spread: {snap['comparison']['spread_bps']:+.1f} bps")

    lines += ["", "== GUNCEL HABERLER (internetin son gundemi) =="]
    if headlines:
        for h in headlines[:12]:
            lines.append(f"- [{h['source']}] {h['title']}")
    else:
        lines.append("(haber akisina ulasilamadi)")

    lines += ["", "Grafigi yorumla, kalabaligin al/sat egilimini cikar, JSON ver."]
    return "\n".join(lines)


def _parse(text: str) -> dict | None:
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception:
        return None


def _heuristic(feed: dict, sent: dict, whale: dict | None = None,
               deriv: dict | None = None) -> dict:
    """LLM yokken: teknik sinyal + haber sentiment + balina baskisindan bias uret."""
    sig = feed.get("signal") or {}
    action = sig.get("action", "HOLD")
    bias = {"BUY": "AL", "SELL": "SAT", "HOLD": "BEKLE"}.get(action, "BEKLE")
    label = sent.get("label", "notr")
    score = float(sent.get("score", 0.0))
    wp = (whale or {}).get("pressure") or {}
    wscore = float(wp.get("score", 0.0))
    whale_txt = ((whale or {}).get("label", "balina verisi yok")
                 + f" (skor {wscore:+.2f})") if whale else "balina verisi yok"
    sq = (deriv or {}).get("squeeze") or {}
    deriv_txt = (f" Vadeli: {sq.get('direction', 'notr')} (funding "
                 f"{(deriv or {}).get('funding_pct', 0):+.3f}%)." if deriv and deriv.get("ok") else "")
    crowd = (f"Haber tonu '{label}' ({score:+.2f}); balina: {whale_txt}. "
             + ("Buyuk emirler ALIM tarafinda." if wscore > 0.15
                else "Buyuk emirler SATIM tarafinda." if wscore < -0.15
                else "Balinada net yon yok.") + deriv_txt)
    return {
        "bias": bias,
        "confidence": round(float(sig.get("confidence", 0.5)), 2),
        "sentiment": "BULLISH" if action == "BUY" else "BEARISH" if action == "SELL" else "NEUTRAL",
        "chart_view": sig.get("rationale", "grafik verisi sinirli"),
        "crowd_view": crowd,
        "summary": f"Teknik {action}, haber tonu {label} -> egilim: {bias}.",
        "risks": ["Sezgisel ozet (LLM kapali); dogrulama icin grafigi inceleyin."],
        "heuristic": True,
    }


def analyze(symbol: str, news_query: str | None = None) -> dict:
    """Tam analiz: grafik + CEX/DEX + haberler + (LLM veya sezgisel) al/sat egilimi."""
    snap = aggregator.snapshot(symbol)
    try:
        feed = chart.chart_feed(symbol, "1h", 200)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst chart hatasi %s: %s", symbol, e)
        feed = {"signal": None, "markers": []}
    headlines = news.fetch_headlines(limit=15, query=news_query or symbol)
    try:
        whale = whales.summary(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst whale hatasi %s: %s", symbol, e)
        whale = {}
    try:
        deriv = derivatives.summary(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst deriv hatasi %s: %s", symbol, e)
        deriv = {}
    try:
        flow = onchain.netflow_signal(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst onchain hatasi %s: %s", symbol, e)
        flow = {"enabled": False}

    report = {
        "symbol": symbol.upper(),
        "ts": now_ms(),
        "market": snap,
        "technical": feed.get("signal"),
        "whales": whale,
        "derivatives": deriv,
        "onchain": flow,
        "headlines": headlines[:10],
        "llm": None,
        "llm_used": False,
    }

    text = llm.complete(SYSTEM_PROMPT, _build_prompt(symbol, snap, feed, headlines, whale, deriv),
                        max_tokens=600)
    if text:
        parsed = _parse(text)
        if parsed:
            report["llm"] = parsed
            report["llm_used"] = True
        else:
            report["llm"] = {"raw": text}
    else:
        # LLM yok -> sezgisel bias (teknik + haber sentiment)
        try:
            sent = news.sentiment(symbol)
        except Exception:
            sent = {"label": "notr", "score": 0.0}
        report["llm"] = _heuristic(feed, sent, whale, deriv)
    return report
