// Renderer-side engine istemcisi (tarayıcı fetch + WebSocket).
import type {
  ArbitrageOpportunity,
  MarketSnapshot,
  MarketsResponse,
  NewsItem,
  CalendarResponse,
  CalendarGuard,
  ResearchResponse,
  QuoteProbe,
  GoalReport,
  LeverageAssessment,
  LeverageSweep,
  AnalystReport,
  GasInfo,
  BacktestResult,
  BotConfig,
  BotEvent,
  BotState,
  ChartFeed,
  PortfolioSnapshot,
  PriceQuote,
  TradeMode,
  TradeOrder,
  TradeSignal,
  WhaleSummary,
  WalletInfo,
  IntelOverview,
  IntelPanels,
  IntelSources,
  IntelBias,
  HLState,
  HLUniverseRow,
  HLPreview,
  HLOrderResult,
  HLLimits,
  HLLiveStatus,
  AnalystDepthOption,
  AnalystUniverseRow,
  AIReport,
  AIAnalystStatus,
  AIDecision
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
  clearTrades: () => post<{ ok: boolean; deleted: number }>('/trades/clear'),
  resetPaper: (seedUsd?: number, cashOnly?: boolean) =>
    post<{ ok: boolean; seed_usd?: number; asset?: string; reason?: string }>(
      '/portfolio/reset',
      { ...(seedUsd != null ? { seed_usd: seedUsd } : {}), cash_only: cashOnly ?? false }
    ),
  /* --- Piyasa İstihbaratı (/intel/*) ---
   * Paneller backend'de TTL cache'lidir; UI sık çağırsa bile upstream'e
   * gidilmez. `refreshIntel` cache'i atlatmaz, tazelemeyi tetikler. */
  intelOverview: () => get<IntelOverview>('/intel/overview'),
  intelGroup: (g: 'macro' | 'onchain' | 'hl') =>
    get<{ group: string; panels: Partial<IntelPanels> }>(`/intel/group/${g}`),
  intelPanel: <K extends keyof IntelPanels>(name: K) =>
    get<{ name: K; data: IntelPanels[K] }>(`/intel/panel/${name}`),
  intelSources: () => get<IntelSources>('/intel/sources'),
  intelBias: (symbol?: string) =>
    get<IntelBias>(`/intel/bias${symbol ? `?symbol=${symbol}` : ''}`),
  refreshIntel: () =>
    get<{ ok: boolean; refreshed: number; healthy: number }>('/intel/refresh'),

  /* --- Hyperliquid perp masası (/hl/*) ---
   * Emirler backend'de risk kapısından geçer; `blocked: true` dönerse emir
   * GÖNDERİLMEMİŞTİR, `reason` neden reddedildiğini söyler. */
  hlState: () => get<HLState>('/hl/state'),
  hlUniverse: (limit = 400) =>
    get<{ ok: boolean; count: number; rows: HLUniverseRow[]; error?: string }>(
      `/hl/universe?limit=${limit}`
    ),
  /** Tek çağrıda tanı: engine ayakta mı, HL erişilebilir mi, imzalayıcı hazır mı. */
  hlHealth: () =>
    get<{
      engine: boolean
      hyperliquid: boolean
      markets: number
      error: string | null
      live: HLLiveStatus
      limits: HLLimits
    }>('/hl/health'),
  hlLimits: () => get<{ manual: HLLimits; ai: HLLimits }>('/hl/limits'),
  hlLiveStatus: () => get<HLLiveStatus>('/hl/live/status'),
  hlPreview: (body: {
    symbol: string
    side: string
    notional_usd?: number
    size?: number
    leverage: number
    order_type?: string
    limit_price?: number
  }) => post<HLPreview>('/hl/preview', body),
  hlOrder: (body: {
    symbol: string
    side: string
    notional_usd?: number
    size?: number
    leverage: number
    order_type?: string
    limit_price?: number
    reduce_only?: boolean
  }) => post<HLOrderResult>('/hl/order', body),
  hlClose: (symbol: string, size?: number) =>
    post<HLOrderResult>('/hl/close', { symbol, ...(size != null ? { size } : {}) }),
  hlLeverage: (symbol: string, leverage: number, cross = false) =>
    post<{ ok: boolean; leverage?: number; error?: string }>('/hl/leverage', {
      symbol,
      leverage,
      cross
    }),
  hlResetPaper: (seedUsd = 1000) =>
    post<{ ok: boolean; cash_usd: number }>('/hl/paper/reset', { seed_usd: seedUsd }),

  /* --- AI analist (/analyst/*) --- */
  analystDepths: () =>
    get<{ default: string; options: AnalystDepthOption[] }>('/analyst/depths'),
  analystUniverse: (limit = 250) =>
    get<{ ok: boolean; count: number; rows: AnalystUniverseRow[] }>(
      `/analyst/universe?limit=${limit}`
    ),
  analystRun: (symbol: string, depth?: string) =>
    post<AnalystReport>('/analyst/run', { symbol, ...(depth ? { depth } : {}) }),
  aiStatus: () => get<AIAnalystStatus>('/analyst/auto/status'),
  aiReports: (limit = 30) =>
    get<{
      reports: AIReport[]
      by_symbol: Record<string, AIReport>
      status: AIAnalystStatus
    }>(`/analyst/auto/reports?limit=${limit}`),
  /** Bir pair için AI kararı. refresh=true önce yeni analiz çalıştırır. */
  aiDecision: (symbol: string, refresh = false) =>
    get<AIDecision>(`/analyst/decision/${symbol}${refresh ? '?refresh=true' : ''}`),
  /** Son analizi kapıdan tekrar geçir, emir GÖNDERME (tavan denemesi için). */
  aiDryRun: (symbol: string) => post<AIDecision>(`/analyst/decision/${symbol}/dry-run`),
  aiScan: (symbol?: string) =>
    post<{ ok: boolean; queued?: string[]; ran_inline?: boolean }>(
      `/analyst/auto/scan${symbol ? `?symbol=${symbol}` : ''}`
    ),
  equity: () => get<{ t: number; equity: number }[]>('/equity'),
  performance: () => get<PerformanceReport>('/performance'),
  livePreflight: () => get<LivePreflight>('/live/preflight'),
  chart: (symbol?: string, interval = '1h', limit = 200) =>
    get<ChartFeed>(
      `/chart?interval=${interval}&limit=${limit}${symbol ? `&symbol=${symbol}` : ''}`
    ),
  marketdata: (symbols: string) => get<MarketSnapshot[]>(`/marketdata?symbols=${symbols}`),
  news: (limit = 12) => get<NewsItem[]>(`/news?limit=${limit}`),
  // Ekonomik veri takvimi + otonom araştırma
  calendar: (hours = 168, minImportance = 0) =>
    get<CalendarResponse>(`/calendar?hours=${hours}&min_importance=${minImportance}`),
  calendarRefresh: () => post<{ ok: boolean; added: number }>('/calendar/refresh'),
  calendarGuard: (symbol?: string) =>
    get<CalendarGuard>(`/calendar/guard${symbol ? `?symbol=${symbol}` : ''}`),
  research: (limit = 20) => get<ResearchResponse>(`/research?limit=${limit}`),
  researchRun: () => post<{ ok: boolean; result: Record<string, number> }>('/research/run'),
  quoteProbe: (chainId = 8453, usd = 25) =>
    get<QuoteProbe>(`/live/quote-probe?chain_id=${chainId}&usd=${usd}`),
  // Hedef + kaldıraç riski
  goal: () => get<GoalReport>('/goal'),
  setGoal: (targetUsd: number, horizonMonths: number, note = '') =>
    post<GoalReport>('/goal', {
      target_usd: targetUsd,
      horizon_months: horizonMonths,
      note
    }),
  leverage: (confidence = 0, entryPrice = 0) =>
    get<LeverageAssessment>(
      `/leverage?confidence=${confidence}&entry_price=${entryPrice}`
    ),
  leverageSweep: (symbol = 'BTCUSDT', interval = '4h') =>
    get<LeverageSweep>(`/leverage/sweep?symbol=${symbol}&interval=${interval}`),
  markets: () => get<MarketsResponse>('/markets'),
  analyst: (symbol: string) => get<AnalystReport>(`/analyst/${symbol}`),
  whales: (symbol: string, minUsd = 25000) =>
    get<WhaleSummary>(`/whales/${symbol}?min_usd=${minUsd}`),
  wallet: () => get<WalletInfo>('/wallet'),
  connectWallet: (address: string) => post<WalletInfo>('/wallet', { address }),
  gas: () => get<GasInfo[]>('/gas'),
  start: () => post<BotState>('/start'),
  stop: () => post<BotState>('/stop'),
  setMode: (mode: TradeMode) => post<BotState>('/mode', { mode }),
  backtest: (base: string, candles: unknown[], cash: number) =>
    post<BacktestResult>('/backtest', { base, quote: 'USD', candles, starting_cash_usd: cash }),
  strategies: () => get<StrategiesResponse>('/strategies'),
  strategySignals: () => get<StrategySignalRow[]>('/strategies/signals'),
  strategyAdvice: () => get<StrategyAdvice>('/strategies/advice'),
  applyStrategyAdvice: (
    strategies: { name: string; enabled?: boolean; weight?: number }[],
    minConfidence?: number
  ) =>
    post<{ ok: boolean; applied: number; strategies: StrategiesResponse }>(
      '/strategies/advice/apply',
      { strategies, min_confidence: minConfidence ?? null }
    ),
  applyPreset: (name: string) =>
    post<{ ok: boolean; preset?: string; strategies?: StrategiesResponse; reason?: string }>(
      '/strategies/preset',
      { name }
    ),
  setRiskConfig: (minConfidence: number) =>
    post<{ ok: boolean; min_confidence: number; preset: string }>('/risk/config', {
      min_confidence: minConfidence
    }),
  riskLimits: () => get<RiskLimits>('/risk/config'),
  setRiskLimits: (limits: Partial<RiskLimitFields>) =>
    post<{ ok: boolean; changed: Record<string, number>; limits: RiskLimits }>(
      '/risk/config',
      limits
    ),
  setStrategyConfig: (name: string, cfg: { enabled?: boolean; weight?: number }) =>
    post<{ ok: boolean; strategies: StrategiesResponse }>('/strategies/config', {
      name,
      ...cfg
    }),
  chains: () => get<ChainsResponse>('/chains'),
  setChain: (chainId: number, active: boolean) =>
    post<ChainsResponse>('/chains/config', { chain_id: chainId, active }),
  setChains: (chainIds: number[]) =>
    post<ChainsResponse>('/chains/config', { chain_ids: chainIds })
}

