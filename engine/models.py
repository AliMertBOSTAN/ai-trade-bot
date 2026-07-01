"""Cekirdek veri modelleri (TS shared/types.ts ile hizali)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal

SignalAction = Literal["BUY", "SELL", "HOLD"]
TradeSide = Literal["BUY", "SELL"]
TradeMode = Literal["paper", "live"]
TradeStatus = Literal["pending", "filled", "failed", "rejected"]


def _id() -> str:
    return uuid.uuid4().hex[:12]


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class PriceQuote:
    chain_id: int
    dex: str
    base: str
    quote: str
    price: float
    liquidity_usd: float
    timestamp: int = field(default_factory=now_ms)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArbitrageOpportunity:
    base: str
    quote: str
    buy_chain: int
    buy_dex: str
    buy_price: float
    sell_chain: int
    sell_dex: str
    sell_price: float
    spread_pct: float
    est_net_profit_usd: float
    notional_usd: float
    id: str = field(default_factory=_id)
    timestamp: int = field(default_factory=now_ms)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TechnicalSnapshot:
    rsi: float
    ema_fast: float
    ema_slow: float
    macd: float
    macd_signal: float
    momentum: float
    price: float
    sma_20: float = 0.0
    roc: float = 0.0
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    stoch_rsi: float = 50.0
    cci: float = 0.0
    williams_r: float = -50.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_mid: float = 0.0
    bb_pct_b: float = 50.0
    bb_bandwidth: float = 0.0
    atr: float = 0.0
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    obv: float = 0.0
    vwap: float = 0.0
    mfi: float = 50.0
    supertrend: float = 0.0
    supertrend_dir: float = 0.0
    ichimoku_tenkan: float = 0.0
    ichimoku_kijun: float = 0.0
    ichimoku_senkou_a: float = 0.0
    ichimoku_senkou_b: float = 0.0
    psar: float = 0.0
    psar_dir: float = 0.0
    keltner_upper: float = 0.0
    keltner_lower: float = 0.0
    donchian_upper: float = 0.0
    donchian_lower: float = 0.0
    awesome: float = 0.0
    squeeze_on: float = 0.0
    squeeze_momentum: float = 0.0
    wavetrend1: float = 0.0
    wavetrend2: float = 0.0
    ma_cross_dir: float = 0.0   # SMA cross: +1 long / -1 short / 0
    rsi_div: float = 0.0        # RSI uyumsuzluk: +1 boga / -1 ayi / 0
    smc_trend: float = 0.0      # SMC swing yapi (BOS/CHoCH): +1 / -1 / 0
    fvg_bias: float = 0.0       # Fair Value Gap yonu: +1 boga / -1 ayi / 0
    swing_trend: float = 0.0    # Dow yapisi (HH+HL / LH+LL): +1 yukselis / -1 dusus / 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradeSignal:
    chain_id: int
    base: str
    quote: str
    action: SignalAction
    confidence: float
    technical: TechnicalSnapshot
    rationale: str
    source: str  # technical|llm|hybrid
    breakdown: dict | None = None
    id: str = field(default_factory=_id)
    timestamp: int = field(default_factory=now_ms)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradeOrder:
    mode: TradeMode
    chain_id: int
    dex: str
    base: str
    quote: str
    side: TradeSide
    amount: float
    price: float
    status: TradeStatus = "pending"
    tx_hash: str = ""
    filled_price: float = 0.0
    fee_usd: float = 0.0
    reason: str = ""
    signal_id: str = ""
    venue_type: str = "dex"
    # Islem nonce'u: live'da gercek zincir nonce'u; paper'da sirali simule sayac.
    # -1 = atanmadi.
    nonce: int = -1
    id: str = field(default_factory=_id)
    timestamp: int = field(default_factory=now_ms)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_api(self) -> dict:
        """Renderer ile hizali camelCase temsil (TS TradeOrder)."""
        return {
            "id": self.id, "mode": self.mode, "chainId": self.chain_id,
            "dex": self.dex, "base": self.base, "quote": self.quote,
            "side": self.side, "amount": self.amount, "price": self.price,
            "status": self.status, "txHash": self.tx_hash,
            "filledPrice": self.filled_price, "feeUsd": self.fee_usd,
            "reason": self.reason, "signalId": self.signal_id,
            "venueType": self.venue_type,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
        }


@dataclass
class Position:
    chain_id: int
    base: str
    quote: str
    amount: float
    avg_entry: float
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    last_price: float = 0.0
    dex: str = ""          # pozisyonun acildigi platform (DEX adi)
    opened_ts: int = 0     # ilk acilis zamani (ms)

    @property
    def key(self) -> str:
        return f"{self.chain_id}:{self.base}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        # Turetilmis alanlar (frontend dogrudan kullanir):
        side = "LONG" if self.amount >= 0 else "SHORT"
        cost = abs(self.amount) * self.avg_entry          # maliyet (giris bazi)
        value = self.amount * self.last_price             # anlik deger (imzali)
        pnl_pct = 0.0
        if self.avg_entry > 0:
            change = (self.last_price - self.avg_entry) / self.avg_entry
            if self.amount < 0:        # short: fiyat dususe gecince kar
                change = -change
            pnl_pct = change * 100.0
        d["side"] = side
        d["costUsd"] = round(cost, 2)
        d["valueUsd"] = round(value, 2)
        d["pnlPct"] = round(pnl_pct, 2)
        d["dex"] = self.dex
        d["openedTs"] = self.opened_ts
        return d
