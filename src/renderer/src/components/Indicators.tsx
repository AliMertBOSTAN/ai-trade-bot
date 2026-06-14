import type { TechnicalSnapshot } from '@shared/types'

type Tone = 'pos' | 'neg' | 'neu'

function Tile({ label, value, tone, hint }: {
  label: string
  value: string
  tone?: Tone
  hint?: string
}): JSX.Element {
  return (
    <div className={`ind ${tone ?? 'neu'}`} title={hint}>
      <div className="ind-label">{label}</div>
      <div className="ind-value">{value}</div>
    </div>
  )
}

/** RSI/StochRSI tipi 0-100 osilatörler: <30 aşırı satım (pos), >70 aşırı alım (neg). */
function oscTone(v: number, lo = 30, hi = 70): Tone {
  if (v <= lo) return 'pos'
  if (v >= hi) return 'neg'
  return 'neu'
}

/**
 * Bir sinyalin teknik gösterge anlık görüntüsünü kompakt bir ızgarada gösterir.
 * Tüm alanlar opsiyonel (eski sinyallerde olmayabilir) -> güvenli varsayılanlar.
 */
export default function Indicators({ tech }: { tech: TechnicalSnapshot }): JSX.Element {
  const rsi = tech.rsi ?? 50
  const stochRsi = tech.stoch_rsi ?? 50
  const adx = tech.adx ?? 0
  const stDir = tech.supertrend_dir ?? 0
  const bbB = tech.bb_pct_b ?? 50
  const mfi = tech.mfi ?? 50
  const cci = tech.cci ?? 0
  const wr = tech.williams_r ?? -50
  const ao = tech.awesome ?? 0
  const wt1 = tech.wavetrend1 ?? 0
  const sqOn = (tech.squeeze_on ?? 0) > 0
  const sqMom = tech.squeeze_momentum ?? 0
  const macdUp = (tech.macd ?? 0) > (tech.macd_signal ?? 0)
  const emaUp = (tech.ema_fast ?? 0) > (tech.ema_slow ?? 0)

  return (
    <div className="ind-grid">
      <Tile label="RSI" value={rsi.toFixed(0)} tone={oscTone(rsi)} hint="Göreli Güç Endeksi" />
      <Tile label="StochRSI" value={stochRsi.toFixed(0)} tone={oscTone(stochRsi, 20, 80)} />
      <Tile label="MFI" value={mfi.toFixed(0)} tone={oscTone(mfi, 20, 80)} hint="Para Akış Endeksi" />
      <Tile label="W%R" value={wr.toFixed(0)} tone={oscTone(wr, -80, -20)} hint="Williams %R" />
      <Tile label="CCI" value={cci.toFixed(0)} tone={cci < -100 ? 'pos' : cci > 100 ? 'neg' : 'neu'} />
      <Tile
        label="ADX"
        value={adx.toFixed(0)}
        tone={adx >= 25 ? 'pos' : 'neu'}
        hint="Trend gücü (>25 güçlü)"
      />
      <Tile
        label="Supertrend"
        value={stDir >= 0 ? '▲' : '▼'}
        tone={stDir >= 0 ? 'pos' : 'neg'}
      />
      <Tile label="EMA" value={emaUp ? '▲' : '▼'} tone={emaUp ? 'pos' : 'neg'} hint="EMA12 / EMA26" />
      <Tile label="MACD" value={macdUp ? '▲' : '▼'} tone={macdUp ? 'pos' : 'neg'} />
      <Tile
        label="BB %B"
        value={bbB.toFixed(0)}
        tone={bbB < 5 ? 'pos' : bbB > 95 ? 'neg' : 'neu'}
        hint="Bollinger bant içi konum"
      />
      <Tile label="AO" value={ao >= 0 ? '▲' : '▼'} tone={ao >= 0 ? 'pos' : 'neg'} hint="Awesome Oscillator" />
      <Tile
        label="WaveTrend"
        value={wt1.toFixed(0)}
        tone={wt1 < -60 ? 'pos' : wt1 > 60 ? 'neg' : 'neu'}
      />
      <Tile
        label="Squeeze"
        value={sqOn ? 'ON' : (sqMom >= 0 ? '▲' : '▼')}
        tone={sqOn ? 'neu' : sqMom >= 0 ? 'pos' : 'neg'}
        hint="TTM Squeeze sıkışma/momentum"
      />
    </div>
  )
}
