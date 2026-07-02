// Renderer geneli paylaşılan UI sabitleri ve yardımcıları.
export const CHAIN_NAMES: Record<number, string> = {
  1: 'Ethereum',
  42161: 'Arbitrum',
  8453: 'Base',
  10: 'Optimism',
  56: 'BNB',
  137: 'Polygon'
}

/** Varsayılan emin olma eşiği (%). Gerçek değer backend /config'ten okunur
 *  (risk.min_confidence); bu sabit yalnızca yükleme sırasında yedektir. */
export const TRADE_THRESHOLD = 73

/** Rejim kodu -> kullanıcı-dostu etiket. */
export const REGIME_LABELS: Record<string, string> = {
  trend_up: '📈 Trend (yukarı)',
  trend_down: '📉 Trend (aşağı)',
  range: '↔️ Yatay (range)'
}

/** Her sekmenin ne işe yaradığını 1 cümlede anlatan ipuçları. */
export const TAB_HINTS: Record<string, string> = {
  overview: 'Portföyün genel durumu: equity eğrisi, açık pozisyonlar, zincir fiyatları ve gas.',
  explore: 'Token/piyasa keşfi — CEX & DEX verilerinde serbest arama.',
  market: 'Seçili sembolün derinlemesine piyasa verisi (fiyat, hacim, funding, derivatives).',
  signals: 'Hibrit sinyal motorunun token başına BUY/SELL/HOLD kararları ve gerekçeleri. İşleme dönüşüp dönüşmeyeceğine Stratejiler katmanı karar verir.',
  strategies: 'İşlemleri AÇAN katman: stratejileri aç/kapa, sermaye ağırlığı ver. Rejim yönlendirici, piyasaya uymayan stratejileri o an devre dışı bırakır.',
  arbitrage: 'Zincirler arası fiyat farkı fırsatları (net kâr tahminiyle).',
  news: 'Kripto haber akışı ve duygu (sentiment) skoru — sinyal güvenini etkiler.',
  analyst: 'LLM tabanlı piyasa yorumu: seçtiğin sembol için yapay zeka analizi.',
  trades: 'Gerçekleşen işlemler, açık pozisyonlar ve bot günlüğü.'
}

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
