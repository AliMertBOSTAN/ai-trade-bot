"""Uniswap V3 / PancakeSwap V3 fiyat okuyucu (QuoterV2 staticcall).

QuoterV2.quoteExactInputSingle 'nonpayable' tanımlıdır ama view gibi
.call() ile çağrılır (state değiştirmez). Birden çok fee tier denenir;
en derin (en çok çıktı veren) havuz seçilir. Likidite, küçük vs büyük
miktar arasındaki fiyat etkisinden (price impact) tahmin edilir.
"""
from __future__ import annotations

import logging

from engine.config.chains import Chain, Dex, Token
from engine.dex.abis import V3_QUOTER_V2_ABI
from engine.web3x.provider import get_web3, cs

log = logging.getLogger("dex.v3")


def _quote_single(quoter, token_in: str, token_out: str, amount_in: int, fee: int):
    params = (cs(token_in), cs(token_out), amount_in, fee, 0)
    return quoter.functions.quoteExactInputSingle(params).call()


def get_v3_quote(chain: Chain, dex: Dex, base: Token) -> tuple[float, float] | None:
    w3 = get_web3(chain.chain_id)
    if w3 is None or not dex.quoter:
        return None

    stable = chain.stable
    quoter = w3.eth.contract(address=cs(dex.quoter), abi=V3_QUOTER_V2_ABI)

    one_base = 10 ** base.decimals
    big_base = one_base * 10  # price impact ölçmek için 10x

    best: tuple[float, float] | None = None
    for fee in dex.fee_tiers:
        try:
            out_small = _quote_single(quoter, base.address, stable.address, one_base, fee)[0]
            if out_small == 0:
                continue
            price = out_small / (10 ** stable.decimals)

            # büyük miktarla price impact -> likidite derinliği tahmini
            try:
                out_big = _quote_single(quoter, base.address, stable.address, big_base, fee)[0]
                price_big = (out_big / (10 ** stable.decimals)) / 10.0
                impact = max(1e-9, (price - price_big) / price)  # 10x için kayma
                # impact küçükse havuz derin: kaba TVL ~ trade / impact
                liquidity_usd = (price * 10) / impact
            except Exception:
                liquidity_usd = price * 10_000  # fallback

            if best is None or liquidity_usd > best[1]:
                best = (price, liquidity_usd)
        except Exception as e:
            log.debug("v3 quote hata %s/%s/%s fee=%s: %s",
                      chain.name, dex.name, base.symbol, fee, e)
            continue

    return best
