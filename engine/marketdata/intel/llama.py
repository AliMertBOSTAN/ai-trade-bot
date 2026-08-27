"""DefiLlama panelleri — zincir ücret/gelir, DEX hacmi, stablecoin, yield, unlock.

Tümü ücretsiz ve anahtarsız. NinjaTools'un `defillama-*` edge fonksiyonlarının
karşılığı; oradaki sayıların birebir aynı upstream'i.

Uçlar:
  overview/fees          → zincir & protokol ücretleri (24s/7g/30g)
  overview/dexs          → DEX spot hacmi
  overview/derivatives   → perp DEX hacmi
  v2/chains              → zincir TVL
  stablecoins            → stablecoin arzı (toplam + zincir kırılımı)
  stablecoincharts/all   → stablecoin arz geçmişi
  yields.llama.fi/pools  → DeFi getiri havuzları
  api.llama.fi/hacks     → hack/exploit geçmişi
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from engine.marketdata.http import get_json
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.llama")

API = "https://api.llama.fi"
STABLE = "https://stablecoins.llama.fi"
YIELDS = "https://yields.llama.fi"

_NO_CHART = "excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"


def _f(x, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# ------------------------------------------------------------ zincir ücretleri
# DefiLlama her protokol icin `breakdown24h` verir: {zincir: {alt-protokol: usd}}.
# Bu KESIN zincir dagilimidir; alan bos gelirse protokolun toplami zincirlerine
# esit bolunerek YAKLASIK dagitilir (panelde `approx` bayragi ile isaretlenir).
_SKIP_CHAINS = {"off chain", "offchain", "treasury"}


def _breakdown(protocols: list[dict], field: str) -> tuple[dict[str, float], bool]:
    """(zincir -> toplam, yaklasik_mi)."""
    out: dict[str, float] = {}
    approx = False
    bd_key = "breakdown24h" if field == "total24h" else "breakdown30d"
    for p in protocols:
        bd = p.get(bd_key)
        total = _f(p.get(field))
        if isinstance(bd, dict) and bd:
            for chain, val in bd.items():
                if chain.lower() in _SKIP_CHAINS:
                    continue
                if isinstance(val, dict):
                    v = sum(_f(x) for x in val.values())
                else:
                    v = _f(val)
                if v:
                    out[chain] = out.get(chain, 0.0) + v
        elif total:
            chains = [c for c in (p.get("chains") or [])
                      if c.lower() not in _SKIP_CHAINS]
            if not chains:
                continue
            approx = True
            for c in chains:
                out[c] = out.get(c, 0.0) + total / len(chains)
    return out, approx


def _pretty_chain(name: str) -> str:
    """DefiLlama breakdown anahtarlari kucuk harf gelir: 'ethereum' -> 'Ethereum'."""
    special = {"bsc": "BSC", "bnb": "BNB", "ton": "TON", "xdai": "xDai",
               "avax": "Avalanche", "op mainnet": "Optimism"}
    n = (name or "").strip()
    return special.get(n.lower(), n if n[:1].isupper() else n.title())


def chain_fees() -> dict:
    """Zincir bazinda 24s/30g ucret + DEX hacmi + en cok kazanan protokoller."""
    def _build() -> dict:
        def _overview(kind: str) -> list[dict]:
            d = get_json(f"{API}/overview/{kind}?{_NO_CHART}", ttl=900, timeout=30)
            return d.get("protocols") or []

        try:
            fees = _overview("fees")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120], "rows": []}
        try:
            dexs = _overview("dexs")
        except Exception:  # noqa: BLE001
            dexs = []
        try:
            chains = get_json(f"{API}/v2/chains", ttl=900)
        except Exception:  # noqa: BLE001
            chains = []
        tvl_by = {(c.get("name") or "").lower(): _f(c.get("tvl"))
                  for c in chains if c.get("name")}

        fee24, approx_a = _breakdown(fees, "total24h")
        fee30, approx_b = _breakdown(fees, "total30d")
        dex24, _ = _breakdown(dexs, "total24h")

        names = sorted(set(fee24) | set(dex24), key=lambda n: -fee24.get(n, 0.0))
        rows = []
        for n in names[:14]:
            f24 = fee24.get(n, 0.0)
            f30 = fee30.get(n, 0.0)
            daily30 = f30 / 30 if f30 > 0 else 0.0
            rows.append({
                "chain": _pretty_chain(n),
                "fees_24h": round(f24, 2),
                "fees_30d": round(f30, 2),
                "fees_change_pct": round((f24 - daily30) / daily30 * 100, 1)
                if daily30 > 0 else None,
                "dex_volume_24h": round(dex24.get(n, 0.0), 2),
                "tvl": round(tvl_by.get(n.lower(), 0.0), 2),
            })
        top_protocols = sorted(
            [{"name": p.get("name"), "fees_24h": round(_f(p.get("total24h")), 2),
              "chains": (p.get("chains") or [])[:3]} for p in fees],
            key=lambda r: -r["fees_24h"])[:10]
        total24 = sum(r["fees_24h"] for r in rows)
        leader = max(rows, key=lambda r: r["fees_24h"]) if rows else None
        return {"ok": bool(rows), "rows": rows, "protocols": top_protocols,
                "total_24h": round(total24, 2),
                "total_30d": round(sum(r["fees_30d"] for r in rows), 2),
                "approx": approx_a or approx_b,
                "leader": leader["chain"] if leader else None,
                "leader_fees": leader["fees_24h"] if leader else None}
    return cached("llama:chain_fees", 900, _build)


def dex_volumes() -> dict:
    """DEX hacim liderleri (spot). DefiLlama perp ucu artik ucretli oldugu icin
    perp tarafi Hyperliquid panelinden okunur."""
    def _build() -> dict:
        d = get_json(f"{API}/overview/dexs?{_NO_CHART}", ttl=900, timeout=30)
        rows = []
        for p in (d.get("protocols") or []):
            v = _f(p.get("total24h"))
            if v <= 0:
                continue
            rows.append({"name": p.get("name"), "volume_24h": round(v, 2),
                         "volume_7d": round(_f(p.get("total7d")), 2),
                         "change_1d": p.get("change_1d"),
                         "chains": (p.get("chains") or [])[:3]})
        rows.sort(key=lambda r: -r["volume_24h"])
        return {"ok": bool(rows), "rows": rows[:15],
                "total_24h": round(_f(d.get("total24h")), 2)}
    return cached("llama:dex_volumes", 900, _build)


# ------------------------------------------------------------------ stablecoin
def stablecoins() -> dict:
    """Stablecoin arzı: toplam, ilk 8 varlık, zincir kırılımı, 30g değişim.

    Arz artışı = piyasaya taze likidite girişi (yapısal boğa yakıtı);
    daralma = likidite çekilmesi.
    """
    def _build() -> dict:
        try:
            d = get_json(f"{STABLE}/stablecoins?includePrices=true", ttl=1800)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120], "assets": []}
        assets = []
        for s in (d.get("peggedAssets") or []):
            cur = (s.get("circulating") or {})
            prev_d = (s.get("circulatingPrevDay") or {})
            prev_w = (s.get("circulatingPrevWeek") or {})
            prev_m = (s.get("circulatingPrevMonth") or {})
            v = _f(cur.get("peggedUSD"))
            if v <= 0:
                continue
            assets.append({
                "symbol": s.get("symbol"), "name": s.get("name"),
                "supply": round(v, 0),
                "change_1d": round(v - _f(prev_d.get("peggedUSD"), v), 0),
                "change_7d": round(v - _f(prev_w.get("peggedUSD"), v), 0),
                "change_30d": round(v - _f(prev_m.get("peggedUSD"), v), 0),
                "price": s.get("price"),
            })
        assets.sort(key=lambda a: -a["supply"])
        total = sum(a["supply"] for a in assets)
        d30 = sum(a["change_30d"] for a in assets)
        d7 = sum(a["change_7d"] for a in assets)

        series: list[dict] = []
        try:
            ch = get_json(f"{STABLE}/stablecoincharts/all", ttl=3600)
            for r in ch[-120:]:
                series.append({"t": int(_f(r.get("date"))) * 1000,
                               "supply": round(_f((r.get("totalCirculatingUSD") or {})
                                                  .get("peggedUSD")), 0)})
        except Exception:  # noqa: BLE001
            pass

        bias = 0.0
        if total > 0:
            pct30 = d30 / total * 100
            bias = max(-1.0, min(1.0, pct30 / 2.0))  # ±%2/30g -> ±1
        return {"ok": bool(assets), "total_supply": round(total, 0),
                "change_7d": round(d7, 0), "change_30d": round(d30, 0),
                "change_30d_pct": round(d30 / total * 100, 2) if total else None,
                "assets": assets[:8], "series": series, "bias": round(bias, 3),
                "note": ("arz genişliyor — taze likidite" if d30 > 0 else
                         "arz daralıyor — likidite çekiliyor")}
    return cached("llama:stables", 1800, _build)


def stablecoin_chains() -> dict:
    """Stablecoin arzının zincir kırılımı (likidite nerede duruyor)."""
    def _build() -> dict:
        d = get_json(f"{STABLE}/stablecoinchains", ttl=1800)
        rows = []
        for c in d if isinstance(d, list) else []:
            v = _f((c.get("totalCirculatingUSD") or {}).get("peggedUSD"))
            prev = _f((c.get("totalCirculatingUSDPrevWeek") or {}).get("peggedUSD"), v)
            if v <= 0:
                continue
            rows.append({"chain": c.get("name"), "supply": round(v, 0),
                         "change_7d": round(v - prev, 0),
                         "change_7d_pct": round((v - prev) / prev * 100, 2) if prev else None})
        rows.sort(key=lambda r: -r["supply"])
        return {"ok": bool(rows), "rows": rows[:12]}
    return cached("llama:stable_chains", 1800, _build)


# ---------------------------------------------------------------------- yield
def yields(min_tvl: float = 5_000_000, limit: int = 25) -> dict:
    """DeFi getiri havuzları — TVL filtreli, APY'ye göre sıralı."""
    def _build() -> dict:
        d = get_json(f"{YIELDS}/pools", ttl=1800)
        rows = []
        for p in (d.get("data") or []):
            tvl = _f(p.get("tvlUsd"))
            apy = _f(p.get("apy"))
            if tvl < min_tvl or apy <= 0 or apy > 500:
                continue
            rows.append({
                "project": p.get("project"), "chain": p.get("chain"),
                "symbol": p.get("symbol"), "tvl": round(tvl, 0),
                "apy": round(apy, 2), "apy_base": p.get("apyBase"),
                "apy_reward": p.get("apyReward"),
                "stablecoin": bool(p.get("stablecoin")),
                "il_risk": p.get("ilRisk"), "exposure": p.get("exposure"),
                "prediction": (p.get("predictions") or {}).get("predictedClass"),
            })
        rows.sort(key=lambda r: -r["apy"])
        stables = [r for r in rows if r["stablecoin"]][:limit]
        return {"ok": bool(rows), "rows": rows[:limit], "stable_rows": stables,
                "count": len(rows)}
    return cached("llama:yields", 1800, _build)


