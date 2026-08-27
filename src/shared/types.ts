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
  | { type: 'research'; note: ResearchNote }

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
  /** Eski dar şema (AnalystLlm) yerine zengin görüş; ikisi de uyumludur. */
  llm: (AnalystLlm & AnalystOpinion) | null
  llm_used: boolean
  /** Kullanılan analiz derinliği ve LLM token bütçesi. */
  depth?: string
  max_tokens?: number
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

// ---- Ekonomik veri takvimi + otonom araştırma (engine /calendar, /research) ----

/** Takvimdeki tek bir olay (CPI, NFP, FOMC, token unlock...). */
export interface CalendarEvent {
  id: string
  /** Normalize edilmiş ad, ör. "TÜFE (CPI)". */
  title: string
  /** Kaynaktaki ham başlık. */
  raw_title: string
  /** Yayın anı (epoch ms, UTC). */
  ts: number
  tsIso: string
  /** Şu andan kaç saat sonra (negatif = geçmiş). */
  inHours: number
  category: 'macro' | 'crypto' | 'other'
  /** 0..1 — kripto fiyatını oynatma gücü. 1.0 = CPI/NFP/FOMC. */
  importance: number
  source: string
  url: string
  /** Boş = piyasa geneli; doluysa yalnızca bu tokenları etkiler. */
  symbols: string[]
}

export interface CalendarStatus {
  eventCount: number
  lastRefreshMs: number
  lastError: string
  guardEnabled: boolean
  preWindowMin: number
  postWindowMin: number
  nextHighImpact: CalendarEvent | null
  activeWindow: CalendarEvent[]
  feeds: string[]
}

export interface CalendarResponse {
  status: CalendarStatus
  upcoming: CalendarEvent[]
  recent: CalendarEvent[]
}

export interface CalendarGuard {
  symbol: string
  /** Doluysa yeni ALIM engellenir (gerekçe metni). */
  guard: string | null
  sizeFactor: number
  sizeNote: string
  activeWindow: CalendarEvent[]
}

/** Araştırmacının bir olay için ürettiği hazırlık ("pre") / sonuç ("post") notu. */
export interface ResearchNote {
  event_id: string
  title: string
  event_ts: number
  eventTsIso: string
  hoursToEvent: number
  phase: 'pre' | 'post'
  created_ms: number
  summary: string
  expectation: string
  scenarios: { kosul: string; etki: string }[]
  watch: string[]
  risk: string
  /** -1..1 — olay çevresinde risk iştahı eğilimi. */
  bias: number
  surprise: string
  headlines: { source: string; title: string; link: string; ts: number }[]
  market: Record<string, Record<string, number | string | null>>
  author: 'llm' | 'numeric'
  symbols: string[]
}

export interface ResearchStatus {
  running: boolean
  enabled: boolean
  intervalMin: number
  lookaheadH: number
  minImportance: number
  llm: boolean
  cycles: number
  lastCycleMs: number
  noteCount: number
  calendar: CalendarStatus
}

export interface ResearchResponse {
  status: ResearchStatus
  notes: ResearchNote[]
}

/** SALT-OKUMA canlı rota testi sonucu (/live/quote-probe). */
export interface QuoteProbe {
  ok: boolean
  chain_id: number
  dex?: string
  fee_tier?: number
  pair?: string
  amount_in_usd?: number
  amount_out?: number
  price?: number | null
  gas_usd?: number
  roundtrip_cost_bps?: number
  error?: string
}

// ---- Hedef + kaldıraç + iflas riski (engine /goal, /leverage) ----

