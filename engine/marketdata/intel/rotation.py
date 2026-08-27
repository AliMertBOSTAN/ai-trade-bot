"""Sektör & zincir rotasyonu — para hangi anlatıdan hangisine akıyor?

Kaynaklar:
  • CoinGecko /coins/categories  (anahtarsız) — sektör piyasa değeri + 24s değişim
  • DefiLlama /v2/chains + overview/fees — zincir TVL ve ücret momentumu
  • CoinMarketCap (opsiyonel, CMC_API_KEY) — global metrikler + dominans

"Rotasyon kenarı" (X → Y): X'ten çıkan, Y'ye giren göreli sermaye. Dominans
değişimlerinin eşleştirilmesiyle türetilir; NinjaTools'taki "Sektör Rotasyonu"
panelinin mantığı.
"""
from __future__ import annotations

import logging

from engine.marketdata.http import get_json
from engine.marketdata.intel import cmc as cmc_mod
from engine.marketdata.intel.cache import cached

log = logging.getLogger("intel.rotation")

CG = "https://api.coingecko.com/api/v3"
LLAMA = "https://api.llama.fi"

# Gürültü sektörleri: çok geniş / tekrarlı kategoriler panelde işe yaramaz.
_SKIP = {"smart-contract-platform", "cryptocurrency", "ethereum-ecosystem",
         "binance-smart-chain", "solana-ecosystem", "polygon-ecosystem",
         "arbitrum-ecosystem", "base-ecosystem", "avalanche-ecosystem",
         "optimism-ecosystem", "bnb-chain-ecosystem", "coinbase-ventures-portfolio",
         "andreessen-horowitz-a16z-portfolio", "multicoin-capital-portfolio",
         "paradigm-portfolio", "polychain-capital-portfolio"}


def _f(x, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def sectors(top: int = 12) -> dict:
    """Sektör rotasyonu: piyasa değeri, 24s değişim, tahmini net akış."""
    def _build() -> dict:
        try:
            cats = get_json(f"{CG}/coins/categories?order=market_cap_desc", ttl=900)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120], "rows": []}
        rows = []
        for c in cats if isinstance(cats, list) else []:
            cid = c.get("id") or ""
            mcap = _f(c.get("market_cap"))
            chg = c.get("market_cap_change_24h")
            if cid in _SKIP or mcap <= 0 or chg is None:
                continue
            chg = _f(chg)
            # 24s'te değişen piyasa değeri ≈ net akış (fiyat etkisi dahil).
            prev = mcap / (1 + chg / 100) if chg != -100 else mcap
            rows.append({
                "sector": c.get("name"), "id": cid,
                "market_cap": round(mcap, 0),
                "change_24h_pct": round(chg, 2),
                "net_flow_usd": round(mcap - prev, 0),
                "volume_24h": round(_f(c.get("volume_24h")), 0),
                # top_3_coins_id: id (str) listesi; top_3_coins: resim url listesi
                "top": [str(x).upper() for x in (c.get("top_3_coins_id") or [])][:3],
            })
        rows.sort(key=lambda r: -abs(r["net_flow_usd"]))
        rows = rows[:top]
        total_mcap = sum(r["market_cap"] for r in rows) or 1.0

        # Dominans kayması: her sektörün toplam içindeki payının 24s değişimi (bp)
        for r in rows:
            prev_mc = r["market_cap"] - r["net_flow_usd"]
            prev_total = total_mcap - sum(x["net_flow_usd"] for x in rows)
            now_share = r["market_cap"] / total_mcap
            prev_share = (prev_mc / prev_total) if prev_total > 0 else now_share
            r["dominance_bp"] = round((now_share - prev_share) * 10_000, 1)

        gainers = sorted([r for r in rows if r["net_flow_usd"] > 0],
                         key=lambda r: -r["net_flow_usd"])[:3]
        losers = sorted([r for r in rows if r["net_flow_usd"] < 0],
                        key=lambda r: r["net_flow_usd"])[:3]
        edges = []
        for src in losers:
            for dst in gainers:
                edges.append({
                    "from": src["sector"], "to": dst["sector"],
                    "flow_usd": round(min(abs(src["net_flow_usd"]),
                                          dst["net_flow_usd"]), 0),
                })
        edges.sort(key=lambda e: -e["flow_usd"])
        return {"ok": bool(rows), "rows": rows, "inflow": gainers,
                "outflow": losers, "edges": edges[:5]}
    return cached("rotation:sectors", 900, _build)


def chains(top: int = 12) -> dict:
    """Zincir rotasyonu: TVL, 1g/7g TVL değişimi, ücret momentumu."""
    def _build() -> dict:
        try:
            data = get_json(f"{LLAMA}/v2/chains", ttl=900)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120], "rows": []}
        rows = []
        for c in data if isinstance(data, list) else []:
            tvl = _f(c.get("tvl"))
            if tvl <= 0:
                continue
            rows.append({"chain": c.get("name"), "tvl": round(tvl, 0),
                         "symbol": c.get("tokenSymbol")})
        rows.sort(key=lambda r: -r["tvl"])
        rows = rows[:top]
        total = sum(r["tvl"] for r in rows) or 1.0
        for r in rows:
            r["share_pct"] = round(r["tvl"] / total * 100, 2)
        return {"ok": bool(rows), "rows": rows, "total_tvl": round(total, 0)}
    return cached("rotation:chains", 900, _build)


def dominance() -> dict:
    """BTC/ETH/stablecoin dominansı — CMC anahtarı varsa oradan, yoksa CoinGecko."""
    def _build() -> dict:
        if cmc_mod.enabled():
            g = cmc_mod.global_metrics()
            if g.get("ok"):
                return g
        try:
            d = get_json(f"{CG}/global", ttl=900).get("data") or {}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:120]}
        mc = d.get("market_cap_percentage") or {}
        return {"ok": True, "source": "coingecko",
                "btc_dominance": round(_f(mc.get("btc")), 2),
                "eth_dominance": round(_f(mc.get("eth")), 2),
                "stable_dominance": round(_f(mc.get("usdt")) + _f(mc.get("usdc")), 2),
                "total_market_cap_usd": round(
                    _f((d.get("total_market_cap") or {}).get("usd")), 0),
                "total_volume_usd": round(
                    _f((d.get("total_volume") or {}).get("usd")), 0),
                "mcap_change_24h": d.get("market_cap_change_percentage_24h_usd")}
    return cached("rotation:dominance", 900, _build)
