"""Intel panellerini arka planda tazeleyen hafif zamanlayıcı.

Neden gerekli: sinyal motoru ve risk kapıları ASLA ağ beklemez — yalnızca
cache okur. O cache'i dolduran yer burasıdır. Ayrıca UI ilk açılışta dolu
gelir, tek tek panel beklemez.

Kapatmak için: .env → INTEL_REFRESH=0
Aralık:        .env → INTEL_REFRESH_S (varsayılan 180 sn)

Tazeleme, her panelin kendi TTL'ine saygı duyar (cached() zaten TTL kontrolü
yapar); bu döngü sadece "birinin düzenli olarak dokunması"nı sağlar.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

log = logging.getLogger("intel.refresher")


class IntelRefresher:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._emit: Callable[[dict], None] | None = None
        self.last_run: float = 0.0
        self.last_error: str | None = None
        self.runs: int = 0

    # -------------------------------------------------------------- kontrol
    @staticmethod
    def enabled() -> bool:
        return os.getenv("INTEL_REFRESH", "1").strip().lower() not in ("0", "false", "no")

    @staticmethod
    def interval_s() -> float:
        try:
            return max(60.0, float(os.getenv("INTEL_REFRESH_S", "180")))
        except ValueError:
            return 180.0

    def start(self, emit: Callable[[dict], None] | None = None) -> bool:
        if not self.enabled():
            log.info("intel tazeleyici kapalı (INTEL_REFRESH=0)")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._emit = emit
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="intel-refresh",
                                        daemon=True)
        self._thread.start()
        log.info("intel tazeleyici başladı (%.0f sn)", self.interval_s())
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        return {"enabled": self.enabled(),
                "running": bool(self._thread and self._thread.is_alive()),
                "interval_s": self.interval_s(), "runs": self.runs,
                "last_run": self.last_run, "last_error": self.last_error}

    # ---------------------------------------------------------------- döngü
    def _loop(self) -> None:
        from engine.marketdata.intel import cache, snapshot
        cache.load_disk()
        # İlk turu hemen çalıştır (UI boş açılmasın), sonra periyodik.
        while not self._stop.is_set():
            t0 = time.time()
            try:
                snap = snapshot()
                self.runs += 1
                self.last_run = time.time()
                self.last_error = None
                ok = sum(1 for v in snap.values() if isinstance(v, dict)
                         and (v.get("ok") or v.get("sentiment")))
                log.info("intel tazelendi: %d/%d panel, %.1f sn",
                         ok, len(snap), time.time() - t0)
                if self._emit:
                    try:
                        self._emit({"type": "intel", "ok": ok, "total": len(snap),
                                    "t": int(self.last_run * 1000)})
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)[:200]
                log.warning("intel tazeleme hatası: %s", e)
            self._stop.wait(self.interval_s())


refresher = IntelRefresher()
