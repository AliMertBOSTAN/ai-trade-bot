// ============================================================
//  Python engine (FastAPI) REST + WebSocket istemcisi.
//  Electron main process bu istemci üzerinden engine'e bağlanır.
// ============================================================
import type {
  ArbitrageOpportunity,
  BacktestParams,
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

const BASE = process.env.ENGINE_URL ?? 'http://127.0.0.1:8787'
const WS = BASE.replace(/^http/, 'ws') + '/ws'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

export const engineApi = {
  getState: () => get<BotState>('/state'),
  getConfig: () => get<BotConfig>('/config'),
  getPrices: () => get<PriceQuote[]>('/prices'),
  getArbitrage: () => get<ArbitrageOpportunity[]>('/arbitrage'),
  getSignals: () => get<TradeSignal[]>('/signals'),
  getPortfolio: () => get<PortfolioSnapshot>('/portfolio'),
  getTrades: (limit = 100) => get<TradeOrder[]>(`/trades?limit=${limit}`),
  getEquityCurve: () => get<{ t: number; equity: number }[]>('/equity'),
  start: () => post<BotState>('/start'),
  stop: () => post<BotState>('/stop'),
  setMode: (mode: TradeMode) => post<BotState>('/mode', { mode }),
  runBacktest: (p: BacktestParams) =>
    post<BacktestResult>('/backtest', {
      base: p.base,
      quote: p.quote,
      candles: p.candles ?? [],
      starting_cash_usd: p.startingCashUsd
    })
}

/** WebSocket event akışı; otomatik yeniden bağlanır. */
export function connectEvents(onEvent: (e: BotEvent) => void): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let keepalive: ReturnType<typeof setInterval> | null = null

  const open = () => {
    ws = new WebSocket(WS)
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data as string) as BotEvent)
      } catch {
        /* yoksay */
      }
    }
    ws.onopen = () => {
      keepalive = setInterval(() => ws?.readyState === 1 && ws.send('ping'), 15000)
    }
    ws.onclose = () => {
      if (keepalive) clearInterval(keepalive)
      if (!closed) setTimeout(open, 2000) // reconnect
    }
    ws.onerror = () => ws?.close()
  }
  open()

  return () => {
    closed = true
    if (keepalive) clearInterval(keepalive)
    ws?.close()
  }
}
