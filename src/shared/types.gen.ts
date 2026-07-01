// ============================================================================
// OTOMATİK ÜRETİLDİ — ELLE DÜZENLEME. Kaynak: engine/models.py
// Yeniden üretmek için: python scripts/gen_types.py
// Bu arayüzler Python to_dict()/asdict() (snake_case) çıktısıyla hizalıdır.
// ============================================================================
/* eslint-disable */

export interface TechnicalSnapshot {
  rsi: number
  ema_fast: number
  ema_slow: number
  macd: number
  macd_signal: number
  momentum: number
  price: number
  sma_20: number
  roc: number
  stoch_k: number
  stoch_d: number
  stoch_rsi: number
  cci: number
  williams_r: number
  bb_upper: number
  bb_lower: number
  bb_mid: number
  bb_pct_b: number
  bb_bandwidth: number
  atr: number
  adx: number
  plus_di: number
  minus_di: number
  obv: number
  vwap: number
  mfi: number
  supertrend: number
  supertrend_dir: number
  ichimoku_tenkan: number
  ichimoku_kijun: number
  ichimoku_senkou_a: number
  ichimoku_senkou_b: number
  psar: number
  psar_dir: number
  keltner_upper: number
  keltner_lower: number
  donchian_upper: number
  donchian_lower: number
  awesome: number
  squeeze_on: number
  squeeze_momentum: number
  wavetrend1: number
  wavetrend2: number
  ma_cross_dir: number
  rsi_div: number
  smc_trend: number
  fvg_bias: number
  swing_trend: number
}

export interface PriceQuote {
  chain_id: number
  dex: string
  base: string
  quote: string
  price: number
  liquidity_usd: number
  timestamp: number
}

export interface ArbitrageOpportunity {
  base: string
  quote: string
  buy_chain: number
  buy_dex: string
  buy_price: number
  sell_chain: number
  sell_dex: string
  sell_price: number
  spread_pct: number
  est_net_profit_usd: number
  notional_usd: number
  id: string
  timestamp: number
}

export interface TradeSignal {
  chain_id: number
  base: string
  quote: string
  action: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  technical: TechnicalSnapshot
  rationale: string
  source: string
  breakdown: Record<string, unknown> | null
  id: string
  timestamp: number
}

export interface TradeOrder {
  mode: 'paper' | 'live'
  chain_id: number
  dex: string
  base: string
  quote: string
  side: 'BUY' | 'SELL'
  amount: number
  price: number
  status: 'pending' | 'filled' | 'failed' | 'rejected'
  tx_hash: string
  filled_price: number
  fee_usd: number
  reason: string
  signal_id: string
  venue_type: string
  nonce: number
  id: string
  timestamp: number
}

export interface Position {
  chain_id: number
  base: string
  quote: string
  amount: number
  avg_entry: number
  realized_pnl_usd: number
  unrealized_pnl_usd: number
  last_price: number
  dex: string
  opened_ts: number
  key: string
}