# -------------------------------------------------------------------- unlocks
# DefiLlama'nin toplu /emissions ucu artik ucretli (HTTP 402). Ucretsiz yol:
#   1) defillama-datasets.llama.fi/emissionsProtocolsList  -> protokol slug listesi
#   2) defillama-datasets.llama.fi/emissions/{slug}        -> metadata.events
# Dosyalar ~1-2 MB oldugundan TAMAMI cekilmez: CoinGecko ilk 250 coin ile
# kesisen, en fazla _UNLOCK_MAX protokol paralel indirilir ve 6 saat cache'lenir.
DATASETS = "https://defillama-datasets.llama.fi"
_UNLOCK_MAX = 25


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _unlock_candidates() -> list[tuple[str, str, float, float]]:
    """(slug, sembol, fiyat, mcap) — piyasa degeri buyuk + emisyon verisi olanlar."""
    try:
        avail = set(get_json(f"{DATASETS}/emissionsProtocolsList", ttl=86_400))
    except Exception as e:  # noqa: BLE001
        log.warning("emisyon protokol listesi alinamadi: %s", e)
        return []
    try:
        markets = get_json(
            "https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=market_cap_desc&per_page=250&page=1", ttl=3600)
    except Exception as e:  # noqa: BLE001
        log.warning("coingecko piyasa listesi alinamadi: %s", e)
        return []
    out: list[tuple[str, str, float, float]] = []
    seen: set[str] = set()
    for c in markets if isinstance(markets, list) else []:
        for cand in (_slugify(c.get("id") or ""), _slugify(c.get("name") or "")):
            if cand and cand in avail and cand not in seen:
                seen.add(cand)
                out.append((cand, (c.get("symbol") or "").upper(),
                            _f(c.get("current_price")), _f(c.get("market_cap"))))
                break
        if len(out) >= _UNLOCK_MAX:
            break
    return out


