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
  risk:
    'Hedefin gerektirdiği getiri, botun ÖLÇÜLEN getirisi, kaldıraç kararı (Kelly), likidasyon fiyatı ve iflas olasılığı. Bu ekran hiçbir ayarı değiştirmez — yalnızca gerçeği gösterir.',
  calendar:
    'Ekonomik veri takvimi (CPI/NFP/FOMC + kripto olayları) ve botun bu tarihler için önceden hazırladığı araştırma notları. Yüksek etkili veri penceresinde yeni alım otomatik durur.',
  analyst: 'LLM tabanlı piyasa yorumu: seçtiğin sembol için yapay zeka analizi.',
  intel:
    'Piyasa İstihbaratı: makro rejim (korku endeksleri, DXY/VIX/faiz, risk-on/off), on-chain akışlar (stablecoin arzı, zincir ücretleri, sektör rotasyonu, unlock takvimi) ve Hyperliquid/whale konumlanması. Bu panellerin birleşik "yapı skoru" sinyal motorunun güvenini modüle eder ve ters yönde güçlüyse yeni pozisyon açılmasını engeller.',
  hyperliquid:
    'Hyperliquid kaldıraçlı (perp) işlem masası: elle emir aç/kapat, kaldıraç ayarla, likidasyon mesafeni gör. AI otopilot açıkken analist kendi kararıyla da işlem açabilir — her iki yol da aynı risk kapılarından geçer.',
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
  | 'calendar'
  | 'risk'
  | 'analyst'
  | 'intel'
  | 'hyperliquid'
  | 'trades'

export const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Genel' },
  { id: 'explore', label: 'Keşfet' },
  { id: 'market', label: 'Piyasa' },
  { id: 'signals', label: 'Sinyaller' },
  { id: 'strategies', label: 'Stratejiler' },
  { id: 'arbitrage', label: 'Arbitraj' },
  { id: 'news', label: 'Haberler' },
  { id: 'calendar', label: 'Takvim & Araştırma' },
  { id: 'risk', label: 'Hedef & Risk' },
  { id: 'analyst', label: 'AI Analist' },
  { id: 'intel', label: 'Piyasa İstihbaratı' },
  { id: 'hyperliquid', label: 'Hyperliquid' },
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

/* ---------------------------------------------------------------------------
 * Üst bölümler: sekme sayısı tek satıra sığmayınca aramak zorlaşıyordu.
 * Artık iki satır var — üstte NE YAPMAK istediğin, altta o iş için paneller.
 *   İZLE  = veri toplama/okuma        (karar vermeden önce baktıkların)
 *   KARAR = sinyal → strateji → risk  (botun ne düşündüğü)
 *   İŞLEM = emir gönderme ve sonuç    (paranın hareket ettiği yer)
 * ------------------------------------------------------------------------- */
export type Section = 'watch' | 'decide' | 'trade'

export const SECTIONS: { id: Section; label: string; hint: string; tabs: Tab[] }[] = [
  {
    id: 'watch',
    label: 'İzle',
    hint: 'Piyasayı okuma katmanı — fiyat, istihbarat, haber, takvim.',
    tabs: ['overview', 'intel', 'market', 'explore', 'news', 'calendar']
  },
  {
    id: 'decide',
    label: 'Karar',
    hint: 'Botun ne düşündüğü: sinyal → strateji → risk → AI görüşü.',
    tabs: ['signals', 'strategies', 'analyst', 'risk']
  },
  {
    id: 'trade',
    label: 'İşlem',
    hint: 'Emirlerin gittiği yer: perp masası, arbitraj, gerçekleşen işlemler.',
    tabs: ['hyperliquid', 'arbitrage', 'trades']
  }
]

/** Bir sekmenin hangi bölüme ait olduğunu bulur (derin link / geri yükleme için). */
export const sectionOf = (tab: Tab): Section =>
  SECTIONS.find((s) => s.tabs.includes(tab))?.id ?? 'watch'

/** Bölüm içindeki sekmeleri TABS sırasına göre değil, SECTIONS sırasına göre verir. */
export const tabsOf = (section: Section): { id: Tab; label: string }[] => {
  const ids = SECTIONS.find((s) => s.id === section)?.tabs ?? []
  return ids
    .map((id) => TABS.find((t) => t.id === id))
    .filter((t): t is { id: Tab; label: string } => Boolean(t))
}

/* --- Görünüm yoğunluğu ---------------------------------------------------
 * "comfortable" varsayılan; "compact" satır yüksekliklerini ve boşlukları
 * kısar, aynı ekrana ~2 kat veri sığar. Seçim localStorage'da kalıcıdır ve
 * <html data-density="..."> üzerinden CSS'e iner. */
export type Density = 'comfortable' | 'compact'

const DENSITY_KEY = 'atb.density'

export function loadDensity(): Density {
  try {
    return localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable'
  } catch {
    return 'comfortable'
  }
}

export function applyDensity(d: Density): void {
  try {
    document.documentElement.dataset.density = d
    localStorage.setItem(DENSITY_KEY, d)
  } catch {
    /* localStorage kapalıysa yoğunluk yine uygulanır, sadece kalıcı olmaz */
    document.documentElement.dataset.density = d
  }
}

/** Son açık sekmeyi hatırla — uygulama açılışında kaldığın yerden devam. */
const TAB_KEY = 'atb.tab'

export function loadTab(fallback: Tab = 'overview'): Tab {
  try {
    const v = localStorage.getItem(TAB_KEY) as Tab | null
    return v && TABS.some((t) => t.id === v) ? v : fallback
  } catch {
    return fallback
  }
}

export function saveTab(tab: Tab): void {
  try {
    localStorage.setItem(TAB_KEY, tab)
  } catch {
    /* yoksay */
  }
}
