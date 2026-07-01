// Renderer geneli paylaşılan UI sabitleri ve yardımcıları.
export const CHAIN_NAMES: Record<number, string> = {
  1: 'Ethereum',
  42161: 'Arbitrum',
  8453: 'Base',
  10: 'Optimism',
  56: 'BNB',
  137: 'Polygon'
}

/** Emin olma eşiği (%) — bunun üzerindeki sinyallere işlem açılır. */
export const TRADE_THRESHOLD = 75

export type Tab =
  | 'overview'
  | 'explore'
  | 'market'
  | 'signals'
  | 'strategies'
  | 'arbitrage'
  | 'news'
  | 'analyst'
  | 'trades'

export const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Genel' },
  { id: 'explore', label: 'Keşfet' },
  { id: 'market', label: 'Piyasa' },
  { id: 'signals', label: 'Sinyaller' },
  { id: 'strategies', label: 'Stratejiler' },
  { id: 'arbitrage', label: 'Arbitraj' },
  { id: 'news', label: 'Haberler' },
  { id: 'analyst', label: 'AI Analist' },
  { id: 'trades', label: 'İşlemler' }
]

/** ABD doları biçimi (2 ondalık). */
export const usd = (n: number | null | undefined): string =>
  Number.isFinite(n)
    ? (n as number).toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2
      })
    : '—'
