"""Ortak HTTP yardımcıları (yalnızca stdlib, ek bağımlılık yok)."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
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

# Geçici (retry edilebilir) HTTP durum kodları
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5  # saniye; 0.5, 1.0, 2.0 ... (üstel)


def _is_retryable(err: Exception) -> bool:
    """Hata geçici mi? (ağ kesintisi, timeout, 5xx/429 -> evet; 404/400 -> hayir)"""
    if isinstance(err, urllib.error.HTTPError):
        return err.code in _RETRYABLE_STATUS
    return isinstance(err, (urllib.error.URLError, TimeoutError, OSError))


def _fetch(url: str, timeout: float,
           headers: dict[str, str] | None = None,
           data: bytes | None = None) -> bytes:
    """Ustel backoff ile retry'li ham getirme. Kalici hatada son hatayi raise eder.

    headers: ek istek basliklari (API anahtari vb.). data verilirse POST olur.
    """
    hdrs = {"User-Agent": _UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, data=data,
                                 method="POST" if data is not None else "GET")
    last: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with _opener.open(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_retryable(e) or attempt == _MAX_RETRIES - 1:
                break
            delay = _BACKOFF_BASE * (2 ** attempt)
            log.warning("fetch %s basarisiz (deneme %d/%d): %s - %.1fs sonra yeniden",
                        url, attempt + 1, _MAX_RETRIES, e, delay)
            time.sleep(delay)
    assert last is not None
    raise last


def get_json(url: str, ttl: float = 10.0, timeout: float = 15.0,
             headers: dict[str, str] | None = None) -> Any:
    """URL'den JSON cek; ttl saniye cache'le; gecici hatada retry. Kalici hata -> raise.

    headers verilirse cache anahtari basliklara gore ayrisir (farkli API
    anahtariyla ayni URL'in yaniti karismasin diye).
    """
    now = time.time()
    key = url if not headers else url + "|" + repr(sorted(headers.items()))
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    data = json.loads(_fetch(url, timeout, headers=headers))
    _cache[key] = (now, data)
    return data


def post_json(url: str, payload: Any, ttl: float = 10.0, timeout: float = 15.0,
              headers: dict[str, str] | None = None) -> Any:
    """JSON POST (Hyperliquid /info gibi uclar icin); ttl saniye cache'li."""
    body = json.dumps(payload).encode("utf-8")
    now = time.time()
    key = "POST:" + url + "|" + json.dumps(payload, sort_keys=True)
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    data = json.loads(_fetch(url, timeout, headers=hdrs, data=body))
    _cache[key] = (now, data)
    return data


def get_text(url: str, ttl: float = 60.0, timeout: float = 15.0,
             headers: dict[str, str] | None = None) -> str:
    """URL'den duz metin/XML cek (RSS icin); ttl saniye cache; gecici hatada retry."""
    now = time.time()
    key = "TXT:" + url
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    text = _fetch(url, timeout, headers=headers).decode("utf-8", errors="replace")
    _cache[key] = (now, text)
    return text
