"""Hyperliquid perp (kaldıraçlı) işlem masası — kağıt ve canlı.

İki mod, TEK arayüz:

  • **paper**  — gerçek HL mark fiyatı, funding oranı ve kaldıraç tavanlarıyla
    simüle edilmiş dolumlar. Pozisyon defteri `data/hl_paper.json`. Likidasyon
    fiyatı ve funding maliyeti gerçek formüllerle hesaplanır, uydurulmaz.
  • **live**   — `hyperliquid-python-sdk` ile gerçek emir. İmzalayıcı iki
    kaynaktan gelebilir (bkz. `signer_info`):
        1. HL_API_WALLET_KEY  → HL'nin "API Wallet" (agent) anahtarı. Sadece
           işlem yetkisi vardır, PARA ÇEKEMEZ. Bu kullanıldığında ana hesap
           adresi HL_ACCOUNT_ADDRESS ile verilmelidir.
        2. engine.security.keystore → mevcut şifreli cüzdan (DEX ile ortak).
    Anahtar bulunamazsa canlı mod AÇILMAZ; broker kağıda düşer (fail-safe).

Canlı emir yolu ayrıca `HL_LIVE=1` bayrağı ister. Bayrak kapalıyken `mode`
"live" seçilse bile emir gönderilmez — kazara canlıya çıkma riskini kaldırır.

Fiyat/boyut yuvarlama: HL her varlık için `szDecimals` verir; boyut buna,
fiyat ise 5 anlamlı basamağa yuvarlanır (borsanın kabul kuralı).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from engine.marketdata.http import post_json

log = logging.getLogger("trading.hl")

INFO_URL = "https://api.hyperliquid.xyz/info"
MAINNET = "https://api.hyperliquid.xyz"
TESTNET = "https://api.hyperliquid-testnet.xyz"

# HL ücretleri (varsayılan kademe). Kağıt simülasyonu bunları uygular.
TAKER_FEE = 0.00045
MAKER_FEE = 0.00015
# Bakım teminatı: HL'de varlığın azami kaldıracının yarısının tersi.
#   maintenance = 1 / (2 * maxLeverage)
# Likidasyon bu eşikte gelir (teminatın tamamı erimeden önce).


def _f(x, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# --------------------------------------------------------------------- meta
_meta_cache: tuple[float, dict] | None = None
_META_TTL = 60.0


def universe() -> dict[str, dict]:
    """{sembol: {max_leverage, sz_decimals, mark, funding, oi}} — TTL cache'li."""
    global _meta_cache
    now = time.time()
    if _meta_cache and now - _meta_cache[0] < _META_TTL:
        return _meta_cache[1]
    meta, ctxs = post_json(INFO_URL, {"type": "metaAndAssetCtxs"}, ttl=15)
    out: dict[str, dict] = {}
    for u, c in zip(meta.get("universe", []), ctxs):
        name = u.get("name")
        if not name or u.get("isDelisted"):
            continue
        mark = _f(c.get("markPx") or c.get("midPx"))
        if mark <= 0:
            continue
        out[name] = {
            "symbol": name,
            "max_leverage": int(u.get("maxLeverage", 1) or 1),
            "sz_decimals": int(u.get("szDecimals", 2) or 0),
            "mark": mark,
            "funding_hourly": _f(c.get("funding")),
            "open_interest_usd": _f(c.get("openInterest")) * mark,
            "day_volume_usd": _f(c.get("dayNtlVlm")),
            "prev_day_px": _f(c.get("prevDayPx")),
        }
    _meta_cache = (now, out)
    return out


