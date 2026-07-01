"""Günlük harcama limiti kapısı (live işlemler için ek koruma).

Günlük zarar kill-switch'ten BAĞIMSIZDIR: bu, gün içinde live olarak işleme
sokulan toplam NOSYONEL hacmi sınırlar (yanlış sinyal patlamasında sermayenin
tümünün dönmesini engeller). Eşik aşılırsa yeni live işlemler reddedilir.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("security.spending")


class SpendingLimiter:
    def __init__(self, daily_limit_usd: float):
        self.daily_limit_usd = max(0.0, daily_limit_usd)
        self._spent = 0.0
        self._day = self._today()

    @staticmethod
    def _today() -> int:
        return int(time.time() // 86400)

    def _roll(self) -> None:
        d = self._today()
        if d != self._day:
            self._day = d
            self._spent = 0.0

    def remaining(self) -> float:
        self._roll()
        if self.daily_limit_usd <= 0:
            return float("inf")
        return max(0.0, self.daily_limit_usd - self._spent)

    def allowed(self, notional_usd: float) -> bool:
        """Bu büyüklükte bir işlem limite sığar mı?"""
        self._roll()
        if self.daily_limit_usd <= 0:  # 0 = limitsiz
            return True
        return self._spent + max(0.0, notional_usd) <= self.daily_limit_usd

    def record(self, notional_usd: float) -> None:
        self._roll()
        self._spent += max(0.0, notional_usd)

    def spent_today(self) -> float:
        self._roll()
        return self._spent

    def reset_daily(self) -> None:
        self._spent = 0.0
        self._day = self._today()