export interface GoalReport {
  active: boolean
  message?: string
  goal: {
    target_usd: number
    horizon_months: number
    start_equity_usd: number
    start_ts: number
    note: string
  }
  current_equity_usd?: number
  progress_pct?: number
  elapsed_years?: number
  remaining_years?: number
  required_multiple?: number | null
  required_cagr_pct?: number | null
  /** Hedefe yetişmek için gereken GÜNLÜK getiri (%). */
  required_daily_pct?: number | null
  feasibility?: 'makul' | 'zorlu' | 'çok riskli' | 'gerçekçi değil' | '—'
  feasibility_note?: string
  actual_cagr_pct?: number | null
  years_to_target_at_actual?: number | null
  eta_at_actual?: string | null
  assumed_cagr_pct?: number
  years_to_target_at_assumed?: number | null
  monthly_dca_needed_usd?: number | null
  warnings?: string[]
}

export interface LeverageDecision {
  /** Kelly + ölçülen istatistikten çıkan kaldıraç. Kenar yoksa 1.0. */
  leverage: number
  reason: string
  kelly: number
  capped: boolean
  stats: {
    samples: number
    win_prob: number
    avg_win: number
    avg_loss: number
    win_loss_ratio: number
    net: number
  }
}

export interface LeverageAssessment {
  enabled: boolean
  decision: LeverageDecision
  max_leverage_cap: number
  liquidation_price: number | null
  /** Likidasyona kaç % dayanak hareketi kaldı. */
  liquidation_distance_pct: number
  /** 0..1 — sermayeyi sıfırlama olasılığı. Kenar yoksa 1.0. */
  risk_of_ruin: number
  risk_per_trade_effective_pct: number
  target?: {
    multiple: number | null
    fair_upper_bound: number
    fair_upper_bound_pct?: number
    one_in?: number
    note: string
  }
}

export interface LeverageSweepRow {
  leverage: number
  total_return_pct: number
  max_drawdown_pct: number
  liquidated: boolean
  liquidation_bar: number | null
  final_multiple: number
  bars: number
  in_position_bars: number
  funding_cost_pct: number
  fee_cost_pct: number
}

export interface LeverageSweep {
  symbol: string
  interval: string
  bars: number
  spot_return_pct: number
  rows: LeverageSweepRow[]
  best_leverage: number
  best_return_pct: number | null
  first_liquidating_leverage: number | null
  note: string
}

/* ============================================================================
 * Piyasa İstihbaratı (intel) — /intel/* uçlarının tipleri.
 * Kaynak: engine/marketdata/intel/. Her panel bağımsız fail-safe olduğu için
 * `ok` alanı false olabilir; UI bu durumda gerekçeyi (`reason`/`error`) gösterir.
 * ========================================================================= */

/** Tüm intel panellerinin ortak taban alanları. */
export interface IntelBase {
  ok?: boolean
  /** Anahtar gerektiren sağlayıcılarda: anahtar var mı. */
  enabled?: boolean
  /** Panel neden boş (anahtar yok, upstream düştü…). */
  reason?: string
  error?: string
  /** Serbest metin yorum (ör. "arz genişliyor — taze likidite"). */
  note?: string
  /** Vekil (proxy) veri uyarısı. */
  disclaimer?: string
  /** Verinin geldiği kaynak: 'coinglass' | 'proxy' | 'nansen' | 'coingecko'… */
  source?: string
}

export interface FearGreedOne {
  ok: boolean
  value: number
  label: string
  change_1d: number
  change_7d: number
  series: { t: number; value: number }[]
}
export interface IntelFearGreed extends IntelBase {
  crypto?: FearGreedOne
  us?: FearGreedOne
}

export interface IndexRow {
  symbol: string
  name: string
  kind: 'equity' | 'vol' | 'fx' | 'rate' | 'metal' | 'energy' | 'etf'
  ok: boolean
  value?: number
  change_pct?: number | null
  change_pct_7d?: number | null
  change_pct_30d?: number | null
  spark?: number[]
}
export interface IntelIndices extends IntelBase {
  rows: IndexRow[]
}