export interface ChainRow {
  chain_id: number
  name: string
  native: string
  active: boolean
}
export interface ChainsResponse {
  chains: ChainRow[]
  active_count: number
}

// Çoklu-strateji çatısı tipleri (backend /strategies ile hizalı)
export interface StrategyInfo {
  name: string
  title?: string
  description?: string
  regime?: string
  params?: string
  enabled: boolean
  weight: number
  capital_fraction: number
}
export interface StrategyCatalogItem {
  name: string
  title?: string
  description?: string
  regime?: string
  params?: string
  in_use: boolean
}
export interface StrategiesResponse {
  active: StrategyInfo[]
  available: string[]
  catalog?: StrategyCatalogItem[]
  /** token ("1:WETH") -> son tespit edilen piyasa rejimi */
  regimes?: Record<string, string>
  /** backend işlem eşiği (0..1) — UI bunu gösterir, sabit yazmaz */
  min_confidence?: number
  /** aktif genel strateji profili: safe | balanced | aggressive | custom */
  preset?: string
  /** mevcut profiller: ad -> {title, min_confidence} */
  presets?: Record<string, { title: string; min_confidence: number }>
}
export interface StrategySignalRow {
  strategy: string
  base: string
  quote: string
  chainId: number
  action: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  reason: string
  /** o anki piyasa rejimi (trend_up | trend_down | range) */
  regime?: string
  /** kararın akıbeti: işlem açıldı / rejim dışı / eşik altı / cooldown / risk reddi */
  status?: string
}

