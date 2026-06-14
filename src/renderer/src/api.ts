// Renderer-side engine istemcisi (tarayıcı fetch + WebSocket).
import type {
  ArbitrageOpportunity,
  MarketSnapshot,
  NewsItem,
  AnalystReport,
  GasInfo,
  BacktestResult,
  BotConfig,
  BotEvent,
  BotState,
  PortfolioSnapshot,
  PriceQuote,
  TradeMode,
  TradeOrder,
  TradeSignal
} from '@shared/types'

const BASE = 'http://127.0.0.1:8787'
const WS = 'ws://127.0.0.1:8787/ws'

async function get<T>(p: string): Promise<T> {
  const r = await fetch(BASE + p)
  if (!r.ok) throw new Error(`${p}: ${r.status}`)
  return r.json()
}
async function post<T>(p: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + p, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!r.ok) throw new Error(`${p}: ${r.status}`)
  return r.json()
}

export const api = {
  state: () => get<BotState>('/state'),
  config: () => get<BotConfig>('/config'),
  prices: () => get<PriceQuote[]>('/prices'),
  arbitrage: () => get<ArbitrageOpportunity[]>('/arbitrage'),
  signals: () => get<TradeSignal[]>('/signals'),
  portfolio: () => get<PortfolioSnapshot>('/portfolio'),
  trades: (n = 100) => get<TradeOrder[]>(`/trades?limit=${n}`),
  equity: () => get<{ t: number; equity: number }[]>('/equity'),
  marketdata: (symbols: string) => get<MarketSnapshot[]>(`/marketdata?symbols=${symbols}`),
  news: (limit = 12) => get<NewsItem[]>(`/news?limit=${limit}`),
  analyst: (symbol: string) => get<AnalystReport>(`/analyst/${symbol}`),
  gas: () => get<GasInfo[]>('/gas'),
  start: () => post<BotState>('/start'),
  stop: () => post<BotState>('/stop'),
  setMode: (mode: TradeMode) => post<BotState>('/mode', { mode }),
  backtest: (base: string, candles: unknown[], cash: number) =>
    post<BacktestResult>('/backtest', { base, quote: 'USD', candles, starting_cash_usd: cash })
}

export function connectEvents(onEvent: (e: BotEvent) => void): () => void {
  let ws: WebSocket | null = null
  let closed = false
  const open = (): void => {
    ws = new WebSocket(WS)
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data))
      } catch {
        /* yoksay */
      }
    }
    ws.onclose = () => {
      if (!closed) setTimeout(open, 2000)
    }
    ws.onerror = () => ws?.close()
  }
  open()
  return () => {
    closed = true
    ws?.close()
  }
}
