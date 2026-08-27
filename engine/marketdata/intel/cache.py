"""Intel katmanı için TTL cache + "hata olursa bayat veriyi kullan" sarmalayıcı.

Panel verilerinin çoğu dakikalar mertebesinde değişir; her istekte upstream'e
gitmek hem yavaş hem rate-limit riski. Burada iki şey yapılır:

  1. `cached(key, ttl, fn)` — taze veri varsa onu döner, yoksa fn()'i çağırır.
  2. fn() PATLARSA en son BAŞARILI sonuç (bayat da olsa) `stale=True` ile döner.
     Böylece tek bir upstream kesintisi paneli boşaltmaz (fail-safe).

Disk kalıcılığı: DATA_DIR/intel_cache.json. Uygulama yeniden başladığında
paneller boş açılmasın diye son snapshot'lar geri yüklenir.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

log = logging.getLogger("intel.cache")

_LOCK = threading.RLock()
_MEM: dict[str, dict[str, Any]] = {}
_DIRTY = False
_LAST_FLUSH = 0.0
_FLUSH_EVERY_S = 30.0


def _path() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "data"), "intel_cache.json")


def load_disk() -> None:
    """Diskteki son snapshot'ları belleğe al (uygulama açılışında bir kez)."""
    p = _path()
    if not os.path.exists(p):
        return
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            with _LOCK:
                for k, v in raw.items():
                    if isinstance(v, dict) and "ts" in v and "value" in v:
                        _MEM[k] = v
        log.info("intel cache diskten yüklendi: %d anahtar", len(_MEM))
    except Exception as e:  # noqa: BLE001
        log.warning("intel cache okunamadı: %s", e)


def flush_disk(force: bool = False) -> None:
    """Belleği diske yaz (en fazla _FLUSH_EVERY_S'de bir, force ile hemen)."""
    global _DIRTY, _LAST_FLUSH
    with _LOCK:
        if not _DIRTY:
            return
        if not force and (time.time() - _LAST_FLUSH) < _FLUSH_EVERY_S:
            return
        snap = dict(_MEM)
        _DIRTY = False
        _LAST_FLUSH = time.time()
    p = _path()
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        log.warning("intel cache yazılamadı: %s", e)


def peek(key: str) -> tuple[Any, float] | None:
    """Cache'teki değeri (taze olsun olmasın) ve yaşını döner. Yoksa None."""
    with _LOCK:
        hit = _MEM.get(key)
    if not hit:
        return None
    return hit["value"], time.time() - float(hit["ts"])


def put(key: str, value: Any) -> None:
    global _DIRTY
    with _LOCK:
        _MEM[key] = {"ts": time.time(), "value": value}
        _DIRTY = True
    flush_disk()


def cached(key: str, ttl: float, fn: Callable[[], Any]) -> Any:
    """TTL cache + bayat-yedek. Dönen değer daima `fn`'in şekliyle aynıdır."""
    hit = peek(key)
    if hit is not None and hit[1] < ttl:
        return hit[0]
    try:
        val = fn()
    except Exception as e:  # noqa: BLE001
        if hit is not None:
            log.warning("%s tazelenemedi (%s) — %.0fs bayat veri kullanılıyor",
                        key, e, hit[1])
            return hit[0]
        raise
    put(key, val)
    return val


def age(key: str) -> float | None:
    """Anahtarın yaşı (saniye) — UI'da "x dk önce" göstermek için."""
    hit = peek(key)
    return None if hit is None else hit[1]


def clear() -> None:
    """Testler için: belleği boşalt."""
    global _DIRTY
    with _LOCK:
        _MEM.clear()
        _DIRTY = False