/** /performance yanıtı — risk-ayarlı performans özeti. */
export interface PerformanceReport {
  total_return_pct: number
  final_equity_usd: number
  sharpe: number
  sortino: number
  max_drawdown_pct: number
  calmar: number
  win_rate?: number
  profit_factor?: number
  expectancy_usd?: number
  trades?: number
  equity_usd: number
  cash_usd: number
  realized_pnl_usd: number
  day_realized_pnl_usd: number
  open_positions: number
  exit_style: string
  risk_pct_per_trade: number
}

/** /risk/config — çalışma anında düzenlenebilir risk limitleri. */
export interface RiskLimitFields {
  min_confidence: number
  max_position_usd: number
  max_open_positions: number
  max_daily_loss_usd: number
  max_gas_gwei: number
  slippage_bps: number
  daily_spend_limit_usd: number
}
export interface RiskLimits extends RiskLimitFields {
  preset: string
  /** alan -> [min, max] izin aralığı (backend kırpma sınırları) */
  bounds: Record<string, [number, number]>
}

/** /live/preflight yanıtı — canlıya geçiş ön kontrol raporu. */
export interface LivePreflight {
  ready: boolean
  checks: {
    signer_wallet: boolean
    rpc_available: boolean
    funded_chain: boolean
    llm_ready: boolean
    kill_switch_clear: boolean
  }
  wallet_address: string | null
  chains: {
    chain_id: number
    name: string
    rpc_ok: boolean
    gas_gwei: number | null
    gas_ok: boolean | null
    stable_symbol: string
    stable_balance: number | null
    native_symbol: string
    native_balance: number | null
    error?: string
  }[]
  limits: {
    min_confidence: number
    max_position_usd: number
    max_daily_loss_usd: number
    max_gas_gwei: number
    daily_spend_limit_usd: number
    slippage_bps: number
  }
  llm_provider: string
}

