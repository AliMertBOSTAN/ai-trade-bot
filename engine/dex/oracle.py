"""Fiyat oracle: tüm aktif zincir + DEX + token için PriceQuote üretir.

Her zincirdeki her DEX'ten her token'ın stable paritesini okur.
Çok sayıda RPC çağrısı içerdiğinden ThreadPool ile paralelleştirilir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.config.chains import CHAINS, Chain, Dex, Token
from engine.dex.uniswap_v2 import get_v2_quote
from engine.dex.uniswap_v3 import get_v3_quote
from engine.models import PriceQuote
from engine.web3x.provider import is_chain_available

log = logging.getLogger("oracle")


def _quote_one(chain: Chain, dex: Dex, token: Token) -> PriceQuote | None:
    if token.symbol == chain.stable.symbol:
        return None
    if dex.protocol == "uniswap-v2":
        res = get_v2_quote(chain, dex, token)
    else:
        res = get_v3_quote(chain, dex, token)
    if res is None:
        return None
    price, liq = res
    return PriceQuote(
        chain_id=chain.chain_id, dex=dex.name,
        base=token.symbol, quote=chain.stable.symbol,
        price=price, liquidity_usd=liq,
    )


def fetch_all_prices(enabled_chains: list[int] | None = None) -> list[PriceQuote]:
    chains = [c for cid, c in CHAINS.items()
              if (enabled_chains is None or cid in enabled_chains)
              and is_chain_available(cid)]

    jobs: list[tuple[Chain, Dex, Token]] = []
    for chain in chains:
        for dex in chain.dexes:
            for token in chain.tokens:
                jobs.append((chain, dex, token))

    quotes: list[PriceQuote] = []
    if not jobs:
        return quotes

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(_quote_one, c, d, t) for c, d, t in jobs]
        for fut in as_completed(futures):
            try:
                q = fut.result()
                if q is not None and q.price > 0:
                    quotes.append(q)
            except Exception as e:
                log.debug("quote future hata: %s", e)

    quotes.sort(key=lambda q: (q.base, q.chain_id, q.dex))
    return quotes
