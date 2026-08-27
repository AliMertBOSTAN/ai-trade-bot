"""Piyasa istihbaratı (intel) katmanı — makro, on-chain akış, Hyperliquid, whale.

Bu paket botun İŞLEM mantığından bağımsızdır: dış kaynaklardan panel verisi
toplar, TTL cache'ler ve iki tüketiciye sunar:

  • REST  → `engine/api/intel.py` (/intel/*) → Electron "Piyasa İstihbaratı" sekmesi
  • SİNYAL → `bias.market_bias()` → `engine/signals/engine.py` güven modülasyonu

Tasarım kuralları:
  1. Hiçbir panel botu durdurmaz — her çağrı fail-safe, hata `ok=False` döner.
  2. Anahtarlı kaynaklar (CoinGlass/CMC/Nansen) opsiyoneldir; yoksa ücretsiz
     yedek veya açık "kapalı" durumu gösterilir.
  3. Sinyal katmanı ASLA ağ çağrısı yapmaz; yalnızca arka planda tazelenen
     cache'i okur (tick döngüsünün gecikmesini artırmamak için).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

# Sıra önemli: temel modüller (keys/cache) önce yüklenir ki alt modüller
# paket yarı-kuruluyken birbirini güvenle içe aktarabilsin.
from engine.marketdata.intel import keys, cache  # noqa: F401,I001
from engine.marketdata.intel import cmc, coinglass, nansen  # noqa: F401
from engine.marketdata.intel import (  # noqa: F401  (dışa açık paneller)
    bias, etf, flows, hl, llama, macro, rotation, premium, utxo,
)

log = logging.getLogger("intel")

__all__ = ["snapshot", "sources", "panel", "PANELS"]

# Panel adı -> (çağrılabilir, cache anahtarı ön eki, grup)
PANELS: dict[str, tuple] = {
    "fear_greed":      (macro.fear_greed,       "macro:fng",        "macro"),
    "indices":         (macro.indices,          "macro:indices",    "macro"),
    "risk_on_off":     (macro.risk_on_off,      "macro:riskonoff",  "macro"),
    "correlation":     (macro.correlation,      "macro:corr",       "macro"),
    "premium":         (premium.premium,        "premium",          "macro"),
    "etf":             (etf.summary,            "etf:bitcoin",      "macro"),
    "stablecoins":     (llama.stablecoins,      "llama:stables",    "onchain"),
    "stablecoin_chains": (llama.stablecoin_chains, "llama:stable_chains", "onchain"),
    "chain_fees":      (llama.chain_fees,       "llama:chain_fees", "onchain"),
    "dex_volumes":     (llama.dex_volumes,      "llama:dex_volumes", "onchain"),
    "yields":          (llama.yields,           "llama:yields",     "onchain"),
    "unlocks":         (llama.unlocks,          "llama:unlocks",    "onchain"),
    "hacks":           (llama.hacks,            "llama:hacks",      "onchain"),
    "sectors":         (rotation.sectors,       "rotation:sectors", "onchain"),
    "chains":          (rotation.chains,        "rotation:chains",  "onchain"),
    "dominance":       (rotation.dominance,     "rotation:dominance", "onchain"),
    "utxo":            (utxo.realized_price,    "utxo:realized",    "onchain"),
    "hyperliquid":     (hl.radar,               "hl:sentiment",     "hl"),
    "smart_money":     (flows.smart_money,      "flows:smartmoney", "hl"),
    "reserves":        (flows.exchange_reserves, "flows:reserves:BTC", "hl"),
}


def panel(name: str) -> dict:
    """Tek panel getir. Bilinmeyen ad -> ValueError; hata -> {"ok": False}."""
    entry = PANELS.get(name)
    if entry is None:
        raise ValueError(f"bilinmeyen panel: {name}")
    fn = entry[0]
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        log.warning("panel %s hata: %s", name, e)
        return {"ok": False, "error": str(e)[:160]}


def snapshot(group: str | None = None, workers: int = 8) -> dict:
    """Tüm panelleri (veya bir grubu) paralel topla.

    Her panel kendi TTL cache'ini kullandığından sıcak durumda bu çağrı
    neredeyse anlıktır; soğuk başlangıçta ~2-6 saniye sürer.
    """
    names = [n for n, e in PANELS.items() if group is None or e[2] == group]
    out: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(panel, n): n for n in names}
        for fut, name in futures.items():
            try:
                out[name] = fut.result(timeout=45)
            except Exception as e:  # noqa: BLE001
                out[name] = {"ok": False, "error": str(e)[:160]}
    cache.flush_disk(force=True)
    return out


def sources() -> dict:
    """Hangi kaynak açık, hangi panel ne kadar taze — UI durum çubuğu için."""
    ages = {}
    for name, (_fn, key, group) in PANELS.items():
        a = cache.age(key)
        ages[name] = {"group": group,
                      "age_s": round(a) if a is not None else None,
                      "cached": a is not None}
    return {
        "keys": keys.status(),
        "providers": {
            "binance": {"enabled": True, "key_required": False},
            "hyperliquid": {"enabled": True, "key_required": False},
            "defillama": {"enabled": True, "key_required": False},
            "coingecko": {"enabled": True, "key_required": False},
            "stooq": {"enabled": True, "key_required": False},
            "alternative_me": {"enabled": True, "key_required": False},
            "cnn": {"enabled": True, "key_required": False},
            "blockchain_info": {"enabled": True, "key_required": False},
            "coinbase": {"enabled": True, "key_required": False},
            "coinglass": {"enabled": coinglass.enabled(), "key_required": True,
                          "env": "COINGLASS_API_KEY"},
            "coinmarketcap": {"enabled": cmc.enabled(), "key_required": True,
                              "env": "CMC_API_KEY"},
            "nansen": {"enabled": nansen.enabled(), "key_required": True,
                       "env": "NANSEN_API_KEY"},
        },
        "panels": ages,
    }
