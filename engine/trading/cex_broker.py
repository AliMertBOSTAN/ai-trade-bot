"""CEX (Binance spot) broker — GELECEK İÇİN HAZIR, ŞU AN PASİF.

Durum: Bu modül henüz Executor'a BAĞLI DEĞİL; orchestrator tüm işlemleri
zincir-üstü DEX'te (PaperBroker / LiveBroker) yapıyor. CEX trading'i devreye
almak için iki şey gerekir:
  1) .env'de BINANCE_API_KEY + BINANCE_SECRET (trade izinli),
  2) Executor'a venue yönlendirmesi (sinyal/sembol -> 'dex' | 'cex').

Bu broker, LiveBroker ile aynı arayüzü (execute(order) -> order) taşır; böylece
gelecekte tek satırla devreye alınabilir. Binance spot REST'ine HMAC-SHA256
imzalı emir gönderir. Gas YOKTUR (CEX); yalnızca taker komisyonu (~%0.1) işlenir.

GÜVENLİK: Gerçek para. Anahtar yoksa örneklenemez (fail-safe). Önce küçük tutar
veya testnet (BINANCE_BASE=https://testnet.binance.vision) ile denenmelidir.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request

from engine.config.settings import RiskConfig, settings
from engine.models import TradeOrder
from engine.trading.portfolio import Portfolio

log = logging.getLogger("broker.cex")

# Bizim quote sembollerini Binance karşılığına çevir (USD ~ USDT).
_QUOTE_MAP = {"USD": "USDT", "USDC": "USDC", "USDT": "USDT"}
TAKER_FEE_PCT = 0.001  # Binance spot taker ~%0.1


class CexBroker:
    """Binance spot broker (HMAC imzalı). Şu an Executor'a bağlı değildir."""

    mode = "live"
    venue_type = "cex"

    def __init__(self, portfolio: Portfolio, risk: RiskConfig):
        self.portfolio = portfolio
        self.risk = risk
        self.base_url = os.getenv("BINANCE_BASE", "https://api.binance.com")
        if not settings.binance_api_key or not settings.binance_secret:
            raise RuntimeError(
                "CEX (Binance) için BINANCE_API_KEY + BINANCE_SECRET gerekli. "
                "Güvenli değilse paper modda kalın.")
        self.api_key = settings.binance_api_key
        self.secret = settings.binance_secret.encode()
        log.info("CexBroker hazır (Binance spot)")

    # ---- imzalı istek ----
    def _signed(self, path: str, params: dict, method: str = "POST") -> dict:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.secret, query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base_url}{path}?{query}&signature={sig}"
        req = urllib.request.Request(
            url, method=method, headers={"X-MBX-APIKEY": self.api_key})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)

    def _symbol(self, base: str, quote: str) -> str:
        return f"{base.upper()}{_QUOTE_MAP.get(quote.upper(), 'USDT')}"

    # ---- ana giriş (LiveBroker ile aynı imza) ----
    def execute(self, order: TradeOrder) -> TradeOrder:
        order.venue_type = "cex"
        symbol = self._symbol(order.base, order.quote)
        try:
            params: dict = {"symbol": symbol, "side": order.side, "type": "MARKET"}
            if order.side == "BUY":
                # MARKET BUY: harcanacak USDT (quoteOrderQty)
                params["quoteOrderQty"] = round(order.amount * order.price, 2)
            else:
                params["quantity"] = order.amount
            resp = self._signed("/api/v3/order", params)

            fills = resp.get("fills") or []
            qty = float(resp.get("executedQty") or order.amount) or order.amount
            quote_qty = float(resp.get("cummulativeQuoteQty") or 0)
            order.filled_price = (quote_qty / qty) if qty else order.price
            # komisyon (varsa fill'lerden, yoksa taker tahmini); CEX'te gas yok
            commission = sum(float(f.get("commission") or 0) for f in fills)
            order.fee_usd = commission or (quote_qty * TAKER_FEE_PCT)
            order.status = "filled" if resp.get("status") == "FILLED" else "pending"
            order.tx_hash = str(resp.get("orderId", ""))
            self.portfolio.apply_fill(order)
        except Exception as e:
            order.status = "failed"
            order.reason = (order.reason + " | " if order.reason else "") + f"CEX hata: {e}"
            log.error("CEX emir başarısız: %s", e)
        return order
