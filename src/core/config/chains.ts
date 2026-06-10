import type { ChainConfig, ChainId } from '@shared/types'

// ============================================================
//  Zincir + DEX + token konfigürasyonu
//  Tüm adresler küçük harf saklanır; runtime'da ethers.getAddress
//  ile checksum'a çevrilir (bkz. providers/contracts.ts).
//  Adresler mainnet doğrulanmış kontratlardır - değiştirmeden önce
//  kontrol edin.
// ============================================================

// Uniswap V3 deployment'ları çoğu zincirde aynı adreste:
const UNIV3_FACTORY = '0x1f98431c8ad98523631ae4a59f267346ea31f984'
const UNIV3_QUOTER_V2 = '0x61ffe014ba17989e743c5f6cb21bf9697530b21e'
const UNIV3_ROUTER_02 = '0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45'

export const CHAINS: Record<ChainId, ChainConfig> = {
  // ---------------- Ethereum ----------------
  1: {
    chainId: 1,
    name: 'Ethereum',
    rpcEnvKey: 'RPC_ETHEREUM',
    nativeSymbol: 'ETH',
    blockExplorer: 'https://etherscan.io',
    stable: { symbol: 'USDC', address: '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', decimals: 6 },
    wrappedNative: { symbol: 'WETH', address: '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', decimals: 18 },
    dexes: [
      {
        name: 'Uniswap V2',
        protocol: 'uniswap-v2',
        factory: '0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f',
        router: '0x7a250d5630b4cf539739df2c5dacb4c659f2488d'
      },
      {
        name: 'Uniswap V3',
        protocol: 'uniswap-v3',
        factory: UNIV3_FACTORY,
        quoter: UNIV3_QUOTER_V2,
        router: UNIV3_ROUTER_02,
        feeTiers: [500, 3000, 10000]
      }
    ],
    tokens: [
      { symbol: 'WETH', address: '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2', decimals: 18 },
      { symbol: 'WBTC', address: '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599', decimals: 8 },
      { symbol: 'LINK', address: '0x514910771af9ca656af840dff83e8264ecf986ca', decimals: 18 },
      { symbol: 'UNI', address: '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984', decimals: 18 }
    ]
  },

  // ---------------- Arbitrum ----------------
  42161: {
    chainId: 42161,
    name: 'Arbitrum',
    rpcEnvKey: 'RPC_ARBITRUM',
    nativeSymbol: 'ETH',
    blockExplorer: 'https://arbiscan.io',
    stable: { symbol: 'USDC', address: '0xaf88d065e77c8cc2239327c5edb3a432268e5831', decimals: 6 },
    wrappedNative: { symbol: 'WETH', address: '0x82af49447d8a07e3bd95bd0d56f35241523fbab1', decimals: 18 },
    dexes: [
      {
        name: 'Uniswap V3',
        protocol: 'uniswap-v3',
        factory: UNIV3_FACTORY,
        quoter: UNIV3_QUOTER_V2,
        router: UNIV3_ROUTER_02,
        feeTiers: [500, 3000, 10000]
      }
    ],
    tokens: [
      { symbol: 'WETH', address: '0x82af49447d8a07e3bd95bd0d56f35241523fbab1', decimals: 18 },
      { symbol: 'WBTC', address: '0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f', decimals: 8 },
      { symbol: 'ARB', address: '0x912ce59144191c1204e64559fe8253a0e49e6548', decimals: 18 },
      { symbol: 'GMX', address: '0xfc5a1a6eb076a2c7ad06ed22c90d7e710e35ad0a', decimals: 18 }
    ]
  },

  // ---------------- Base ----------------
  8453: {
    chainId: 8453,
    name: 'Base',
    rpcEnvKey: 'RPC_BASE',
    nativeSymbol: 'ETH',
    blockExplorer: 'https://basescan.org',
    stable: { symbol: 'USDC', address: '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913', decimals: 6 },
    wrappedNative: { symbol: 'WETH', address: '0x4200000000000000000000000000000000000006', decimals: 18 },
    dexes: [
      {
        name: 'Uniswap V3',
        protocol: 'uniswap-v3',
        factory: '0x33128a8fc17869897dce68ed026d694621f6fdfd',
        quoter: '0x3d4e44eb1374240ce5f1b871ab261cd16335b76a',
        router: '0x2626664c2603336e57b271c5c0b26f421741e481',
        feeTiers: [500, 3000, 10000]
      }
    ],
    tokens: [
      { symbol: 'WETH', address: '0x4200000000000000000000000000000000000006', decimals: 18 },
      { symbol: 'cbBTC', address: '0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf', decimals: 8 },
      { symbol: 'DEGEN', address: '0x4ed4e862860bed51a9570b96d89af5e1b0efefed', decimals: 18 }
    ]
  },

  // ---------------- Optimism ----------------
  10: {
    chainId: 10,
    name: 'Optimism',
    rpcEnvKey: 'RPC_OPTIMISM',
    nativeSymbol: 'ETH',
    blockExplorer: 'https://optimistic.etherscan.io',
    stable: { symbol: 'USDC', address: '0x0b2c639c533813f4aa9d7837caf62653d097ff85', decimals: 6 },
    wrappedNative: { symbol: 'WETH', address: '0x4200000000000000000000000000000000000006', decimals: 18 },
    dexes: [
      {
        name: 'Uniswap V3',
        protocol: 'uniswap-v3',
        factory: UNIV3_FACTORY,
        quoter: UNIV3_QUOTER_V2,
        router: UNIV3_ROUTER_02,
        feeTiers: [500, 3000, 10000]
      }
    ],
    tokens: [
      { symbol: 'WETH', address: '0x4200000000000000000000000000000000000006', decimals: 18 },
      { symbol: 'OP', address: '0x4200000000000000000000000000000000000042', decimals: 18 },
      { symbol: 'WBTC', address: '0x68f180fcce6836688e9084f035309e29bf0a2095', decimals: 8 }
    ]
  },

  // ---------------- BSC (PancakeSwap) ----------------
  56: {
    chainId: 56,
    name: 'BNB Chain',
    rpcEnvKey: 'RPC_BSC',
    nativeSymbol: 'BNB',
    blockExplorer: 'https://bscscan.com',
    stable: { symbol: 'USDT', address: '0x55d398326f99059ff775485246999027b3197955', decimals: 18 },
    wrappedNative: { symbol: 'WBNB', address: '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c', decimals: 18 },
    dexes: [
      {
        name: 'PancakeSwap V2',
        protocol: 'uniswap-v2',
        factory: '0xca143ce32fe78f1f7019d7d551a6402fc5350c73',
        router: '0x10ed43c718714eb63d5aa57b78b54704e256024e'
      },
      {
        name: 'PancakeSwap V3',
        protocol: 'uniswap-v3',
        factory: '0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865',
        quoter: '0xb048bbc1ee6b733fffcfb9e9cef7375518e25997',
        router: '0x13f4ea83d0bd40e75c8222255bc855a974568dd4',
        feeTiers: [500, 2500, 10000]
      }
    ],
    tokens: [
      { symbol: 'WBNB', address: '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c', decimals: 18 },
      { symbol: 'ETH', address: '0x2170ed0880ac9a755fd29b2688956bd959f933f8', decimals: 18 },
      { symbol: 'BTCB', address: '0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c', decimals: 18 },
      { symbol: 'CAKE', address: '0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82', decimals: 18 }
    ]
  },

  // ---------------- Polygon (QuickSwap + Uniswap V3) ----------------
  137: {
    chainId: 137,
    name: 'Polygon',
    rpcEnvKey: 'RPC_POLYGON',
    nativeSymbol: 'MATIC',
    blockExplorer: 'https://polygonscan.com',
    stable: { symbol: 'USDC', address: '0x2791bca1f2de4661ed88a30c99a7a9449aa84174', decimals: 6 },
    wrappedNative: { symbol: 'WMATIC', address: '0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270', decimals: 18 },
    dexes: [
      {
        name: 'QuickSwap V2',
        protocol: 'uniswap-v2',
        factory: '0x5757371414417b8c6caad45baef941abc7d3ab32',
        router: '0xa5e0829caced8ffdd4de3c43696c57f7d7a678ff'
      },
      {
        name: 'Uniswap V3',
        protocol: 'uniswap-v3',
        factory: UNIV3_FACTORY,
        quoter: UNIV3_QUOTER_V2,
        router: UNIV3_ROUTER_02,
        feeTiers: [500, 3000, 10000]
      }
    ],
    tokens: [
      { symbol: 'WMATIC', address: '0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270', decimals: 18 },
      { symbol: 'WETH', address: '0x7ceb23fd6bc0add59e62ac25578270cff1b9f619', decimals: 18 },
      { symbol: 'WBTC', address: '0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6', decimals: 8 }
    ]
  }
}

export const ALL_CHAIN_IDS = Object.keys(CHAINS).map((n) => Number(n) as ChainId)

export function getChain(chainId: ChainId): ChainConfig {
  const c = CHAINS[chainId]
  if (!c) throw new Error(`Bilinmeyen chainId: ${chainId}`)
  return c
}
