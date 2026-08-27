"""Borsa giriş/çıkış baskısı & smart-money radarı.

Katmanlar (üstten aşağı, mevcut olan kullanılır):
  1. Nansen (NANSEN_API_KEY)     — gerçek smart-money zincir akışları
  2. CoinGlass (COINGLASS_API_KEY) — borsa rezerv bakiyeleri ve 1g/7g değişimi
  3. ÜCRETSİZ VEKİL              — Binance taker alım/satım dengesi + büyük
     işlem baskısı (whales.py) çoklu sembol üzerinde taranır

Vekil katman anahtarsız çalışır ve "kim alıyor/satıyor" sorusunun piyasa-içi
(orderflow) cevabını verir; zincir-üstü cüzdan etiketlemesi için Nansen gerekir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from engine.marketdata import whales as whales_mod
from engine.marketdata.http import get_json
from engine.marketdata.intel import coinglass, nansen
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.flows")

FAPI = "https://fapi.binance.com/futures/data"

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK"]


def _f(x, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def taker_flow(symbol: str, period: str = "1h", limit: int = 24) -> dict:
    """Binance vadeli taker alım/satım hacim oranı — agresif taraf kim?"""
    sym = symbol.upper()
    sym = sym if sym.endswith("USDT") else f"{sym}USDT"
    rows = get_json(f"{FAPI}/takerlongshortRatio?symbol={sym}"
                    f"&period={period}&limit={min(limit, 500)}", ttl=120)
    if not rows:
        return {"ok": False, "symbol": symbol}
    series = [{"t": int(r["timestamp"]),
               "buy_vol": _f(r.get("buyVol")), "sell_vol": _f(r.get("sellVol")),
               "ratio": _f(r.get("buySellRatio"), 1.0)} for r in rows]
    buy = sum(s["buy_vol"] for s in series)
    sell = sum(s["sell_vol"] for s in series)
    tot = buy + sell
    imb = (buy - sell) / tot if tot > 0 else 0.0
    return {"ok": True, "symbol": symbol.upper(),
            "buy_volume": round(buy, 2), "sell_volume": round(sell, 2),
            "imbalance": round(imb, 4), "ratio": round(buy / sell, 3) if sell else None,
            "series": series[-24:]}


def _proxy_row(sym: str) -> dict | None:
    """Tek sembol icin orderflow vekili. GERCEK veri yoksa None (sahte notr yok)."""
    taker, whale = None, None
    try:
        taker = taker_flow(sym)
    except Exception as e:  # noqa: BLE001
        log.debug("%s taker akisi yok: %s", sym, e)
    try:
        w = whales_mod.summary(sym)
        # whales.summary hata durumunda da dict doner; big_count=0 ise VERI YOK.
        if ((w.get("pressure") or {}).get("big_count") or 0) > 0:
            whale = w
    except Exception as e:  # noqa: BLE001
        log.debug("%s balina ozeti yok: %s", sym, e)
    if not (taker and taker.get("ok")) and whale is None:
        return None
    t_imb = (taker or {}).get("imbalance", 0.0) or 0.0
    w_score = ((whale or {}).get("pressure") or {}).get("score", 0.0) or 0.0
    if whale is None:
        score = max(-1.0, min(1.0, t_imb * 3))
    elif not (taker and taker.get("ok")):
        score = float(w_score)
    else:
        score = 0.55 * (t_imb * 3) + 0.45 * float(w_score)
    score = round(max(-1.0, min(1.0, score)), 3)
    return {
        "symbol": sym.upper(),
        "taker_imbalance": round(t_imb, 4),
        "whale_score": round(float(w_score), 3),
        "score": score,
        "label": ("birikim" if score > 0.2 else
                  "dağıtım" if score < -0.2 else "nötr"),
        "buy_volume": (taker or {}).get("buy_volume"),
        "sell_volume": (taker or {}).get("sell_volume"),
    }


def _proxy_radar(symbols: list[str]) -> dict:
    """Anahtarsiz smart-money vekili: taker dengesizligi + balina baskisi."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = [r for r in ex.map(_proxy_row, symbols) if r]
    rows.sort(key=lambda r: -abs(r["score"]))
    if not rows:
        return {"ok": False, "source": "proxy", "rows": [], "score": 0.0,
                "reason": ("borsa verisine ulaşılamadı (Binance erişimi "
                           "engelli olabilir) — NANSEN_API_KEY ile zincir-üstü "
                           "kaynağa geçebilirsiniz")}
    net = sum(r["score"] for r in rows) / len(rows)
    return {"ok": True, "source": "proxy", "rows": rows,
            "score": round(net, 3),
            "accumulation": [r for r in rows if r["score"] > 0.2][:5],
            "distribution": [r for r in rows if r["score"] < -0.2][:5],
            "note": "Nansen anahtarı yok — orderflow tabanlı vekil kullanılıyor"}


def smart_money(symbols: list[str] | None = None) -> dict:
    """Smart-money radarı (Nansen varsa gerçek, yoksa orderflow vekili)."""
    syms = symbols or DEFAULT_SYMBOLS

    def _build() -> dict:
        if nansen.enabled():
            n = nansen.smart_money_flows()
            if n.get("ok"):
                return n
            log.info("nansen boş döndü — vekile düşülüyor: %s", n.get("reason"))
        return _proxy_radar(syms)
    return cached("flows:smartmoney:" + ",".join(syms), 300, _build)


def exchange_reserves(symbol: str = "BTC") -> dict:
    """Borsa rezervleri — düşen rezerv = birikim, artan = satış baskısı."""
    def _build() -> dict:
        if coinglass.enabled():
            cg = coinglass.exchange_balance(symbol)
            if cg.get("ok"):
                total = sum(r["balance"] for r in cg["rows"])
                d1 = sum(r["change_1d"] for r in cg["rows"])
                d7 = sum(r["change_7d"] for r in cg["rows"])
                bias = 0.0
                if total > 0:
                    bias = max(-1.0, min(1.0, -(d7 / total) * 100))
                return {"ok": True, "source": "coinglass", "symbol": symbol,
                        "total": round(total, 2), "change_1d": round(d1, 2),
                        "change_7d": round(d7, 2), "rows": cg["rows"],
                        "bias": round(bias, 3),
                        "note": ("rezerv düşüyor — birikim" if d7 < 0
                                 else "rezerv artıyor — satış baskısı")}
        # Anahtarsız yedek: bilinen ETH borsa cüzdanları (Etherscan gerekir)
        from engine.marketdata import onchain as onchain_mod
        if symbol.upper() in ("ETH", "WETH") and onchain_mod.enabled():
            b = onchain_mod.exchange_eth_balances()
            return {"ok": True, "source": "etherscan", "symbol": "ETH",
                    "total": b["total_eth"], "rows": [
                        {"exchange": k, "balance": v, "change_1d": 0.0,
                         "change_7d": 0.0} for k, v in b["wallets"].items()],
                    "bias": 0.0, "note": "anlık bakiye (trend için geçmiş gerekir)"}
        return {"ok": False, "source": None, "symbol": symbol, "rows": [],
                "reason": "COINGLASS_API_KEY (veya ETH için ETHERSCAN_API_KEY) yok"}
    return cached(f"flows:reserves:{symbol}", 900, _build)
