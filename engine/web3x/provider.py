"""web3.py provider yöneticisi — zincir başına lazy + FAILOVER'lı Web3 instance.

Dayanıklılık:
  • Her zincir için birden çok RPC denenir (env'de virgülle ayrılmış URL'ler +
    yerleşik anahtar-gerektirmeyen public yedekler). İlk BAĞLANAN kullanılır.
  • Hiçbiri yanıt vermezse zincir devre dışı (None) — sessiz değil, log'lanır.
BSC/Polygon gibi POA zincirleri için geth_poa_middleware enjekte edilir.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from web3 import Web3
from web3.middleware import geth_poa_middleware

from engine.config.settings import settings

log = logging.getLogger("web3x")

# POA middleware gerektiren zincirler
_POA_CHAINS = {56, 137}

# Anahtar gerektirmeyen public yedek RPC'ler (env boşsa/çalışmazsa son çare).
# Birincil RPC her zaman .env'den gelir; bunlar yalnızca fail-over içindir.
_PUBLIC_FALLBACKS: dict[int, list[str]] = {
    1: ["https://eth.llamarpc.com", "https://rpc.ankr.com/eth", "https://cloudflare-eth.com"],
    42161: ["https://arb1.arbitrum.io/rpc", "https://rpc.ankr.com/arbitrum"],
    8453: ["https://mainnet.base.org", "https://base.llamarpc.com"],
    10: ["https://mainnet.optimism.io", "https://rpc.ankr.com/optimism"],
    56: ["https://bsc-dataseed.binance.org", "https://rpc.ankr.com/bsc"],
    137: ["https://polygon-rpc.com", "https://rpc.ankr.com/polygon"],
}


def _candidate_urls(chain_id: int) -> list[str]:
    """Bu zincir için denenecek RPC URL'leri (öncelik sırasına göre, tekilleştirilmiş).

    1) .env'deki RPC (virgülle birden çok yazılabilir) — birincil
    2) yerleşik public yedekler — son çare
    """
    raw = settings.rpc.get(chain_id, "") or ""
    env_urls = [u.strip() for u in raw.split(",") if u.strip()]
    out: list[str] = []
    for u in env_urls + _PUBLIC_FALLBACKS.get(chain_id, []):
        if u not in out:
            out.append(u)
    return out


def _make_w3(url: str, chain_id: int) -> Web3:
    if url.startswith("ws"):
        w3 = Web3(Web3.WebsocketProvider(url, websocket_timeout=20))
    else:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
    if chain_id in _POA_CHAINS:
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return w3


@lru_cache(maxsize=None)
def get_web3(chain_id: int) -> Web3 | None:
    """Bir zincir için BAĞLANAN ilk Web3 instance'ı döndürür; hiçbiri yoksa None."""
    urls = _candidate_urls(chain_id)
    if not urls:
        log.warning("chain %s için RPC tanımlı değil ve public yedek yok - atlanıyor", chain_id)
        return None

    for i, url in enumerate(urls):
        try:
            w3 = _make_w3(url, chain_id)
            if w3.is_connected():
                if i > 0:
                    log.warning("chain %s: birincil RPC başarısız, yedeğe geçildi (%s)",
                                chain_id, url)
                return w3
        except Exception as e:  # noqa: BLE001
            log.warning("chain %s RPC denemesi başarısız (%s): %s", chain_id, url, e)
            continue

    log.error("chain %s: hiçbir RPC bağlanamadı (%d denendi) - zincir devre dışı",
              chain_id, len(urls))
    return None


def reset_provider_cache() -> None:
    """Bağlantı koptuğunda yeniden seçim için cache'i temizle (failover yeniden çalışır)."""
    get_web3.cache_clear()


def is_chain_available(chain_id: int) -> bool:
    w3 = get_web3(chain_id)
    if w3 is None:
        return False
    try:
        return w3.is_connected()
    except Exception:
        return False


def cs(addr: str) -> str:
    """Checksum'a normalize et."""
    return Web3.to_checksum_address(addr)