export interface RiskComponent {
  name: string
  label: string
  value: number | null
  /** true = risk-on oyu, false = risk-off, null = nötr. */
  positive: boolean | null
  detail: string
}
export interface IntelRiskOnOff extends IntelBase {
  score: number
  mode: string
  positive?: number
  negative?: number
  total: number
  components: RiskComponent[]
}

export interface IntelCorrelation extends IntelBase {
  base?: string
  rows: { symbol: string; name: string; corr_30d: number | null; corr_90d: number | null }[]
}

export interface PremiumRow {
  coin: string
  coinbase: number
  offshore: number
  venue: string
  premium_usd: number
  premium_pct: number
}
export interface IntelPremium extends IntelBase {
  rows: PremiumRow[]
  series: Record<string, { t: number; premium_pct: number }[]>
  bias: number
}

export interface EtfFlowSide extends IntelBase {
  asset?: string
  rows: { t?: number; date?: number | string; flow_usd?: number; flow_proxy_usd?: number }[]
  etfs?: string[]
  flow_1d?: number
  flow_5d?: number
  flow_30d?: number
  bias?: number
}
export interface IntelEtf extends IntelBase {
  bitcoin?: EtfFlowSide
  ethereum?: EtfFlowSide
  bias?: number
}

export interface IntelStablecoins extends IntelBase {
  total_supply: number
  change_7d: number
  change_30d: number
  change_30d_pct: number | null
  bias: number
  assets: {
    symbol: string
    name: string
    supply: number
    change_1d: number
    change_7d: number
    change_30d: number
    price: number | null
  }[]
  series: { t: number; supply: number }[]
}

export interface IntelStablecoinChains extends IntelBase {
  rows: { chain: string; supply: number; change_7d: number; change_7d_pct: number | null }[]
}

export interface IntelChainFees extends IntelBase {
  rows: {
    chain: string
    fees_24h: number
    fees_30d: number
    fees_change_pct: number | null
    dex_volume_24h: number
    tvl: number
  }[]
  protocols?: { name: string; fees_24h: number; chains: string[] }[]
  total_24h: number
  total_30d: number
  /** Zincir dağılımı protokol toplamından bölüştürüldüyse true. */
  approx?: boolean
  leader: string | null
  leader_fees: number | null
}

export interface IntelDexVolumes extends IntelBase {
  rows: {
    name: string
    volume_24h: number
    volume_7d: number
    change_1d: number | null
    chains: string[]
  }[]
  total_24h: number
}

export interface YieldPool {
  project: string
  chain: string
  symbol: string
  tvl: number
  apy: number
  apy_base: number | null
  apy_reward: number | null
  stablecoin: boolean
  il_risk: string | null
  exposure: string | null
  prediction: string | null
}
export interface IntelYields extends IntelBase {
  rows: YieldPool[]
  stable_rows: YieldPool[]
  count: number
}

export interface UnlockRow {
  name: string
  symbol: string
  t: number
  tokens: number
  value_usd: number
  mcap: number
  pct_of_mcap: number | null
  category: string
  unlock_type: string | null
}
export interface IntelUnlocks extends IntelBase {
  rows: UnlockRow[]
  significant: UnlockRow[]
  total_usd?: number
  scanned?: number
  window_days: number
}

export interface IntelHacks extends IntelBase {
  rows: {
    name: string
    t: number
    amount_usd: number
    chain: string | null
    technique: string | null
    classification: string | null
  }[]
}

export interface SectorRow {
  sector: string
  id: string
  market_cap: number
  change_24h_pct: number
  net_flow_usd: number
  volume_24h: number
  top: string[]
  dominance_bp?: number
}
export interface IntelSectors extends IntelBase {
  rows: SectorRow[]
  inflow: SectorRow[]
  outflow: SectorRow[]
  edges: { from: string; to: string; flow_usd: number }[]
}

export interface IntelChains extends IntelBase {
  rows: { chain: string; tvl: number; symbol: string | null; share_pct?: number }[]
  total_tvl: number
}

