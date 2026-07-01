// ============================================================
//  Paylaşılan tip tanımları (main <-> renderer <-> core)
// ============================================================

export type ChainId = 1 | 42161 | 8453 | 10 | 56 | 137

export type DexProtocol = 'uniswap-v2' | 'uniswap-v3'

export interface TokenInfo {
  symbol: string
  address: string
  decimals: number
}

export interface DexConfig {
  /** İnsan-okunur ad, ör. "Uniswap V3" */
  name: string
  protocol: DexProtocol
  /** v2: router/factory, v3: quoter + factory */
  factory: string
  router?: string
  quoter?: string
  /** v3 fee tier (ör. 3000 = %0.3). v2 için kullanılmaz. */
  feeTiers?: number[]
}

export interface ChainConfig {
  chainId: ChainId
  name: string
  rpcEnvKey: string
  nativeSymbol: string
  /** Bu zincirde fiyatlamada referans alınacak stable (USDC vb.) */
  stable: TokenInfo
  /** Wrapped native (WETH/WBNB/WMATIC) */
  wrappedNative: TokenInfo
  dexes: DexConfig[]
  /** Bu zincirde izlenecek token evreni */
  tokens: TokenInfo[]
  blockExplorer: string
}

// ---- Fiyat / piyasa verisi ----

export interface PriceQuote {
  chainId: ChainId
  dex: string
  base: string // sembol
  quote: string // sembol (genelde stable)
  /** 1 base = price quote */
  price: number
  /** Likidite tahmini (quote cinsinden), arbitraj fizibilitesi için */
  liquidityUsd: number
  timestamp: number
}

