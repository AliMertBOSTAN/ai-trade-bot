"""LLM piyasa analisti.

CEX/DEX karşılaştırmalı veriyi (aggregator) ve anlık haber başlıklarını
(news) LLM'e verip yapılandırılmış bir piyasa yorumu ister:
sentiment + özet + CEX/DEX uyumsuzluk yorumu + riskler + haber etkisi.

API key .env'den gelir (LLM_PROVIDER + ANTHROPIC_API_KEY / OPENAI_API_KEY).
Key yoksa LLM'siz, yalnızca sayısal karşılaştırma içeren bir rapor döner
(fail-safe; bot asla haber/LLM'e bağımlı kalmaz).
"""
from __future__ import annotations

import json
import logging

from engine.marketdata import aggregator, news
from engine.models import now_ms
from engine.signals import llm

log = logging.getLogger("marketdata.analyst")

SYSTEM_PROMPT = (
    "Sen temkinli bir kripto piyasa analistisın. Sana bir varlığın CEX "
    "(Binance) ve DEX (Uniswap vb.) açık piyasa verileri ile güncel haber "
    "başlıkları verilir. Görevin: kaynakları KARŞILAŞTIRIP yorumlamak. "
    "SADECE şu JSON şemasında yanıt ver: "
    '{"sentiment": "BULLISH|BEARISH|NEUTRAL", "confidence": 0.0-1.0, '
    '"summary": "2-3 cümle genel yorum", '
    '"cex_dex_view": "fiyat/likidite uyumu veya uyumsuzluğu hakkında 1 cümle", '
    '"news_impact": "haberlerin olası fiyat etkisi hakkında 1-2 cümle", '
    '"risks": ["kısa risk maddeleri"]}. '
    "Veri eksikse veya çelişkiliyse NEUTRAL ver ve confidence düşür. "
    "Yatırım tavsiyesi değil, veri yorumu üret."
)


def _build_prompt(snap: dict, headlines: list[dict]) -> str:
    lines = [f"VARLIK: {snap['symbol']}", "", "== PİYASA VERİSİ =="]
    if snap.get("cex"):
        c = snap["cex"]
        ob = c.get("order_book") or {}
        lines.append(
            f"Binance: {c['price']:.4f} USD | 24s {c['change_pct_24h']:+.2f}% | "
            f"hacim {c['volume_quote_24h']:,.0f} USD | "
            f"spread {ob.get('spread_bps', 0):.1f}bps | "
            f"defter dengesizliği {ob.get('imbalance', 0):+.2f}")
    if snap.get("dex"):
        d = snap["dex"]
        lines.append(
            f"DEX ({d['dex']}@{d['chain']}): {d['price_usd']:.4f} USD | "
            f"24s {d['change_pct_24h']:+.2f}% | likidite {d['liquidity_usd']:,.0f} USD | "
            f"24s hacim {d['volume_24h_usd']:,.0f} USD")
    if snap.get("comparison"):
        cmp_ = snap["comparison"]
        lines.append(f"CEX/DEX spread: {cmp_['spread_bps']:+.1f} bps ({cmp_['note']})")
    if snap.get("errors"):
        lines.append(f"Veri uyarıları: {snap['errors']}")

    lines += ["", "== GÜNCEL HABERLER =="]
    if headlines:
        for h in headlines[:12]:
            lines.append(f"- [{h['source']}] {h['title']}")
    else:
        lines.append("(haber akışına ulaşılamadı)")

    lines += ["", "Karşılaştırmalı yorumunu JSON olarak ver."]
    return "\n".join(lines)


def _parse(text: str) -> dict | None:
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception:
        return None


def analyze(symbol: str, news_query: str | None = None) -> dict:
    """Tam analiz raporu: ham veri + haberler + (varsa) LLM yorumu."""
    snap = aggregator.snapshot(symbol)
    headlines = news.fetch_headlines(limit=15, query=news_query)

    report = {
        "symbol": symbol.upper(),
        "ts": now_ms(),
        "market": snap,
        "headlines": headlines[:10],
        "llm": None,
        "llm_used": False,
    }

    text = llm.complete(SYSTEM_PROMPT, _build_prompt(snap, headlines),
                        max_tokens=500)
    if text:
        parsed = _parse(text)
        if parsed:
            report["llm"] = parsed
            report["llm_used"] = True
        else:
            report["llm"] = {"raw": text}
    else:
        report["llm"] = {
            "note": "LLM yapılandırılmamış (.env: LLM_PROVIDER + API key). "
                    "Yalnızca sayısal karşılaştırma döndü."
        }
    return report