export interface IntelDominance extends IntelBase {
  btc_dominance: number | null
  eth_dominance: number | null
  stable_dominance: number | null
  total_market_cap_usd: number | null
  total_volume_usd: number | null
  mcap_change_24h: number | null
}

export interface IntelUtxo extends IntelBase {
  date?: string
  price: number
  realized_price: number
  sth_realized: number | null
  mvrv: number
  premium_pct: number
  zone: string
  bias: number
  sth_note: string | null
  series: { d: string; price: number; realized: number; mvrv: number; sth: number | null }[]
}

export interface HlAssetRow {
  symbol: string
  price: number
  change_pct_24h: number | null
  volume_usd: number
  funding_pct: number
  open_interest_usd: number
}
export interface HlSentiment extends IntelBase {
  count?: number
  total_oi_usd?: number
  total_volume_24h?: number
  weighted_funding_pct?: number
  breadth_pct?: number
  score?: number
  label?: string
  top_oi?: HlAssetRow[]
  top_volume?: HlAssetRow[]
  movers?: HlAssetRow[]
}
export interface HlWalletAggregate extends IntelBase {
  label?: string
  rows: {
    symbol: string
    long_usd: number
    short_usd: number
    net_usd: number
    long_pct: number
    wallets: number
    unrealized_pnl: number
  }[]
  net_usd?: number
  gross_usd?: number
  score?: number
  wallets_scanned?: number
  wallets_failed?: number
  bias?: string
}
export interface IntelHyperliquid extends IntelBase {
  sentiment?: HlSentiment
  winners?: HlWalletAggregate
  watchlist?: HlWalletAggregate
  bias?: number
}

export interface SmartMoneyRow {
  symbol: string
  score: number
  label: string
  taker_imbalance?: number
  whale_score?: number
  net_usd?: number
  buy_volume?: number | null
  sell_volume?: number | null
}
export interface IntelSmartMoney extends IntelBase {
  rows: SmartMoneyRow[]
  score: number
  accumulation?: SmartMoneyRow[]
  distribution?: SmartMoneyRow[]
}

export interface IntelReserves extends IntelBase {
  symbol?: string
  total?: number
  change_1d?: number
  change_7d?: number
  bias?: number
  rows: { exchange: string; balance: number; change_1d: number; change_7d: number }[]
}

/** Sinyal motoruna giren birleşik piyasa yapısı skoru. */
export interface IntelBiasComponent {
  name: string
  score: number
  weight?: number
  detail: string
}
export interface IntelBias {
  ok: boolean
  score: number
  label: string
  market_score?: number
  symbol_score?: number
  available?: number
  components: IntelBiasComponent[]
  symbol_components?: IntelBiasComponent[]
}

export interface IntelSources {
  keys: Record<string, boolean | number>
  providers: Record<string, { enabled: boolean; key_required: boolean; env?: string }>
  panels: Record<string, { group: string; age_s: number | null; cached: boolean }>
}

/** /intel/overview — tüm paneller tek yanıtta. */
export interface IntelPanels {
  fear_greed: IntelFearGreed
  indices: IntelIndices
  risk_on_off: IntelRiskOnOff
  correlation: IntelCorrelation
  premium: IntelPremium
  etf: IntelEtf
  stablecoins: IntelStablecoins
  stablecoin_chains: IntelStablecoinChains
  chain_fees: IntelChainFees
  dex_volumes: IntelDexVolumes
  yields: IntelYields
  unlocks: IntelUnlocks
  hacks: IntelHacks
  sectors: IntelSectors
  chains: IntelChains
  dominance: IntelDominance
  utxo: IntelUtxo
  hyperliquid: IntelHyperliquid
  smart_money: IntelSmartMoney
  reserves: IntelReserves
}

export interface IntelOverview {
  panels: IntelPanels
  sources: IntelSources
  bias: IntelBias
  refresher: {
    enabled: boolean
    running: boolean
    interval_s: number
    runs: number
    last_run: number
    last_error: string | null
  }
}

