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
from email.utils import parsedate_to_datetime

from engine.config.settings import settings
from engine.marketdata.http import get_text

log = logging.getLogger("marketdata.news")

DEFAULT_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://thedefiant.io/api/feed",
]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _parse_feed(xml_text: str, source: str) -> list[dict]:
    """RSS 2.0 ve Atom'u tolere ederek başlıkları çıkar."""
    items: list[dict] = []
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for item in root.iter("item"):  # RSS 2.0
        ts = 0
        pub = item.findtext("pubDate")
        if pub:
            try:
                ts = int(parsedate_to_datetime(pub).timestamp() * 1000)
            except Exception:
                pass
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