def _protocol_unlocks(item: tuple[str, str, float, float],
                      now: float, horizon: float) -> list[dict]:
    slug, symbol, price, mcap = item
    try:
        d = get_json(f"{DATASETS}/emissions/{slug}", ttl=21_600, timeout=25)
    except Exception as e:  # noqa: BLE001
        log.debug("emisyon %s alinamadi: %s", slug, e)
        return []
    rows = []
    for e in ((d.get("metadata") or {}).get("events") or []):
        ts = _f(e.get("timestamp"))
        if ts <= 0 or not (now <= ts <= horizon):
            continue
        toks = e.get("noOfTokens")
        n = sum(_f(x) for x in toks) if isinstance(toks, list) else _f(toks)
        usd = n * price
        if usd <= 0:
            continue
        rows.append({
            "name": d.get("name") or slug, "symbol": symbol,
            "t": int(ts * 1000), "tokens": round(n, 2),
            "value_usd": round(usd, 0), "mcap": round(mcap, 0),
            "pct_of_mcap": round(usd / mcap * 100, 2) if mcap > 0 else None,
            "category": (e.get("category") or "")[:40],
            "unlock_type": e.get("unlockType"),
        })
    return rows


def unlocks(days: int = 45) -> dict:
    """Yaklasan token unlock'lari (arz soku takvimi) — ucretsiz kaynaklardan."""
    def _build() -> dict:
        cands = _unlock_candidates()
        if not cands:
            return {"ok": False, "rows": [], "significant": [],
                    "reason": "emisyon/piyasa listesi alinamadi", "window_days": days}
        now = time.time()
        horizon = now + days * 86400
        rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            for part in ex.map(lambda it: _protocol_unlocks(it, now, horizon), cands):
                rows.extend(part)
        rows.sort(key=lambda r: r["t"])
        big = sorted([r for r in rows if (r["pct_of_mcap"] or 0) >= 0.5],
                     key=lambda r: -(r["pct_of_mcap"] or 0))[:10]
        return {"ok": bool(rows), "rows": rows[:30], "significant": big,
                "total_usd": round(sum(r["value_usd"] for r in rows), 0),
                "scanned": len(cands), "window_days": days}
    return cached("llama:unlocks", 21_600, _build)


def hacks(limit: int = 10) -> dict:
    """Son hack/exploit olayları (risk radarı)."""
    def _build() -> dict:
        d = get_json(f"{API}/hacks", ttl=3600)
        rows = sorted(d if isinstance(d, list) else [],
                      key=lambda r: -_f(r.get("date")))[:limit]
        return {"ok": bool(rows), "rows": [{
            "name": r.get("name"), "t": int(_f(r.get("date")) * 1000),
            "amount_usd": round(_f(r.get("amount")) * 1_000_000, 0),
            "chain": (r.get("chain") or [None])[0] if isinstance(r.get("chain"), list)
            else r.get("chain"),
            "technique": r.get("technique"), "classification": r.get("classification"),
        } for r in rows]}
    return cached("llama:hacks", 3600, _build)