def normalize_symbol(symbol: str) -> str:
    """'BTCUSDT' / 'btc-perp' / 'WETH' → HL evrenindeki ad ('BTC', 'ETH')."""
    s = (symbol or "").upper().replace("-PERP", "").replace("_", "")
    for suffix in ("USDT", "USDC", "USD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    if s == "WETH":
        s = "ETH"
    if s == "WBTC":
        s = "BTC"
    return s


def round_size(symbol: str, size: float) -> float:
    d = (universe().get(symbol) or {}).get("sz_decimals", 3)
    return round(size, d)


def round_price(price: float, sz_decimals: int = 2) -> float:
    """HL kuralı: en fazla 5 anlamlı basamak ve (6 - szDecimals) ondalık."""
    if price <= 0:
        return price
    import math
    max_dec = max(0, 6 - sz_decimals)
    sig = 5 - max(0, int(math.floor(math.log10(abs(price)))) + 1)
    return round(price, max(0, min(max_dec, sig if sig > 0 else 0)))


# ------------------------------------------------------------ likidasyon
def maintenance_margin(symbol: str) -> float:
    lev = (universe().get(symbol) or {}).get("max_leverage", 20)
    return 1.0 / (2.0 * max(1, lev))


def liquidation_price(entry: float, leverage: float, side: str,
                      symbol: str = "") -> float | None:
    """HL izole marj likidasyon fiyatı.

    liq = entry ± entry * (1/lev - maintenance) / (1 ∓ 0)  (izole, tek pozisyon)
    LONG için aşağı, SHORT için yukarı. Kaldıraç 0 veya giriş 0 ise None.
    """
    if entry <= 0 or leverage <= 0:
        return None
    mm = maintenance_margin(symbol) if symbol else 0.005
    move = (1.0 / leverage) - mm
    px = entry * (1 - move) if side == "LONG" else entry * (1 + move)
    return round(max(0.0, px), 6)


# ---------------------------------------------------------------- modeller
@dataclass
class HLPosition:
    symbol: str
    side: str                 # LONG | SHORT
    size: float               # coin cinsinden, daima pozitif
    entry: float
    leverage: float
    margin_usd: float
    opened_ts: int
    funding_paid_usd: float = 0.0
    fees_paid_usd: float = 0.0
    last_funding_ts: int = 0

    def notional(self, mark: float) -> float:
        return self.size * mark

    def unrealized(self, mark: float) -> float:
        diff = (mark - self.entry) if self.side == "LONG" else (self.entry - mark)
        return diff * self.size

    def to_dict(self, mark: float) -> dict:
        liq = liquidation_price(self.entry, self.leverage, self.side, self.symbol)
        upnl = self.unrealized(mark)
        d = asdict(self)
        d.update({
            "mark": mark,
            "notional_usd": round(self.notional(mark), 2),
            "unrealized_pnl": round(upnl, 2),
            "roe_pct": round(upnl / self.margin_usd * 100, 2) if self.margin_usd else None,
            "liq_price": liq,
            "liq_distance_pct": round(abs(mark - liq) / mark * 100, 2)
            if liq and mark else None,
        })
        return d


@dataclass
class PaperBook:
    cash_usd: float = 1000.0
    positions: dict[str, HLPosition] = field(default_factory=dict)
    realized_pnl_usd: float = 0.0
    day_realized_pnl_usd: float = 0.0
    day_key: str = ""
    history: list[dict] = field(default_factory=list)


# ----------------------------------------------------------------- imzalayıcı
def signer_info() -> dict:
    """Hangi imzalama kaynağının kullanılabildiğini raporlar (anahtar SIZDIRMAZ)."""
    api_key = (os.getenv("HL_API_WALLET_KEY") or "").strip()
    acct = (os.getenv("HL_ACCOUNT_ADDRESS") or "").strip()
    out = {"api_wallet": bool(api_key), "account_address": acct or None,
           "keystore": False, "source": None, "ready": False, "reason": None}
    if api_key:
        if not acct:
            out["reason"] = ("HL_API_WALLET_KEY var ama HL_ACCOUNT_ADDRESS yok — "
                             "API wallet ile imzalarken ANA hesap adresi gerekir")
        else:
            out.update(source="api_wallet", ready=True)
            return out
    try:
        from engine.security.keystore import load_private_key
        if load_private_key():
            out["keystore"] = True
            if not out["ready"]:
                out.update(source="keystore", ready=True)
            return out
    except Exception:  # noqa: BLE001
        pass
    if not out["reason"]:
        out["reason"] = ("İmzalama anahtarı yok — .env'e HL_API_WALLET_KEY "
                         "(+HL_ACCOUNT_ADDRESS) ekleyin ya da şifreli keystore "
                         "tanımlayın. Kağıt mod anahtarsız çalışır.")
    return out


def live_enabled() -> bool:
    """Canlı emir bayrağı. Kapalıyken 'live' mod seçilse bile emir gitmez."""
    return os.getenv("HL_LIVE", "0").strip().lower() in ("1", "true", "yes")


def testnet() -> bool:
    return os.getenv("HL_TESTNET", "0").strip().lower() in ("1", "true", "yes")


# -------------------------------------------------------------------- broker
class HLBroker:
    """Kağıt ve canlı Hyperliquid perp brokeri. Tek örnek kullanılır (`hl`)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._book = PaperBook()
        self._loaded = False
        self._exchange = None       # lazy: hyperliquid.exchange.Exchange
        self._exchange_err: str | None = None

    # ---------------------------------------------------------- kalıcılık
    def _path(self) -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "hl_paper.json")

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        p = self._path()
        if not os.path.exists(p):
            self._book.cash_usd = _f(os.getenv("HL_PAPER_SEED_USD", "1000"), 1000.0)
            return
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
            self._book = PaperBook(
                cash_usd=_f(raw.get("cash_usd"), 1000.0),
                realized_pnl_usd=_f(raw.get("realized_pnl_usd")),
                day_realized_pnl_usd=_f(raw.get("day_realized_pnl_usd")),
                day_key=raw.get("day_key", ""),
                history=raw.get("history") or [],
                positions={k: HLPosition(**v) for k, v in (raw.get("positions") or {}).items()},
            )
        except Exception as e:  # noqa: BLE001
            log.warning("hl kağıt defteri okunamadı (%s) — sıfırdan başlanıyor", e)
            self._book = PaperBook(cash_usd=_f(os.getenv("HL_PAPER_SEED_USD", "1000"), 1000.0))

    def _save(self) -> None:
        p = self._path()
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            data = {
                "cash_usd": self._book.cash_usd,
                "realized_pnl_usd": self._book.realized_pnl_usd,
                "day_realized_pnl_usd": self._book.day_realized_pnl_usd,
                "day_key": self._book.day_key,
                "history": self._book.history[-200:],
                "positions": {k: asdict(v) for k, v in self._book.positions.items()},
            }
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception as e:  # noqa: BLE001
            log.warning("hl kağıt defteri yazılamadı: %s", e)

    # ------------------------------------------------------------- canlı
    def _get_exchange(self):
        """hyperliquid-python-sdk Exchange örneği (lazy). Hata -> None + gerekçe."""
        if self._exchange is not None or self._exchange_err:
            return self._exchange
        info = signer_info()
        if not info["ready"]:
            self._exchange_err = info["reason"]
            return None
        try:
            from eth_account import Account
            from hyperliquid.exchange import Exchange
        except ImportError as e:
            self._exchange_err = (f"hyperliquid-python-sdk kurulu değil ({e}) — "
                                  "`pip install hyperliquid-python-sdk`")
            return None
        try:
            if info["source"] == "api_wallet":
                wallet = Account.from_key(os.environ["HL_API_WALLET_KEY"])
                account_address = os.environ["HL_ACCOUNT_ADDRESS"]
            else:
                from engine.security.keystore import load_private_key
                wallet = Account.from_key(load_private_key())
                account_address = wallet.address
            self._exchange = Exchange(
                wallet, base_url=(TESTNET if testnet() else MAINNET),
                account_address=account_address)
            log.info("HL canlı imzalayıcı hazır (%s, hesap %s…%s)",
                     info["source"], account_address[:6], account_address[-4:])
        except Exception as e:  # noqa: BLE001
            self._exchange_err = f"HL imzalayıcı kurulamadı: {e}"
            log.warning(self._exchange_err)
            return None
        return self._exchange

    def live_ready(self) -> dict:
        """Canlı emir gönderilebilir mi — ve gönderilemiyorsa neden?"""
        info = signer_info()
        flag = live_enabled()
        ex = self._get_exchange() if (flag and info["ready"]) else None
        reasons = []
        if not flag:
            reasons.append("HL_LIVE=0 (canlı emir bayrağı kapalı)")
        if not info["ready"]:
            reasons.append(info["reason"] or "imzalayıcı yok")
        if flag and info["ready"] and ex is None:
            reasons.append(self._exchange_err or "imzalayıcı kurulamadı")
        return {"ready": bool(flag and info["ready"] and ex is not None),
                "flag": flag, "signer": info, "testnet": testnet(),
                "reasons": reasons}

    # ------------------------------------------------------------- durum
    def _roll_day(self) -> None:
        key = time.strftime("%Y-%m-%d", time.gmtime())
        if self._book.day_key != key:
            self._book.day_key = key
            self._book.day_realized_pnl_usd = 0.0

    def _accrue_funding(self, uni: dict) -> None:
        """Kağıt modda geçen süre kadar funding tahakkuk ettir.

        HL'de funding SAATLİK ödenir. LONG pozitif funding'de ÖDER, negatifte
        ALIR; SHORT tersi. Simülasyonun gerçekçi kalması için şart.
        """
        now = int(time.time())
        for pos in self._book.positions.values():
            u = uni.get(pos.symbol)
            if not u:
                continue
            if not pos.last_funding_ts:
                pos.last_funding_ts = now
                continue
            hours = (now - pos.last_funding_ts) / 3600.0
            if hours < 0.02:      # ~1 dk'dan azsa atla (gürültü)
                continue
            rate = u["funding_hourly"] * hours
            cost = pos.notional(u["mark"]) * rate
            if pos.side == "SHORT":
                cost = -cost
            pos.funding_paid_usd += cost
            self._book.cash_usd -= cost
            pos.last_funding_ts = now

    def _check_liquidations(self, uni: dict) -> list[dict]:
        """Kağıt modda likidasyon kontrolü — marj biterse pozisyon silinir."""
        hit = []
        for sym, pos in list(self._book.positions.items()):
            u = uni.get(sym)
            if not u:
                continue
            liq = liquidation_price(pos.entry, pos.leverage, pos.side, sym)
            if liq is None:
                continue
            mark = u["mark"]
            gone = (pos.side == "LONG" and mark <= liq) or \
                   (pos.side == "SHORT" and mark >= liq)
            if gone:
                loss = -pos.margin_usd
                self._book.realized_pnl_usd += loss
                self._book.day_realized_pnl_usd += loss
                self._book.history.append({
                    "t": int(time.time() * 1000), "symbol": sym, "action": "LIQUIDATED",
                    "side": pos.side, "size": pos.size, "price": mark,
                    "pnl_usd": round(loss, 2), "mode": "paper"})
                del self._book.positions[sym]
                hit.append({"symbol": sym, "liq_price": liq, "mark": mark})
                log.warning("HL KAĞIT LİKİDASYON: %s %s @ %.4f (liq %.4f)",
                            sym, pos.side, mark, liq)
        return hit

    def state(self) -> dict:
        """Hesap durumu. Canlıysa HL'den, değilse kağıt defterinden."""
        with self._lock:
            self._load()
            self._roll_day()
            uni = universe()
            live = self.live_ready()
            if live["ready"]:
                try:
                    return self._live_state(uni)
                except Exception as e:  # noqa: BLE001
                    log.warning("HL canlı durum alınamadı (%s) — kağıt gösteriliyor", e)
            self._accrue_funding(uni)
            liq_hits = self._check_liquidations(uni)
            self._save()
            positions = [p.to_dict(uni.get(p.symbol, {}).get("mark", p.entry))
                         for p in self._book.positions.values()]
            upnl = sum(p["unrealized_pnl"] for p in positions)
            margin = sum(p["margin_usd"] for p in positions)
            return {
                "mode": "paper", "ok": True,
                "equity_usd": round(self._book.cash_usd + margin + upnl, 2),
                "cash_usd": round(self._book.cash_usd, 2),
                "margin_used_usd": round(margin, 2),
                "unrealized_pnl": round(upnl, 2),
                "realized_pnl": round(self._book.realized_pnl_usd, 2),
                "day_realized_pnl": round(self._book.day_realized_pnl_usd, 2),
                "positions": positions,
                "history": self._book.history[-40:][::-1],
                "liquidations": liq_hits,
                "live": live,
            }

    def _live_state(self, uni: dict) -> dict:
        addr = (os.getenv("HL_ACCOUNT_ADDRESS") or "").strip()
        if not addr:
            ex = self._get_exchange()
            addr = getattr(ex, "account_address", "") if ex else ""
        st = post_json(INFO_URL, {"type": "clearinghouseState", "user": addr}, ttl=5)
        ms = st.get("marginSummary") or {}
        positions = []
        for ap in (st.get("assetPositions") or []):
            p = ap.get("position") or {}
            szi = _f(p.get("szi"))
            if szi == 0:
                continue
            sym = p.get("coin")
            lev = _f((p.get("leverage") or {}).get("value"), 1.0)
            entry = _f(p.get("entryPx"))
            side = "LONG" if szi > 0 else "SHORT"
            mark = (uni.get(sym) or {}).get("mark", entry)
            positions.append({
                "symbol": sym, "side": side, "size": abs(szi), "entry": entry,
                "leverage": lev, "mark": mark,
                "margin_usd": round(_f(p.get("marginUsed")), 2),
                "notional_usd": round(_f(p.get("positionValue")), 2),
                "unrealized_pnl": round(_f(p.get("unrealizedPnl")), 2),
                "roe_pct": round(_f(p.get("returnOnEquity")) * 100, 2),
                "liq_price": _f(p.get("liquidationPx")) or None,
                "liq_distance_pct": (round(abs(mark - _f(p.get("liquidationPx")))
                                           / mark * 100, 2)
                                     if mark and _f(p.get("liquidationPx")) else None),
                "funding_paid_usd": round(-_f((p.get("cumFunding") or {}).get("sinceOpen")), 2),
                "fees_paid_usd": 0.0, "opened_ts": 0, "last_funding_ts": 0,
            })
        return {
            "mode": "live", "ok": True,
            "equity_usd": round(_f(ms.get("accountValue")), 2),
            "cash_usd": round(_f(st.get("withdrawable")), 2),
            "margin_used_usd": round(_f(ms.get("totalMarginUsed")), 2),
            "unrealized_pnl": round(sum(p["unrealized_pnl"] for p in positions), 2),
            "realized_pnl": None, "day_realized_pnl": self._book.day_realized_pnl_usd,
            "positions": positions, "history": self._book.history[-40:][::-1],
            "liquidations": [], "live": self.live_ready(), "address": addr,
        }

    # ------------------------------------------------------------- emirler
    def set_leverage(self, symbol: str, leverage: int, cross: bool = False) -> dict:
        sym = normalize_symbol(symbol)
        u = universe().get(sym)
        if not u:
            return {"ok": False, "error": f"{sym} Hyperliquid'de yok"}
        lev = max(1, min(int(leverage), u["max_leverage"]))
        live = self.live_ready()
        if live["ready"]:
            ex = self._get_exchange()
            try:
                res = ex.update_leverage(lev, sym, cross)
                return {"ok": True, "mode": "live", "symbol": sym,
                        "leverage": lev, "raw": res}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)[:200]}
        return {"ok": True, "mode": "paper", "symbol": sym, "leverage": lev,
                "note": "kağıt modda kaldıraç emir anında uygulanır"}

    def open(self, symbol: str, side: str, *, notional_usd: float | None = None,
             size: float | None = None, leverage: int = 3,
             order_type: str = "market", limit_price: float | None = None,
             reduce_only: bool = False, source: str = "manual",
             slippage: float = 0.01) -> dict:
        """Pozisyon aç/ekle. `notional_usd` verilirse boyut mark fiyatından türetilir."""
        with self._lock:
            self._load()
            self._roll_day()
            sym = normalize_symbol(symbol)
            u = universe().get(sym)
            if not u:
                return {"ok": False, "error": f"{sym} Hyperliquid perp evreninde yok"}
            side = side.upper()
            if side not in ("LONG", "SHORT"):
                return {"ok": False, "error": "yön LONG veya SHORT olmalı"}
            mark = u["mark"]
            lev = max(1, min(int(leverage), u["max_leverage"]))
            if size is None:
                if not notional_usd or notional_usd <= 0:
                    return {"ok": False, "error": "notional_usd veya size gerekli"}
                size = notional_usd / mark
            size = round_size(sym, abs(size))
            if size <= 0:
                return {"ok": False, "error": "boyut çok küçük (szDecimals'a yuvarlandı)"}
            notional = size * mark
            if notional < 10:
                return {"ok": False, "error": "Hyperliquid asgari emir büyüklüğü ~$10"}

            live = self.live_ready()
            if live["ready"]:
                return self._live_order(sym, side, size, lev, order_type,
                                        limit_price, reduce_only, slippage, source, u)
            return self._paper_order(sym, side, size, lev, mark, order_type,
                                     limit_price, reduce_only, source, u)

    def _live_order(self, sym, side, size, lev, order_type, limit_price,
                    reduce_only, slippage, source, u) -> dict:
        ex = self._get_exchange()
        if ex is None:
            return {"ok": False, "error": self._exchange_err or "imzalayıcı yok"}
        try:
            ex.update_leverage(lev, sym, False)   # izole marj
        except Exception as e:  # noqa: BLE001
            log.warning("HL kaldıraç ayarlanamadı (%s): %s", sym, e)
        is_buy = side == "LONG"
        try:
            if order_type == "limit" and limit_price:
                px = round_price(float(limit_price), u["sz_decimals"])
                res = ex.order(sym, is_buy, size, px,
                               {"limit": {"tif": "Gtc"}}, reduce_only=reduce_only)
            else:
                res = ex.market_open(sym, is_buy, size, None, slippage)
        except Exception as e:  # noqa: BLE001
            log.warning("HL canlı emir hatası %s %s: %s", sym, side, e)
            return {"ok": False, "error": str(e)[:200]}
        ok = str((res or {}).get("status", "")).lower() == "ok"
        entry = self._fill_price(res) or u["mark"]
        rec = {"t": int(time.time() * 1000), "symbol": sym, "action": "OPEN",
               "side": side, "size": size, "price": entry, "leverage": lev,
               "mode": "live", "source": source, "raw_status": (res or {}).get("status")}
        self._book.history.append(rec)
        self._save()
        return {"ok": ok, "mode": "live", "symbol": sym, "side": side,
                "size": size, "leverage": lev, "price": entry,
                "liq_price": liquidation_price(entry, lev, side, sym),
                "raw": res, "source": source}

    @staticmethod
    def _fill_price(res) -> float | None:
        try:
            statuses = res["response"]["data"]["statuses"]
            for st in statuses:
                if "filled" in st:
                    return float(st["filled"]["avgPx"])
        except Exception:  # noqa: BLE001
            pass
        return None

    def _paper_order(self, sym, side, size, lev, mark, order_type, limit_price,
                     reduce_only, source, u) -> dict:
        # Kağıt dolum: market emir taker olarak mark ± kayma; limit emir maker.
        taker = order_type != "limit"
        slip = 0.0005 if taker else 0.0
        fill = mark * (1 + slip) if side == "LONG" else mark * (1 - slip)
        if order_type == "limit" and limit_price:
            fill = float(limit_price)
        fee = size * fill * (TAKER_FEE if taker else MAKER_FEE)
        margin = size * fill / lev

        pos = self._book.positions.get(sym)
        if pos and pos.side != side:
            # Ters yön: önce mevcut pozisyonu kapat (net-out davranışı)
            close_size = min(pos.size, size)
            self._close_paper(sym, close_size, fill, source=source)
            pos = self._book.positions.get(sym)
            size -= close_size
            if size <= 0:
                return {"ok": True, "mode": "paper", "symbol": sym,
                        "action": "reduced", "price": fill}
            margin = size * fill / lev

        if reduce_only:
            return {"ok": False, "error": "reduce-only ama ters pozisyon yok"}
        if margin + fee > self._book.cash_usd:
            return {"ok": False,
                    "error": f"yetersiz kağıt teminat: gerekli ${margin + fee:,.2f}, "
                             f"var ${self._book.cash_usd:,.2f}"}

        self._book.cash_usd -= margin + fee
        if pos:
            total = pos.size + size
            pos.entry = (pos.entry * pos.size + fill * size) / total
            pos.size = total
            pos.margin_usd += margin
            pos.fees_paid_usd += fee
            pos.leverage = lev
        else:
            self._book.positions[sym] = HLPosition(
                symbol=sym, side=side, size=size, entry=fill, leverage=lev,
                margin_usd=margin, opened_ts=int(time.time() * 1000),
                fees_paid_usd=fee, last_funding_ts=int(time.time()))
        rec = {"t": int(time.time() * 1000), "symbol": sym, "action": "OPEN",
               "side": side, "size": size, "price": round(fill, 6), "leverage": lev,
               "fee_usd": round(fee, 4), "mode": "paper", "source": source}
        self._book.history.append(rec)
        self._save()
        return {"ok": True, "mode": "paper", "symbol": sym, "side": side,
                "size": size, "leverage": lev, "price": round(fill, 6),
                "fee_usd": round(fee, 4), "margin_usd": round(margin, 2),
                "liq_price": liquidation_price(fill, lev, side, sym), "source": source}

    def close(self, symbol: str, size: float | None = None,
              source: str = "manual") -> dict:
        with self._lock:
            self._load()
            sym = normalize_symbol(symbol)
            live = self.live_ready()
            if live["ready"]:
                ex = self._get_exchange()
                if ex is None:
                    return {"ok": False, "error": self._exchange_err or "imzalayıcı yok"}
                try:
                    res = ex.market_close(sym, size)
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "error": str(e)[:200]}
                self._book.history.append({
                    "t": int(time.time() * 1000), "symbol": sym, "action": "CLOSE",
                    "size": size, "mode": "live", "source": source})
                self._save()
                return {"ok": str((res or {}).get("status", "")).lower() == "ok",
                        "mode": "live", "symbol": sym, "raw": res, "source": source}
            pos = self._book.positions.get(sym)
            if not pos:
                return {"ok": False, "error": f"{sym} için açık pozisyon yok"}
            mark = (universe().get(sym) or {}).get("mark", pos.entry)
            return self._close_paper(sym, size or pos.size, mark, source=source)

    def _close_paper(self, sym: str, size: float, price: float,
                     source: str = "manual") -> dict:
        pos = self._book.positions.get(sym)
        if not pos:
            return {"ok": False, "error": "pozisyon yok"}
        size = min(round_size(sym, abs(size)), pos.size)
        if size <= 0:
            return {"ok": False, "error": "kapatılacak boyut 0"}
        frac = size / pos.size
        diff = (price - pos.entry) if pos.side == "LONG" else (pos.entry - price)
        pnl = diff * size
        fee = size * price * TAKER_FEE
        released = pos.margin_usd * frac
        self._book.cash_usd += released + pnl - fee
        self._book.realized_pnl_usd += pnl - fee
        self._book.day_realized_pnl_usd += pnl - fee
        pos.size -= size
        pos.margin_usd -= released
        if pos.size <= 1e-12:
            del self._book.positions[sym]
        self._book.history.append({
            "t": int(time.time() * 1000), "symbol": sym, "action": "CLOSE",
            "side": pos.side, "size": size, "price": round(price, 6),
            "pnl_usd": round(pnl - fee, 2), "fee_usd": round(fee, 4),
            "mode": "paper", "source": source})
        self._save()
        return {"ok": True, "mode": "paper", "symbol": sym, "size": size,
                "price": round(price, 6), "pnl_usd": round(pnl - fee, 2),
                "source": source}

    def reset_paper(self, seed_usd: float = 1000.0) -> dict:
        with self._lock:
            self._loaded = True
            self._book = PaperBook(cash_usd=max(10.0, seed_usd))
            self._save()
            return {"ok": True, "cash_usd": self._book.cash_usd}

    def day_pnl(self) -> float:
        with self._lock:
            self._load()
            self._roll_day()
            return self._book.day_realized_pnl_usd


hl = HLBroker()
