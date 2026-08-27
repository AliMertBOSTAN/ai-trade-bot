"""Hyperliquid radarı — global duyarlılık + kazanan cüzdan pozisyonları.

Tümü Hyperliquid'in AÇIK API'si; anahtar gerekmez.

  POST /info {"type":"metaAndAssetCtxs"}          → tüm perp bağlamları
  POST /info {"type":"clearinghouseState",...}    → bir cüzdanın açık pozisyonları
  GET  stats-data.hyperliquid.xyz/Mainnet/leaderboard → PnL sıralaması

Paneller:
  sentiment()         — OI ağırlıklı funding, yükselen/düşen oranı, global bias
  winner_positions()  — kâr sıralamasındaki cüzdanların net LONG/SHORT dağılımı
  watchlist()         — .env HL_WATCH_WALLETS ile takip edilen cüzdanlar
  radar()             — hepsini tek yanıtta birleştirir

Kazanan cüzdan analizi maliyetlidir (cüzdan başına 1 istek); bu yüzden en fazla
`_MAX_WALLETS` cüzdan taranır ve sonuç 10 dakika cache'lenir.
"""
from __future__ import annotations

import logging
import os

from engine.marketdata.http import get_json, post_json
from engine.marketdata.intel import keys
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.hl")

INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

_MAX_WALLETS = 12
_MIN_ACCOUNT_VALUE = 250_000.0  # küçük hesaplar sinyal taşımaz

# Hyperliquid'in genel PnL sıralaması ~35 MB'lık TEK bir JSON'dur. Her tazelemede
# indirmek kabul edilemez (günde GB'lar) ve sık sık yarım gelir. Bu yüzden
# varsayılan KAPALI: .env HL_LEADERBOARD=1 ile açılır. Açık değilken "kazanan
# cüzdan" paneli HL_WATCH_WALLETS listesinden beslenir.
_LEADERBOARD_MAX_BYTES = 60 * 1024 * 1024


