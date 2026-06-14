"""Zincir + DEX + token konfigürasyonu (Python tarafı).

TS tarafındaki src/core/config/chains.ts ile aynı adresleri taşır.
Adresler küçük harftir; web3.to_checksum_address ile normalize edilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Uniswap V3 çoğu zincirde aynı adreslerde deploy edilmiştir
UNIV3_FACTORY = "0x1f98431c8ad98523631ae4a59f267346ea31f984"
UNIV3_QUOTER_V2 = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"
UNIV3_ROUTER_02 = "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45"


@dataclass(frozen=True)
class Token:
    symbol: str
    address: str
    decimals: int


@dataclass(frozen=True)
class Dex:
    name: str
    protocol: str  # "uniswap-v2" | "uniswap-v3"
    factory: str
    router: str = ""
    quoter: str = ""
    fee_tiers: tuple[int, ...] = ()


@dataclass(frozen=True)
class Chain:
    chain_id: int
    name: str
    native_symbol: str
    block_explorer: str
    stable: Token
    wrapped_native: Token
    dexes: list[Dex]
    tokens: list[Token]


CHAINS: dict[int, Chain] = {
    1: Chain(
        chain_id=1, name="Ethereum", native_symbol="ETH",
        block_explorer="https://etherscan.io",
        stable=Token("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6),
        wrapped_native=Token("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18),
        dexes=[
            Dex("Uniswap V2", "uniswap-v2",
                "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f",
                router="0x7a250d5630b4cf539739df2c5dacb4c659f2488d"),
            Dex("Uniswap V3", "uniswap-v3", UNIV3_FACTORY,
                router=UNIV3_ROUTER_02, quoter=UNIV3_QUOTER_V2,
                fee_tiers=(500, 3000, 10000)),
            # --- ek DEX'ler (intra-chain arbitraj yüzeyini genişletir) ---
            Dex("SushiSwap V2", "uniswap-v2",
                "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac",
                router="0xd9e1ce17f2641f24ae83637ab66a2cce9ae25f30"),
            Dex("PancakeSwap V2", "uniswap-v2",
                "0x1097053fd2ea711dad45caccc45eff7548fcb362",
                router="0xeff92a263d31888d860bd50809a8d171709b7b1c"),
            Dex("PancakeSwap V3", "uniswap-v3",
                "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                router="0x1b81d678ffb9c0263b24a97847620c99d213eb14",
                quoter="0xb048bbc1ee6b733fffcfb9e9cef7375518e25997",
                fee_tiers=(100, 500, 2500, 10000)),
            Dex("ShibaSwap", "uniswap-v2",
                "0x115934131916c8b277dd010ee02de363c09d037c",
                router="0x03f7724180aa6b939894b5ca4314783b0b36b329"),
        ],
        tokens=[
            Token("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18),
            Token("WBTC", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", 8),
            Token("LINK", "0x514910771af9ca656af840dff83e8264ecf986ca", 18),
            Token("UNI", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984", 18),
        ],
    ),
    42161: Chain(
        chain_id=42161, name="Arbitrum", native_symbol="ETH",
        block_explorer="https://arbiscan.io",
        stable=Token("USDC", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", 6),
        wrapped_native=Token("WETH", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", 18),
        dexes=[
            Dex("Uniswap V3", "uniswap-v3", UNIV3_FACTORY,
                router=UNIV3_ROUTER_02, quoter=UNIV3_QUOTER_V2,
                fee_tiers=(500, 3000, 10000)),
        ],
        tokens=[
            Token("WETH", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", 18),
            Token("WBTC", "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f", 8),
            Token("ARB", "0x912ce59144191c1204e64559fe8253a0e49e6548", 18),
            Token("GMX", "0xfc5a1a6eb076a2c7ad06ed22c90d7e710e35ad0a", 18),
        ],
    ),
    8453: Chain(
        chain_id=8453, name="Base", native_symbol="ETH",
        block_explorer="https://basescan.org",
        stable=Token("USDC", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", 6),
        wrapped_native=Token("WETH", "0x4200000000000000000000000000000000000006", 18),
        dexes=[
            Dex("Uniswap V3", "uniswap-v3",
                "0x33128a8fc17869897dce68ed026d694621f6fdfd",
                router="0x2626664c2603336e57b271c5c0b26f421741e481",
                quoter="0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
                fee_tiers=(500, 3000, 10000)),
        ],
        tokens=[
            Token("WETH", "0x4200000000000000000000000000000000000006", 18),
            Token("cbBTC", "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf", 8),
            Token("DEGEN", "0x4ed4e862860bed51a9570b96d89af5e1b0efefed", 18),
        ],
    ),
    10: Chain(
        chain_id=10, name="Optimism", native_symbol="ETH",
        block_explorer="https://optimistic.etherscan.io",
        stable=Token("USDC", "0x0b2c639c533813f4aa9d7837caf62653d097ff85", 6),
        wrapped_native=Token("WETH", "0x4200000000000000000000000000000000000006", 18),
        dexes=[
            Dex("Uniswap V3", "uniswap-v3", UNIV3_FACTORY,
                router=UNIV3_ROUTER_02, quoter=UNIV3_QUOTER_V2,
                fee_tiers=(500, 3000, 10000)),
        ],
        tokens=[
            Token("WETH", "0x4200000000000000000000000000000000000006", 18),
            Token("OP", "0x4200000000000000000000000000000000000042", 18),
            Token("WBTC", "0x68f180fcce6836688e9084f035309e29bf0a2095", 8),
        ],
    ),
    56: Chain(
        chain_id=56, name="BNB Chain", native_symbol="BNB",
        block_explorer="https://bscscan.com",
        stable=Token("USDT", "0x55d398326f99059ff775485246999027b3197955", 18),
        wrapped_native=Token("WBNB", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", 18),
        dexes=[
            Dex("PancakeSwap V2", "uniswap-v2",
                "0xca143ce32fe78f1f7019d7d551a6402fc5350c73",
                router="0x10ed43c718714eb63d5aa57b78b54704e256024e"),
            Dex("PancakeSwap V3", "uniswap-v3",
                "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865",
                router="0x13f4ea83d0bd40e75c8222255bc855a974568dd4",
                quoter="0xb048bbc1ee6b733fffcfb9e9cef7375518e25997",
                fee_tiers=(500, 2500, 10000)),
            # --- ek DEX'ler (intra-chain arbitraj yüzeyini genişletir) ---
            Dex("Uniswap V3", "uniswap-v3",
                "0xdb1d10011ad0ff90774d0c6bb92e5c5c8b4461f7",
                router="0xb971ef87ede563556b2ed4b1c0b0019111dd85d2",
                quoter="0x78d78e420da98ad378d7799be8f4af69033eb077",
                fee_tiers=(100, 500, 3000, 10000)),
            Dex("SushiSwap V2", "uniswap-v2",
                "0xc35dadb65012ec5796536bd9864ed8773abc74c4",
                router="0x1b02da8cb0d097eb8d57a175b88c7d8b47997506"),
            Dex("Biswap", "uniswap-v2",
                "0x858e3312ed3a876947ea49d572a7c42de08af7ee",
                router="0x3a6d8ca21d1cf76f653a67577fa0d27453350dd8"),
            Dex("ApeSwap", "uniswap-v2",
                "0x0841bd0b734e4f5853f0dd8d7ea041c241fb0da6",
                router="0xcf0febd3f17cef5b47b0cd257acf6025c5bff3b7"),
        ],
        tokens=[
            Token("WBNB", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", 18),
            Token("ETH", "0x2170ed0880ac9a755fd29b2688956bd959f933f8", 18),
            Token("BTCB", "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c", 18),
            Token("CAKE", "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82", 18),
        ],
    ),
    137: Chain(
        chain_id=137, name="Polygon", native_symbol="MATIC",
        block_explorer="https://polygonscan.com",
        stable=Token("USDC", "0x2791bca1f2de4661ed88a30c99a7a9449aa84174", 6),
        wrapped_native=Token("WMATIC", "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270", 18),
        dexes=[
            Dex("QuickSwap V2", "uniswap-v2",
                "0x5757371414417b8c6caad45baef941abc7d3ab32",
                router="0xa5e0829caced8ffdd4de3c43696c57f7d7a678ff"),
            Dex("Uniswap V3", "uniswap-v3", UNIV3_FACTORY,
                router=UNIV3_ROUTER_02, quoter=UNIV3_QUOTER_V2,
                fee_tiers=(500, 3000, 10000)),
        ],
        tokens=[
            Token("WMATIC", "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270", 18),
            Token("WETH", "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619", 18),
            Token("WBTC", "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6", 8),
        ],
    ),
}

ALL_CHAIN_IDS = list(CHAINS.keys())


def get_chain(chain_id: int) -> Chain:
    if chain_id not in CHAINS:
        raise ValueError(f"Bilinmeyen chain_id: {chain_id}")
    return CHAINS[chain_id]
