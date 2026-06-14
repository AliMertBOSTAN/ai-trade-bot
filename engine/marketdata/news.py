"""Anlık kripto haber okuyucu (RSS, key gerekmez).

Varsayılan akışlar CoinDesk/Cointelegraph/Decrypt/The Defiant; .env'deki
NEWS_FEEDS ile (virgülle ayrılmış URL listesi) özelleştirilebilir.
Yalnızca stdlib xml.etree kullanır; bir akış düşerse diğerleriyle devam
eder (fail-safe). LLM analistinin haber bağlamı buradan gelir.
"""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from engine.config.settings import settings
from engine.marketdata.http import get_text

log = logging.getLogger("marketdata.news")

DEFAULT_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://thedefiant.io/api/feed",
    "https://tr.investing.com/rss/news.rss",   # Investing.com TR (genel haber)
    "https://ninjanews.io/feed/",              # Ninja News (TR kripto, WordPress RSS)
]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _parse_date(pub: str | None) -> int:
    """RSS pubDate -> epoch ms. RFC822'yi ve Investing.com'un
    'YYYY-MM-DD HH:MM:SS' biçimini tolere eder; başarısızsa 0 döner."""
    if not pub:
        return 0
    pub = pub.strip()
    # 1) Standart RFC822 (CoinDesk, Cointelegraph, WordPress vb.)
    try:
        return int(parsedate_to_datetime(pub).timestamp() * 1000)
    except Exception:
        pass
    # 2) Investing.com biçimi: '2026-04-04 16:01:58' (+ opsiyonel tz)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return int(datetime.strptime(pub, fmt).timestamp() * 1000)
        except Exception:
            continue
    return 0


def _parse_feed(xml_text: str, source: str) -> list[dict]:
    """RSS 2.0 ve Atom'u tolere ederek başlıkları çıkar."""
    items: list[dict] = []
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for item in root.iter("item"):  # RSS 2.0
        ts = _parse_date(item.findtext("pubDate"))
        items.append({
            "source": source,
            "title": _clean(item.findtext("title")),
            "summary": _clean(item.findtext("description"))[:300],
            "link": (item.findtext("link") or "").strip(),
            "ts": ts,
        })

    if not items:  # Atom
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            link_el = entry.find("atom:link", ns)
            items.append({
                "source": source,
                "title": _clean(entry.findtext("atom:title", default="", namespaces=ns)),
                "summary": _clean(entry.findtext("atom:summary", default="", namespaces=ns))[:300],
                "link": link_el.get("href") if link_el is not None else "",
                "ts": 0,
            })
    return items


# Anahtar-kelime sentiment sözlüğü (EN + TR). LLM'siz, hızlı, açıklanabilir.
_BULLISH = {
    "surge", "rally", "soar", "soars", "gain", "gains", "jump", "jumps", "bullish",
    "breakout", "adopt", "adoption", "partnership", "upgrade", "approve", "approval",
    "inflow", "inflows", "record", "high", "pump", "boom", "rise", "rises", "up",
    "yükseliş", "yükseldi", "artış", "arttı", "rekor", "ralli", "onay", "onaylandı",
    "kazanç", "sıçradı", "pozitif", "boğa", "yatırım", "ortaklık", "rekortmen",
}
_BEARISH = {
    "crash", "plunge", "plunges", "drop", "drops", "fall", "falls", "dump", "dumps",
    "bearish", "hack", "hacked", "exploit", "lawsuit", "ban", "banned", "selloff",
    "sell-off", "outflow", "outflows", "fear", "decline", "slump", "down", "low",
    "düşüş", "düştü", "çöküş", "çakıldı", "hack", "dava", "yasak", "kayıp",
    "negatif", "ayı", "satış baskısı", "iflas", "dolandırıcılık", "tehlike",
}

_WORD_RE = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]+", re.UNICODE)


def _score_text(text: str) -> tuple[int, int]:
    """Metindeki boğa/ayı kelime sayısı."""
    words = {w.lower() for w in _WORD_RE.findall(text)}
    low = text.lower()
    bull = sum(1 for w in _BULLISH if (" " in w and w in low) or w in words)
    bear = sum(1 for w in _BEARISH if (" " in w and w in low) or w in words)
    return bull, bear


def sentiment(symbol: str, limit: int = 40) -> dict:
    """Bir token için haber sentiment'i (anahtar-kelime, LLM'siz).

    Önce sembolü içeren başlıklara bakar; yeterli değilse piyasa geneline
    düşer. Dönüş camelCase (renderer ile hizalı):
      {score: -1..1, label, count, matched, market, headlines: [...]}
    """
    headlines = fetch_headlines(limit=limit)
    sym = symbol.upper().lstrip("W")  # WETH -> ETH, WBTC -> BTC vb.
    token = [h for h in headlines
             if sym.lower() in h["title"].lower() or sym.lower() in h["summary"].lower()]
    used, market = (token, False) if len(token) >= 3 else (headlines, True)

    bull = bear = 0
    for h in used:
        b, r = _score_text(f"{h['title']} {h['summary']}")
        bull += b
        bear += r
    total = bull + bear
    score = (bull - bear) / total if total else 0.0
    if score > 0.15:
        label = "pozitif"
    elif score < -0.15:
        label = "negatif"
    else:
        label = "nötr"

    return {
        "score": round(score, 3),
        "label": label,
        "count": len(used),
        "matched": len(token),
        "market": market,  # True: piyasa geneli (token'a özel başlık az)
        "headlines": [h["title"] for h in used[:3]],
    }


def fetch_headlines(limit: int = 30, query: str | None = None) -> list[dict]:
    """Tüm akışlardan güncel başlıklar; en yeniden eskiye sıralı.

    query verilirse başlık/özet içinde (büyük/küçük harf duyarsız) filtreler.
    """
    feeds = settings.news_feeds or DEFAULT_FEEDS
    items: list[dict] = []
    for url in feeds:
        try:
            source = url.split("/")[2].replace("www.", "")
            items.extend(_parse_feed(get_text(url, ttl=120), source))
        except Exception as e:
            log.warning("Haber akışı okunamadı (%s): %s", url, e)

    if query:
        q = query.lower()
        items = [i for i in items
                 if q in i["title"].lower() or q in i["summary"].lower()]

    items.sort(key=lambda i: i["ts"], reverse=True)
    return items[:limit]
