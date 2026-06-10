"""web3.py provider yöneticisi - zincir başına lazy Web3 instance.

BSC/Polygon gibi POA zincirleri için geth_poa_middleware enjekte edilir.
RPC tanımlı değilse ilgili zincir devre dışı sayılır.
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


@lru_cache(maxsize=None)
def get_web3(chain_id: int) -> Web3 | None:
    """Bir zincir için Web3 instance döndürür; RPC yoksa None."""
    url = settings.rpc.get(chain_id, "")
    if not url:
        log.warning("chain %s için RPC tanımlı değil - atlanıyor", chain_id)
        return None

    if url.startswith("ws"):
        w3 = Web3(Web3.WebsocketProvider(url, websocket_timeout=20))
    else:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))

    if chain_id in _POA_CHAINS:
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    return w3


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