/** /strategies/advice yanıtı — AI strateji önerisi. */
export interface StrategyAdviceItem {
  name: string
  enabled: boolean
  weight: number
  comment: string
  current_enabled: boolean
  current_weight: number
}
export interface StrategyAdvice {
  source: 'llm' | 'heuristic'
  rationale: string
  min_confidence: number
  current_min_confidence: number
  strategies: StrategyAdviceItem[]
  stats: Record<
    string,
    { trades: number; wins: number; pnl_usd: number; win_rate: number; expectancy_usd: number }
  >
}

export type ConnStatus = 'connecting' | 'open' | 'reconnecting'

export function connectEvents(
  onEvent: (e: BotEvent) => void,
  onStatus?: (s: ConnStatus) => void
): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let attempt = 0
  let timer: ReturnType<typeof setTimeout> | null = null

  const RECONNECT_MAX_MS = 15000
  const RECONNECT_BASE_MS = 1000

  const open = (): void => {
    onStatus?.(attempt === 0 ? 'connecting' : 'reconnecting')
    ws = new WebSocket(WS)
    ws.onopen = () => {
      attempt = 0
      onStatus?.('open')
    }
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data))
      } catch {
        /* bozuk mesajı yoksay */
      }
    }
    ws.onclose = () => {
      if (closed) return
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
      attempt += 1
      onStatus?.('reconnecting')
      timer = setTimeout(open, delay)
    }
    ws.onerror = () => {
      // Hata olunca soketi kapat; onclose yeniden bağlanmayı tetikler.
      ws?.close()
    }
  }

  open()

  // Temizleyici: aboneliği iptal et, zamanlayıcıyı durdur, soketi kapat.
  return () => {
    closed = true
    if (timer) clearTimeout(timer)
    ws?.close()
  }
}
