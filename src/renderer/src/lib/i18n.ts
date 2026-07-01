// Hafif i18n altyapısı — bağımlılık yok. Varsayılan dil: TR. EN hazır.
import { useSyncExternalStore } from 'react'

export type Lang = 'tr' | 'en'
type Dict = Record<string, string>

const TR: Dict = {
  'conn.connecting': 'bağlanıyor…',
  'conn.open': 'engine bağlı',
  'conn.reconnecting': 'yeniden bağlanıyor…',
  'conn.down': 'engine yok (uvicorn?)',
  'run.start': '▶ Başlat',
  'run.stop': '■ Durdur',
  'mode.paper': 'Paper',
  'mode.live': 'Live',
  'tab.overview': 'Genel',
  'tab.explore': 'Keşfet',
  'tab.market': 'Piyasa',
  'tab.signals': 'Sinyaller',
  'tab.strategies': 'Stratejiler',
  'tab.arbitrage': 'Arbitraj',
  'tab.news': 'Haberler',
  'tab.analyst': 'AI Analist',
  'tab.trades': 'İşlemler',
  'kpi.equity': 'Equity',
  'kpi.cash': 'Nakit',
  'kpi.pnl': 'Toplam PnL',
  'kpi.positions': 'Açık Pozisyon',
  'kpi.arb': 'Fırsat (arb)',
  'kpi.gas': 'Gas (ETH)'
}

const EN: Dict = {
  'conn.connecting': 'connecting…',
  'conn.open': 'engine connected',
  'conn.reconnecting': 'reconnecting…',
  'conn.down': 'engine down (uvicorn?)',
  'run.start': '▶ Start',
  'run.stop': '■ Stop',
  'mode.paper': 'Paper',
  'mode.live': 'Live',
  'tab.overview': 'Overview',
  'tab.explore': 'Explore',
  'tab.market': 'Market',
  'tab.signals': 'Signals',
  'tab.strategies': 'Strategies',
  'tab.arbitrage': 'Arbitrage',
  'tab.news': 'News',
  'tab.analyst': 'AI Analyst',
  'tab.trades': 'Trades',
  'kpi.equity': 'Equity',
  'kpi.cash': 'Cash',
  'kpi.pnl': 'Total PnL',
  'kpi.positions': 'Open Positions',
  'kpi.arb': 'Opportunities (arb)',
  'kpi.gas': 'Gas (ETH)'
}

const DICTS: Record<Lang, Dict> = { tr: TR, en: EN }

let _lang: Lang = 'tr'
const _subs = new Set<() => void>()

function subscribe(cb: () => void): () => void {
  _subs.add(cb)
  return () => _subs.delete(cb)
}
function getLang(): Lang {
  return _lang
}
export function setLang(l: Lang): void {
  if (l === _lang) return
  _lang = l
  if (typeof document !== 'undefined') document.documentElement.lang = l
  _subs.forEach((cb) => cb())
}

export function t(key: string): string {
  return DICTS[_lang][key] ?? key
}

export function useI18n(): { t: (k: string) => string; lang: Lang; setLang: (l: Lang) => void } {
  const lang = useSyncExternalStore(subscribe, getLang, getLang)
  return { t: (k: string) => DICTS[lang][k] ?? k, lang, setLang }
}