/* ============================================================================
 * Hyperliquid perp masası (/hl/*) ve AI analist (/analyst/*)
 * ========================================================================= */

export interface HLPositionView {
  symbol: string
  side: 'LONG' | 'SHORT'
  size: number
  entry: number
  leverage: number
  mark: number
  margin_usd: number
  notional_usd: number
  unrealized_pnl: number
  roe_pct: number | null
  liq_price: number | null
  liq_distance_pct: number | null
  funding_paid_usd: number
  fees_paid_usd: number
  opened_ts: number
}

export interface HLHistoryRow {
  t: number
  symbol: string
  action: 'OPEN' | 'CLOSE' | 'LIQUIDATED'
  side?: string
  size?: number
  price?: number
  leverage?: number
  pnl_usd?: number
  fee_usd?: number
  mode: 'paper' | 'live'
  source?: string
}

export interface HLSignerInfo {
  api_wallet: boolean
  account_address: string | null
  keystore: boolean
  source: 'api_wallet' | 'keystore' | null
  ready: boolean
  reason: string | null
}

export interface HLLiveStatus {
  ready: boolean
  flag: boolean
  testnet: boolean
  signer: HLSignerInfo
  reasons: string[]
}

export interface HLLimits {
  max_leverage: number
  max_notional_usd: number
  max_positions: number
  max_total_notional_usd: number
  max_daily_loss_usd: number
  min_liq_distance_pct: number
  cooldown_s: number
  ai_enabled: boolean
  ai_max_notional_usd: number
  ai_max_leverage: number
  ai_min_confidence: number
}

export interface HLState {
  ok: boolean
  mode: 'paper' | 'live'
  equity_usd: number
  cash_usd: number
  margin_used_usd: number
  unrealized_pnl: number
  realized_pnl: number | null
  day_realized_pnl: number
  positions: HLPositionView[]
  history: HLHistoryRow[]
  liquidations: { symbol: string; liq_price: number; mark: number }[]
  live: HLLiveStatus
  limits?: HLLimits
  address?: string
  error?: string
}

export interface HLUniverseRow {
  symbol: string
  mark: number
  max_leverage: number
  sz_decimals: number
  funding_hourly: number
  open_interest_usd: number
  day_volume_usd: number
  change_pct_24h: number | null
}

export interface HLDecisionView {
  approved: boolean
  reason: string
  leverage: number
  notional_usd: number
  warnings: string[]
}

export interface HLPreview {
  symbol: string
  mark: number
  side: string
  decision: HLDecisionView
  size: number
  margin_usd: number
  liq_price: number | null
  max_leverage: number
  funding_hourly_pct: number
}

export interface HLOrderResult {
  ok: boolean
  blocked?: boolean
  reason?: string
  error?: string
  mode?: 'paper' | 'live'
  symbol?: string
  side?: string
  size?: number
  leverage?: number
  price?: number
  fee_usd?: number
  margin_usd?: number
  liq_price?: number | null
  pnl_usd?: number
  source?: string
  decision?: HLDecisionView
}

/* --- AI analist --- */

export interface AnalystTradePlan {
  venue: string
  side: 'LONG' | 'SHORT' | 'YOK'
  entry: number | null
  stop: number | null
  target: number | null
  /** Analistin SEÇTİĞİ kaldıraç (1-10). Stop mesafesi ve oynaklıkla belirlenir. */
  leverage: number
  /** Kaldıracı neden bu seçtiğinin tek cümlelik gerekçesi. */
  leverage_note?: string | null
  size_hint_pct: number
  rationale: string
}

export interface AnalystLevels {
  support: number[]
  resistance: number[]
  invalidation: number | null
}

export interface AnalystScenario {
  name: string
  probability: number
  note: string
}