def _f(x, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# --------------------------------------------------------------- global bias
def sentiment() -> dict:
    """Tüm perp evreninden global duyarlılık: funding, OI, yükselen oranı."""
    def _build() -> dict:
        meta, ctxs = post_json(INFO, {"type": "metaAndAssetCtxs"}, ttl=30)
        universe = meta.get("universe", [])
        rows = []
        for u, c in zip(universe, ctxs):
            name = u.get("name") or ""
            if not name or u.get("isDelisted"):
                continue
            mark = _f(c.get("markPx") or c.get("midPx"))
            if mark <= 0:
                continue
            prev = _f(c.get("prevDayPx"))
            oi = _f(c.get("openInterest")) * mark
            rows.append({
                "symbol": name, "price": mark,
                "change_pct_24h": round((mark - prev) / prev * 100, 2) if prev else None,
                "volume_usd": round(_f(c.get("dayNtlVlm")), 0),
                "funding_pct": round(_f(c.get("funding")) * 100, 5),
                "open_interest_usd": round(oi, 0),
            })
        if not rows:
            return {"ok": False, "rows": []}
        total_oi = sum(r["open_interest_usd"] for r in rows) or 1.0
        w_funding = sum(r["funding_pct"] * r["open_interest_usd"]
                        for r in rows) / total_oi
        ups = [r for r in rows if (r["change_pct_24h"] or 0) > 0]
        breadth = len(ups) / len(rows)

        # Funding pozitifse kalabalık LONG (contrarian aşağı), negatifse tersi.
        # Saatlik funding: %0.0125 nötr taban (yıllık ~%11).
        f_bias = max(-1.0, min(1.0, -(w_funding - 0.00125) / 0.005))
        b_bias = (breadth - 0.5) * 2.0
        score = round(max(-1.0, min(1.0, 0.6 * f_bias + 0.4 * b_bias)), 3)
        label = ("risk iştahı yüksek" if score > 0.3 else
                 "kalabalık long — dikkat" if score < -0.3 else "dengeli")

        top_oi = sorted(rows, key=lambda r: -r["open_interest_usd"])[:10]
        top_vol = sorted(rows, key=lambda r: -r["volume_usd"])[:10]
        movers = sorted([r for r in rows if r["change_pct_24h"] is not None],
                        key=lambda r: -abs(r["change_pct_24h"]))[:10]
        return {"ok": True, "count": len(rows),
                "total_oi_usd": round(total_oi, 0),
                "total_volume_24h": round(sum(r["volume_usd"] for r in rows), 0),
                "weighted_funding_pct": round(w_funding, 5),
                "breadth_pct": round(breadth * 100, 1),
                "score": score, "label": label,
                "top_oi": top_oi, "top_volume": top_vol, "movers": movers}
    return cached("hl:sentiment", 60, _build)


# --------------------------------------------------- kazanan cüzdan pozisyonu
def leaderboard_enabled() -> bool:
    return os.getenv("HL_LEADERBOARD", "0").strip().lower() in ("1", "true", "yes")


def _leaderboard_addresses(window: str = "day") -> list[tuple[str, float, float]]:
    """(adres, hesap değeri, pencere PnL) — PnL'e göre azalan. ~35 MB indirir."""
    d = get_json(LEADERBOARD, ttl=3600, timeout=90)
    rows = d.get("leaderboardRows") or []
    out: list[tuple[str, float, float]] = []
    for r in rows:
        addr = r.get("ethAddress") or ""
        av = _f(r.get("accountValue"))
        if not addr.startswith("0x") or av < _MIN_ACCOUNT_VALUE:
            continue
        pnl = 0.0
        for w in (r.get("windowPerformances") or []):
            if isinstance(w, list) and len(w) == 2 and w[0] == window:
                pnl = _f((w[1] or {}).get("pnl"))
        out.append((addr, av, pnl))
    out.sort(key=lambda t: -t[2])
    return out


def _wallet_positions(addr: str) -> list[dict]:
    st = post_json(INFO, {"type": "clearinghouseState", "user": addr}, ttl=300)
    out = []
    for ap in (st.get("assetPositions") or []):
        p = ap.get("position") or {}
        szi = _f(p.get("szi"))
        if szi == 0:
            continue
        out.append({
            "symbol": p.get("coin"),
            "side": "LONG" if szi > 0 else "SHORT",
            "notional_usd": abs(_f(p.get("positionValue"))),
            "entry": _f(p.get("entryPx")),
            "unrealized_pnl": _f(p.get("unrealizedPnl")),
            "leverage": _f((p.get("leverage") or {}).get("value")),
        })
    return out


def _aggregate(wallets: list[tuple[str, float, float]], label: str) -> dict:
    per_coin: dict[str, dict] = {}
    scanned, failed = 0, 0
    for addr, _av, pnl in wallets[:_MAX_WALLETS]:
        try:
            positions = _wallet_positions(addr)
            scanned += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            log.debug("hl cüzdan %s okunamadı: %s", addr[:10], e)
            continue
        for p in positions:
            c = per_coin.setdefault(p["symbol"], {
                "symbol": p["symbol"], "long_usd": 0.0, "short_usd": 0.0,
                "wallets": 0, "pnl_usd": 0.0})
            if p["side"] == "LONG":
                c["long_usd"] += p["notional_usd"]
            else:
                c["short_usd"] += p["notional_usd"]
            c["wallets"] += 1
            c["pnl_usd"] += p["unrealized_pnl"]
        _ = pnl
    rows = []
    for c in per_coin.values():
        tot = c["long_usd"] + c["short_usd"]
        if tot <= 0:
            continue
        rows.append({
            "symbol": c["symbol"],
            "long_usd": round(c["long_usd"], 0), "short_usd": round(c["short_usd"], 0),
            "net_usd": round(c["long_usd"] - c["short_usd"], 0),
            "long_pct": round(c["long_usd"] / tot * 100, 1),
            "wallets": c["wallets"], "unrealized_pnl": round(c["pnl_usd"], 0),
        })
    rows.sort(key=lambda r: -abs(r["net_usd"]))
    net = sum(r["net_usd"] for r in rows)
    gross = sum(r["long_usd"] + r["short_usd"] for r in rows) or 1.0
    score = round(max(-1.0, min(1.0, net / gross)), 3)
    return {"ok": bool(rows), "label": label, "rows": rows[:15],
            "net_usd": round(net, 0), "gross_usd": round(gross, 0),
            "score": score, "wallets_scanned": scanned, "wallets_failed": failed,
            "bias": ("LONG eğilimi" if score > 0.15 else
                     "SHORT eğilimi" if score < -0.15 else "dengeli")}


def winner_positions() -> dict:
    """Günlük PnL sıralamasının tepesindeki cüzdanların net yönü.

    Varsayılan KAPALI (bkz. `leaderboard_enabled`): açmak için .env'e
    HL_LEADERBOARD=1 ekleyin. Kapalıyken panel HL_WATCH_WALLETS'a yönlendirir.
    """
    if not leaderboard_enabled():
        return {"ok": False, "enabled": False, "rows": [],
                "reason": ("HL_LEADERBOARD=0 — genel PnL sıralaması ~35 MB "
                           "indirdiği için kapalı. Açmak için .env'e "
                           "HL_LEADERBOARD=1 ekleyin ya da HL_WATCH_WALLETS "
                           "ile kendi izlediğiniz cüzdanları kullanın.")}

    def _build() -> dict:
        try:
            wallets = _leaderboard_addresses("day")
        except Exception as e:  # noqa: BLE001
            log.warning("hl leaderboard alınamadı: %s", e)
            return {"ok": False, "enabled": True, "reason": str(e)[:140], "rows": []}
        if not wallets:
            return {"ok": False, "enabled": True, "reason": "leaderboard boş",
                    "rows": []}
        res = _aggregate(wallets, "Kazananlar (24s PnL)")
        res["enabled"] = True
        return res
    return cached("hl:winners", 3600, _build)


def watchlist() -> dict:
    """.env HL_WATCH_WALLETS ile takip edilen cüzdanların pozisyonları."""
    addrs = keys.hl_wallets()
    if not addrs:
        return {"ok": False, "enabled": False,
                "reason": "HL_WATCH_WALLETS tanımlı değil", "rows": []}

    def _build() -> dict:
        res = _aggregate([(a, 1e12, 0.0) for a in addrs], "İzleme listesi")
        res["enabled"] = True
        return res
    return cached("hl:watchlist:" + ",".join(addrs)[:64], 300, _build)


def radar() -> dict:
    """Hyperliquid paneli — duyarlılık + kazanan yönü + izleme listesi."""
    out: dict = {}
    for name, fn in (("sentiment", sentiment), ("winners", winner_positions),
                     ("watchlist", watchlist)):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001
            log.warning("hl %s hata: %s", name, e)
            out[name] = {"ok": False, "reason": str(e)[:140]}
    s = out.get("sentiment") or {}
    w = out.get("winners") or {}
    parts = [x for x in (s.get("score") if s.get("ok") else None,
                         w.get("score") if w.get("ok") else None) if x is not None]
    out["bias"] = round(sum(parts) / len(parts), 3) if parts else 0.0
    # Panel seviyesinde tek bir "ok": duyarlilik calisiyorsa panel doludur.
    out["ok"] = bool(s.get("ok"))
    return out
