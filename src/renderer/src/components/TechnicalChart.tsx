import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  type WhitespaceData
} from 'lightweight-charts'
import { api } from '../api'
import type { ChartFeed } from '@shared/types'

const INTERVALS = ['15m', '1h', '4h', '1d'] as const
type Interval = (typeof INTERVALS)[number]

const sec = (ms: number): UTCTimestamp => Math.floor(ms / 1000) as UTCTimestamp

const ACTION_COLOR: Record<string, string> = {
  BUY: '#34d399',
  SELL: '#f87171',
  HOLD: '#9fb0c9'
}

export default function TechnicalChart(
  { symbol: initialSymbol }: { symbol?: string } = {}
): JSX.Element {
  const boxRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const emaFastRef = useRef<ISeriesApi<'Line'> | null>(null)
  const emaSlowRef = useRef<ISeriesApi<'Line'> | null>(null)
  const bbUpRef = useRef<ISeriesApi<'Line'> | null>(null)
  const bbMidRef = useRef<ISeriesApi<'Line'> | null>(null)
  const bbLowRef = useRef<ISeriesApi<'Line'> | null>(null)
  const stUpRef = useRef<ISeriesApi<'Line'> | null>(null)
  const stDownRef = useRef<ISeriesApi<'Line'> | null>(null)

  const [interval, setInterval_] = useState<Interval>('1h')
  const [feed, setFeed] = useState<ChartFeed | null>(null)
  const [err, setErr] = useState(false)
  // Boşsa backend aktif sembolü (son sinyal/pozisyon) izler; doluysa o token.
  // initialSymbol verilirse (örn. Keşfet'ten tıklama) o sembolle açılır.
  const [symInput, setSymInput] = useState(initialSymbol ?? '')
  const [symbol, setSymbol] = useState<string | undefined>(initialSymbol)

  // --- veri çekimi ---
  useEffect(() => {
    let alive = true
    const load = async (): Promise<void> => {
      try {
        const f = await api.chart(symbol, interval)
        if (alive) {
          setFeed(f)
          setErr(false)
        }
      } catch {
        if (alive) setErr(true)
      }
    }
    load()
    const t = window.setInterval(load, 20000) // klines TTL 30s; 20s'de bir tazele
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [interval, symbol])

  const applySymbol = (): void => {
    const s = symInput.trim().toUpperCase()
    setSymbol(s || undefined)
  }

  // --- chart'ı bir kez kur (StrictMode'a dayanıklı temizlik) ---
  useEffect(() => {
    if (!boxRef.current) return
    const chart = createChart(boxRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#5b6680',
        fontSize: 11
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.045)' }
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.07)' },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.07)',
        timeVisible: true,
        secondsVisible: false
      },
      crosshair: { mode: CrosshairMode.Normal }
    })
    chartRef.current = chart

    candleRef.current = chart.addCandlestickSeries({
      upColor: '#34d399',
      downColor: '#f87171',
      borderVisible: false,
      wickUpColor: '#34d399',
      wickDownColor: '#f87171'
    })
    const line = (color: string, width: 1 | 2, style = LineStyle.Solid): ISeriesApi<'Line'> =>
      chart.addLineSeries({
        color,
        lineWidth: width,
        lineStyle: style,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false
      })
    bbUpRef.current = line('rgba(159,176,201,0.30)', 1, LineStyle.Dashed)
    bbLowRef.current = line('rgba(159,176,201,0.30)', 1, LineStyle.Dashed)
    bbMidRef.current = line('rgba(159,176,201,0.18)', 1)
    emaFastRef.current = line('#6aa6ff', 2)
    emaSlowRef.current = line('#f0b35b', 2)
    stUpRef.current = line('#34d399', 2)
    stDownRef.current = line('#f87171', 2)

    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      emaFastRef.current = emaSlowRef.current = null
      bbUpRef.current = bbMidRef.current = bbLowRef.current = null
      stUpRef.current = stDownRef.current = null
    }
  }, [])

  // --- feed değişince serileri güncelle ---
  useEffect(() => {
    const chart = chartRef.current
    const candle = candleRef.current
    if (!chart || !candle || !feed || !feed.candles.length) return

    candle.setData(
      feed.candles.map<CandlestickData>((c) => ({
        time: sec(c.t),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close
      }))
    )

    const toLine = (pts: { t: number; value: number }[]): LineData[] =>
      pts.map((p) => ({ time: sec(p.t), value: p.value }))
    emaFastRef.current?.setData(toLine(feed.overlays.emaFast))
    emaSlowRef.current?.setData(toLine(feed.overlays.emaSlow))
    bbUpRef.current?.setData(toLine(feed.overlays.bbUpper))
    bbMidRef.current?.setData(toLine(feed.overlays.bbMid))
    bbLowRef.current?.setData(toLine(feed.overlays.bbLower))

    // Supertrend: yöne göre yeşil/kırmızı iki seri (diğer yönde whitespace=boşluk)
    const st = feed.overlays.supertrend
    const stUp: (LineData | WhitespaceData)[] = st.map((p) =>
      p.dir > 0 ? { time: sec(p.t), value: p.value } : { time: sec(p.t) }
    )
    const stDown: (LineData | WhitespaceData)[] = st.map((p) =>
      p.dir < 0 ? { time: sec(p.t), value: p.value } : { time: sec(p.t) }
    )
    stUpRef.current?.setData(stUp)
    stDownRef.current?.setData(stDown)

    // Geçmiş al/sat işaretleri (kural-tabanlı kararın dönüş noktaları)
    candle.setMarkers(
      feed.markers.map<SeriesMarker<Time>>((m) => ({
        time: sec(m.t),
        position: m.action === 'BUY' ? 'belowBar' : 'aboveBar',
        color: m.action === 'BUY' ? '#34d399' : '#f87171',
        shape: m.action === 'BUY' ? 'arrowUp' : 'arrowDown',
        text: m.action
      }))
    )

    chart.timeScale().fitContent()
  }, [feed])

  const sig = feed?.signal
  return (
    <div className="tachart">
      <div className="tachart-head">
        <div className="tachart-sym">
          {feed ? `${feed.symbol}/${feed.quote}` : 'yükleniyor…'}
          {feed?.source && (
            <span className="tachart-src" title="OHLCV veri kaynağı">
              {feed.source === 'coingecko' ? 'CoinGecko' : 'Binance'}
            </span>
          )}
          {sig && (
            <span
              className="tachart-sig"
              style={{ color: ACTION_COLOR[sig.action] }}
              title={sig.rationale}
            >
              {sig.action} · %{Math.round(sig.confidence * 100)}
            </span>
          )}
        </div>
        <div className="tachart-ctrl">
          <input
            className="tachart-input"
            value={symInput}
            placeholder={symbol ? symbol : 'oto (token ara)'}
            onChange={(e) => setSymInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && applySymbol()}
            onBlur={applySymbol}
            spellCheck={false}
          />
          <div className="tachart-iv">
            {INTERVALS.map((iv) => (
              <button
                key={iv}
                className={iv === interval ? 'active' : ''}
                onClick={() => setInterval_(iv)}
              >
                {iv}
              </button>
            ))}
          </div>
        </div>
      </div>
      {sig && <div className="tachart-note muted">{sig.rationale}</div>}
      {feed && !feed.candles.length && (
        <div className="tachart-note muted">{feed.note ?? 'mum verisi yok'}</div>
      )}
      {err && !feed && <div className="muted">chart verisi alınamadı (engine?)</div>}
      <div ref={boxRef} className="tachart-canvas" />
    </div>
  )
}
