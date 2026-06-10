"""Mod switch: paper <-> live broker seçimi tek noktadan.

Bot çalışırken mod değiştirilebilir; live'a geçişte ön koşullar doğrulanır.
"""
from __future__ import annotations

import logging

from engine.config.settings import RiskConfig, settings
from engine.trading.paper_broker import PaperBroker
from engine.trading.portfolio import Portfolio

log = logging.getLogger("executor")


class Executor:
    def __init__(self, portfolio: Portfolio, risk: RiskConfig, mode: str = "paper"):
        self.portfolio = portfolio
        self.risk = risk
        self._mode = "paper"
        self._paper = PaperBroker(portfolio, risk)
        self._live = None
        self.set_mode(mode)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> str:
        if mode == "live":
            settings.assert_live_ready()  # secret/önkoşul doğrula (fail-safe)
            if self._live is None:
                from engine.trading.live_broker import LiveBroker
                self._live = LiveBroker(self.portfolio, self.risk)
            self._mode = "live"
            log.warning("MOD: LIVE - gerçek işlemler aktif")
        else:
            self._mode = "paper"
            log.info("MOD: PAPER - simülasyon")
        return self._mode

    @property
    def broker(self):
        return self._live if self._mode == "live" else self._paper

    def execute(self, order):
        order.mode = self._mode
        return self.broker.execute(order)
