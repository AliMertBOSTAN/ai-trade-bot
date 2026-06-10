"""Uniswap V2 / PancakeSwap V2 / QuickSwap V2 fiyat okuyucu.

Fiyat ve likidite getReserves'ten hesaplanır (router'a bağımlı değiliz).
"""
from __future__ import annotations

import logging

from engine.config.chains import Chain, Dex, Token
from engine.dex.abis import V2_FACTORY_ABI, V2_PAIR_ABI
from engine.web3x.provider import get_web3, cs

log = logging.getLogger("dex.v2")
ZERO = "0x0000000000000000000000000000000000000000"


def get_v2_quote(chain: Chain, dex: Dex, base: Token) -> tuple[float, float] | None:
    """(price, liquidity_usd) döndürür. base/stable paritesi.

    price = 1 base kaç stable eder.
    liquidity_usd = havuzdaki stable tarafının 2 katı (toplam TVL yaklaşığı).
    """
    w3 = get_web3(chain.chain_id)
    if w3 is None:
        return None

    stable = chain.stable
    try:
        factory = w3.eth.contract(address=cs(dex.factory), abi=V2_FACTORY_ABI)
        pair_addr = factory.functions.getPair(cs(base.address), cs(stable.address)).call()
        if pair_addr == ZERO:
            return None  # bu DEX'te havuz yok

        pair = w3.eth.contract(address=cs(pair_addr), abi=V2_PAIR_ABI)
        r0, r1, _ = pair.functions.getReserves().call()
        token0 = pair.functions.token0().call().lower()

        if token0 == base.address.lower():
            base_reserve, stable_reserve = r0, r1
        else:
            base_reserve, stable_reserve = r1, r0

        base_amt = base_reserve / (10 ** base.decimals)
        stable_amt = stable_reserve / (10 ** stable.decimals)
        if base_amt == 0:
            return None

        price = stable_amt / base_amt
        liquidity_usd = stable_amt * 2.0  # constant-product => iki taraf eşit USD
        return price, liquidity_usd
    except Exception as e:  # RPC hatası vs - sessizce atla
        log.debug("v2 quote hata %s/%s/%s: %s", chain.name, dex.name, base.symbol, e)
        return None
