"""Ortak HTTP yardımcıları (yalnızca stdlib, ek bağımlılık yok)."""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

log = logging.getLogger("marketdata.http")

_UA = "ai-trade-bot/0.2 (+public-data)"


class _Redirect308(urllib.request.HTTPRedirectHandler):
    """308 Permanent Redirect desteği (stdlib varsayılanı 308'i izlemez)."""

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, 301, msg, headers)


_opener = urllib.request.build_opener(_Redirect308)

# Basit TTL cache: aynı URL'i sık sık çekip rate-limit yememek için.
_cache: dict[str, tuple[float, Any]] = {}


def get_json(url: str, ttl: float = 10.0, timeout: float = 15.0) -> Any:
    """URL'den JSON çek; ttl saniye boyunca cache'le. Hata -> raise."""
    now = time.time()
    hit = _cache.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with _opener.open(req, timeout=timeout) as r:
        data = json.load(r)
    _cache[url] = (now, data)
    return data


def get_text(url: str, ttl: float = 60.0, timeout: float = 15.0) -> str:
    """URL'den düz metin/XML çek (RSS için); ttl saniye cache."""
    now = time.time()
    key = "TXT:" + url
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with _opener.open(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", errors="replace")
    _cache[key] = (now, text)
    return text