/** LLM'in ürettiği zengin görüş (analyst.SYSTEM_PROMPT şeması). */
export interface AnalystOpinion {
  bias?: 'AL' | 'SAT' | 'BEKLE'
  confidence?: number
  sentiment?: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
  horizon?: string
  macro_view?: string
  flow_view?: string
  chart_view?: string
  crowd_view?: string
  levels?: AnalystLevels
  scenarios?: AnalystScenario[]
  trade?: AnalystTradePlan
  conflicts?: string[]
  risks?: string[]
  summary?: string
  note?: string
  heuristic?: boolean
  raw?: string
}

export interface AnalystDepthOption {
  id: string
  label: string
  tokens: number
  note: string
}

export interface AnalystUniverseRow {
  symbol: string
  source: string
  mark?: number
  max_leverage?: number
  volume_usd?: number
  perp?: boolean
}

export interface AutopilotOutcome {
  acted: boolean
  reason: string
  result?: HLOrderResult
  decision?: HLDecisionView
  wanted?: { side: string; leverage: number; notional_usd: number; confidence: number }
}

/** Otonom analistin kaydettiği karar özeti. */
export interface AIReport {
  symbol: string
  ts: number
  trigger: string
  bias?: string
  confidence?: number
  sentiment?: string
  horizon?: string
  summary?: string
  macro_view?: string
  flow_view?: string
  chart_view?: string
  crowd_view?: string
  levels?: AnalystLevels
  scenarios?: AnalystScenario[]
  conflicts?: string[]
  risks?: string[]
  trade?: AnalystTradePlan
  llm_used: boolean
  heuristic: boolean
  took_s: number
  /** Eski alan — geriye dönük uyumluluk için doldurulmaya devam ediyor. */
  autopilot?: AutopilotOutcome
  /** Yeni: tam karar kaydı (POZİSYON AL / BEKLE / GİRME + gerekçe). */
  decision?: AIDecision
}

export interface AIAnalystStatus {
  enabled: boolean
  running: boolean
  interval_min: number
  watchlist: string[]
  depth: string
  scans: number
  errors: number
  last_scan: number
  last_error: string | null
  queued: string[]
  autopilot: boolean
  autopilot_limits: Record<string, number | boolean>
}

/* --- AI kararı: POZİSYON AL / BEKLE / GİRME -------------------------------
 * Otopilot kapalı olsa bile üretilir; `executed` false kalır ve `reason`
 * işleme dönmeme sebebini söyler. Durum makinesi engine/marketdata/
 * ai_analyst.py `decide()` içindedir. */
export type DecisionState =
  | 'READY'      // kapı onayladı, otopilot kapalı → elle açabilirsin
  | 'ACTED'      // otopilot açık, emir gönderildi
  | 'NO_PLAN'    // analist yön önermedi
  | 'LOW_CONF'   // güven eşiğin altında
  | 'HEURISTIC'  // LLM kapalı
  | 'NO_SCAN'    // bu pair hiç taranmadı
  | 'BLOCKED'    // risk kapısı reddetti
  | 'FAILED'     // emir gönderildi ama hata

export type DecisionVerdict = 'enter' | 'wait' | 'avoid'

export interface DecisionPlan {
  requested_leverage: number
  exchange_max_leverage: number
  size_hint_pct: number
  requested_notional_usd: number
  approved_leverage: number | null
  approved_notional_usd: number | null
  leverage_note?: string | null
  entry?: number | null
  stop?: number | null
  target?: number | null
  rationale?: string | null
  intel_score?: number | null
}

export interface AIDecision {
  state: DecisionState
  label: string
  verdict: DecisionVerdict
  symbol: string
  side: 'LONG' | 'SHORT' | null
  confidence: number
  autopilot: boolean
  executed: boolean
  reason: string
  ts: number
  gate?: HLDecisionView
  plan?: DecisionPlan
  result?: HLOrderResult
  report?: AIReport
}