export interface Candle {
  t: number // ms timestamp
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// ---- Arbitraj ----

export interface ArbitrageOpportunity {
  id: string
  base: string
  quote: string
  buyChain: ChainId
  buyDex: string
  buyPrice: number
  sellChain: ChainId
  sellDex: string
  sellPrice: number
  spreadPct: number
  /** Tahmini net kâr (gas + slippage düşülmüş), quote cinsinden */
  estNetProfitUsd: number
  notionalUsd: number
  timestamp: number
}

// ---- Sinyaller ----

export type SignalAction = 'BUY' | 'SELL' | 'HOLD'

export interface TechnicalSnapshot {
  rsi: number
  emaFast: number
  emaSlow: number
  macd: number
  macdSignal: number
  momentum: number
  price: number
  // Python (asdict) snake_case gönderir; runtime JSON ile hizalı opsiyonel alanlar:
  ema_fast?: number
  ema_slow?: number
  macd_signal?: number
  // --- genişletilmiş klasik göstergeler (opsiyonel) ---
  sma_20?: number
  roc?: number
  stoch_k?: number
  stoch_d?: number
  stoch_rsi?: number
  cci?: number
  williams_r?: number
  bb_upper?: number
  bb_lower?: number
  bb_mid?: number
  bb_pct_b?: number
  bb_bandwidth?: number
  atr?: number
  adx?: number
  plus_di?: number
  minus_di?: number
  obv?: number
  vwap?: number
  mfi?: number
  // --- gelişmiş / TradingView göstergeleri (opsiyonel) ---
  supertrend?: number
  supertrend_dir?: number
  ichimoku_tenkan?: number
  ichimoku_kijun?: number
  ichimoku_senkou_a?: number
  ichimoku_senkou_b?: number
  psar?: number
  psar_dir?: number
  keltner_upper?: number
  keltner_lower?: number
  donchian_upper?: number
  donchian_lower?: number
  awesome?: number
  squeeze_on?: number
  squeeze_momentum?: number
  wavetrend1?: number
  wavetrend2?: number
  // --- pattern / piyasa-yapısı (TradingView'den uyarlanan) ---
  ma_cross_dir?: number // +1 long / -1 short
  rsi_div?: number // +1 boğa / -1 ayı uyumsuzluk
  smc_trend?: number // +1 / -1 SMC yapı (BOS/CHoCH)
  fvg_bias?: number // +1 / -1 Fair Value Gap
  swing_trend?: number // +1 yükseliş (HH+HL) / -1 düşüş (LH+LL) / 0 yatay
}

/** Güvenin nasıl hesaplandığı: teknik + haber kırılımı (UI'da hep gösterilir). */
export interface SignalBreakdown {
  technicalScore: number // 0..1 kural skoru
  technicalState: string // RSI/ADX/Supertrend... özeti
  newsScore: number // -1..1 sentiment
  newsLabel: string // pozitif|nötr|negatif
  newsCount: number
  newsMatched: number // token'a özel başlık sayısı
  newsMarket: boolean // true: piyasa geneli (token'a özel az)
  newsHeadlines: string[]
  weights: { technical: number; news: number }
  llmUsed: boolean
  llmAction: string | null
  llmNote: string
  finalConfidence: number // 0..1
}

export interface TradeSignal {
  id: string
  chainId: ChainId
  base: string
  quote: string
  action: SignalAction
  /** 0..1 güven skoru */
  confidence: number
  technical: TechnicalSnapshot
  /** LLM'in kısa gerekçesi (hibrit modda) */
  rationale: string
  source: 'technical' | 'llm' | 'hybrid'
  breakdown?: SignalBreakdown
  timestamp: number
}

// ---- İşlemler / pozisyonlar ----

export type TradeMode = 'paper' | 'live'
export type TradeSide = 'BUY' | 'SELL'
export type TradeStatus = 'pending' | 'filled' | 'failed' | 'rejected'

export interface TradeOrder {
  id: string
  mode: TradeMode
  chainId: ChainId
  dex: string
  base: string
  quote: string
  side: TradeSide
  /** base cinsinden miktar */
  amount: number
  /** beklenen fiyat */
  price: number
  status: TradeStatus
  txHash?: string
  filledPrice?: number
  feeUsd?: number
  reason?: string
  signalId?: string
  /** İşlem yeri tipi: 'dex' (zincir-üstü, gas var) | 'cex' (borsa). */
  venueType?: 'dex' | 'cex'
  /** İşlem nonce'u (live: gerçek zincir; paper: simüle sayaç; -1 = yok). */
  nonce?: number
  timestamp: number
}

export interface WalletInfo {
  address: string | null
  source: 'signer' | 'watch' | 'none'
  can_sign: boolean
  mode: string
}

export interface Position {
  key: string // chainId:base
  chainId: ChainId
  base: string
  quote: string
  amount: number
  avgEntry: number
  realizedPnlUsd: number
  unrealizedPnlUsd: number
  lastPrice: number
  // Türetilmiş/zenginleştirilmiş alanlar (backend Position.to_dict)
  side?: 'LONG' | 'SHORT'
  costUsd?: number
  valueUsd?: number
  pnlPct?: number
  dex?: string
  openedTs?: number
}

export interface PortfolioSnapshot {
  cashUsd: number
  equityUsd: number
  positions: Position[]
  realizedPnlUsd: number
  unrealizedPnlUsd: number
  timestamp: number
}

// ---- Bot durumu / config ----

export interface RiskConfig {
  maxPositionUsd: number
  maxOpenPositions: number
  maxDailyLossUsd: number
  stopLossPct: number
  takeProfitPct: number
  slippageBps: number // basis points (100 = %1)
  minConfidence: number
}

export interface BotConfig {
  mode: TradeMode
  pollIntervalMs: number
  enabledChains: ChainId[]
  startingCashUsd: number
  risk: RiskConfig
  llmProvider: 'anthropic' | 'openai' | 'none'
}

export type BotStatus = 'stopped' | 'running' | 'error'

export interface BotState {
  status: BotStatus
  mode: TradeMode
  lastTick: number
  message?: string
}

// ---- IPC köprü sözleşmesi (preload -> renderer) ----

export interface BotApi {
  start: () => Promise<BotState>
  stop: () => Promise<BotState>
  getState: () => Promise<BotState>
  getConfig: () => Promise<BotConfig>
  setConfig: (patch: Partial<BotConfig>) => Promise<BotConfig>
  setMode: (mode: TradeMode) => Promise<BotState>
  getPrices: () => Promise<PriceQuote[]>
  getArbitrage: () => Promise<ArbitrageOpportunity[]>
  getSignals: () => Promise<TradeSignal[]>
  getPortfolio: () => Promise<PortfolioSnapshot>
  getTrades: (limit?: number) => Promise<TradeOrder[]>
  getEquityCurve: () => Promise<{ t: number; equity: number }[]>
  runBacktest: (params: BacktestParams) => Promise<BacktestResult>
  onEvent: (cb: (evt: BotEvent) => void) => () => void
}

export interface BacktestParams {
  base: string
  quote: string
  candles?: Candle[]
  startingCashUsd: number
  risk: RiskConfig
}

export interface BacktestResult {
  trades: TradeOrder[]
  equityCurve: { t: number; equity: number }[]
  totalReturnPct: number
  maxDrawdownPct: number
  winRate: number
  sharpe: number
  finalEquityUsd: number
}

export type BotEvent =
  | { type: 'tick'; state: BotState }
  | { type: 'signal'; signal: TradeSignal }
  | { type: 'trade'; order: TradeOrder }
  | { type: 'arbitrage'; opp: ArbitrageOpportunity }
  | { type: 'log'; level: 'info' | 'warn' | 'error'; message: string }

// ---- Açık piyasa verisi + haber (engine /marketdata, /news) ----

export interface MarketCex {
  source: string
  symbol: string
  price: number
  change_pct_24h: number
  high_24h: number
  low_24h: number
  volume_quote_24h: number
  order_book?: {
    best_bid: number
    best_ask: number
    spread_bps: number
    imbalance: number
  }
}

export interface MarketDex {
  source: string
  chain: string
  dex: string
  pair: string
  price_usd: number
  liquidity_usd: number
  volume_24h_usd: number
  change_pct_24h: number
  url?: string
}

export interface MarketComparison {
  cex_price: number
  dex_price: number
  dex_venue: string
  spread_bps: number
  dex_liquidity_usd: number
  note: string
}

export interface MarketSnapshot {
  symbol: string
  ts: number
  cex: MarketCex | null
  dex: MarketDex | null
  comparison: MarketComparison | null
  errors: string[]
}

export interface NewsItem {
  source: string
  title: string
  summary: string
  link: string
  ts: number
}

// ---- Canlı gas (zincir başına) ----
export interface GasInfo {
  chain_id: number
  chain: string
  gwei: number
  swap_usd: number
}

// ---- Keşfet / Piyasalar (/markets) ----
export type MarketStatus = 'live' | 'coming_soon'

export interface MarketDescriptor {
  id: string
  label: string
  asset_class: string // 'crypto' | 'equity' | ...
  status: MarketStatus
}

export interface MarketInstrument {
  market: string // MarketDescriptor.id (örn. 'dex' | 'binance' | 'hyperliquid')
  symbol: string
  quote: string
  venue: string
  chain_id?: number | null
  price: number
  change_pct_24h?: number | null
  liquidity_usd?: number | null
  volume_usd?: number | null
  // perp (kaldıraçlı) piyasalar için opsiyonel alanlar (örn. Hyperliquid)
  kind?: string // 'spot' | 'perp'
  max_leverage?: number
  funding_pct?: number // saatlik funding (%)
  open_interest_usd?: number
  // meme / DEX (örn. Solana) için opsiyonel alanlar
  market_cap_usd?: number
  url?: string // DexScreener vb. dış sayfa
}

export interface MarketsResponse {
  markets: MarketDescriptor[]
  instruments: MarketInstrument[]
}

// ---- LLM analist raporu (/analyst) ----
export interface AnalystLlm {
  bias?: 'AL' | 'SAT' | 'BEKLE'
  sentiment?: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  confidence?: number
  summary?: string
  chart_view?: string
  crowd_view?: string
  cex_dex_view?: string
  news_impact?: string
  risks?: string[]
  raw?: string
  note?: string
  heuristic?: boolean
}

// ---- Balina (whale) takibi ----
export interface WhalePressure {
  score: number // -1 satış .. +1 alım
  buy_usd: number
  sell_usd: number
  buy_count: number
  sell_count: number
  big_count: number
  min_usd: number
}
export interface WhaleWall {
  price: number
  qty: number
  usd: number
}
export interface WhaleTrade {
  price: number
  qty: number
  usd: number
  side: 'buy' | 'sell'
  time: number
}
export interface WhaleSummary {
  symbol: string
  label: string // "balina alımı" | "balina satışı" | "dengeli"
  pressure: WhalePressure
  walls: { bids: WhaleWall[]; asks: WhaleWall[] }
  recent: WhaleTrade[]
}

export interface DerivativesSummary {
  symbol: string
  funding: number
  funding_pct: number
  oi_change_pct: number
  ls_ratio: number
  long_pct?: number | null
  short_pct?: number | null
  squeeze: {
    score: number
    direction: string
    cascade: boolean
    notes: string[]
  }
  ok: boolean
}

export interface OnchainSignal {
  enabled: boolean
  score: number
  note?: string
  total_exchange_eth?: number
  wallets?: Record<string, number>
}

export interface AnalystReport {
  symbol: string
  ts: number
  market: MarketSnapshot
  technical?: { action?: string; confidence?: number; rationale?: string; price?: number } | null
  whales?: WhaleSummary | null
  derivatives?: DerivativesSummary | null
  onchain?: OnchainSignal | null
  headlines: NewsItem[]
  llm: AnalystLlm | null
  llm_used: boolean
}

// ---- TA chart beslemesi (/chart, lightweight-charts) ----
export interface LinePoint {
  t: number // ms
  value: number
}

export interface SupertrendPoint extends LinePoint {
  dir: number // +1 yükseliş, -1 düşüş
}

export interface ChartMarker {
  t: number // ms
  action: 'BUY' | 'SELL'
  confidence: number
  price: number
}

export interface ChartSignal {
  action: SignalAction
  confidence: number
  source: string
  rationale: string
  price: number
}

export interface ChartFeed {
  symbol: string
  quote: string
  interval: string
  /** OHLCV kaynağı: 'binance' (CEX) | 'coingecko' (token yedeği) */
  source?: string
  /** Veri bulunamazsa açıklama */
  note?: string
  candles: Candle[]
  overlays: {
    emaFast: LinePoint[]
    emaSlow: LinePoint[]
    bbUpper: LinePoint[]
    bbMid: LinePoint[]
    bbLower: LinePoint[]
    supertrend: SupertrendPoint[]
  }
  markers: ChartMarker[]
  signal: ChartSignal | null
}
