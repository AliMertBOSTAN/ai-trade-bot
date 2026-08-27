// Piyasa İstihbaratı panellerinin ortak yapı taşları.
// Amaç: her widget aynı iskeleti kullansın — başlık + kaynak rozeti + boş/hata
// durumu tek yerde çözülsün. Böylece "veri yok" hâli her panelde tutarlı görünür.
import type { JSX, ReactNode } from 'react'
import type { IntelBase } from '@shared/types'

/** Büyük sayıları kısaltır: 1.23B / 45.6M / 789K. */
export function compact(n: number | null | undefined, prefix = '$'): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const a = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (a >= 1e12) return `${sign}${prefix}${(a / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${sign}${prefix}${(a / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${sign}${prefix}${(a / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${sign}${prefix}${(a / 1e3).toFixed(1)}K`
  return `${sign}${prefix}${a.toFixed(2)}`
}

/** Yüzde biçimi, işaretli. */
export function pct(n: number | null | undefined, digits = 2): string {
  return n == null || !Number.isFinite(n) ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

/** Sayı işaretine göre CSS sınıfı (yeşil / kırmızı / nötr). */
export function sign(n: number | null | undefined, flip = false): string {
  if (n == null || !Number.isFinite(n) || n === 0) return 'muted'
  const positive = flip ? n < 0 : n > 0
  return positive ? 'pos' : 'neg'
}

export function timeAgo(seconds: number | null | undefined): string {
  if (seconds == null) return 'hiç'
  if (seconds < 60) return `${Math.round(seconds)} sn önce`
  if (seconds < 3600) return `${Math.round(seconds / 60)} dk önce`
  return `${(seconds / 3600).toFixed(1)} sa önce`
}

/** Minik çizgi grafik (sparkline) — bağımlılık yok, saf SVG. */
export function Spark({
  values,
  width = 84,
  height = 24,
  invert = false
}: {
  values: number[] | undefined
  width?: number
  height?: number
  /** true: düşüş yeşil (ör. borsa rezervi). */
  invert?: boolean
}): JSX.Element | null {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const d = values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`)
    .join(' ')
  const up = values[values.length - 1] >= values[0]
  const good = invert ? !up : up
  return (
    <svg className="ispark" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={d} fill="none" strokeWidth="1.5" className={good ? 'sp-pos' : 'sp-neg'} />
    </svg>
  )
}

/** 0..100 ölçeğinde ölçüm çubuğu (korku endeksi, risk modu). */
export function Gauge({ value, max = 100 }: { value: number; max?: number }): JSX.Element {
  const p = Math.max(0, Math.min(100, (value / max) * 100))
  const tone = p >= 62 ? 'pos' : p <= 38 ? 'neg' : 'neu'
  return (
    <div className={`igauge ${tone}`}>
      <div className="igauge-fill" style={{ width: `${p}%` }} />
      <div className="igauge-mark" style={{ left: '50%' }} />
    </div>
  )
}

/** -1..+1 skoru için ortadan iki yöne büyüyen çubuk. */
export function BiasBar({ score }: { score: number }): JSX.Element {
  const s = Math.max(-1, Math.min(1, score))
  const w = Math.abs(s) * 50
  return (
    <div className="ibias">
      <div className="ibias-zero" />
      <div
        className={`ibias-fill ${s >= 0 ? 'pos' : 'neg'}`}
        style={s >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }}
      />
    </div>
  )
}

/** Panelin kaynağını / vekil uyarısını gösteren küçük rozet. */
export function SourceTag({ data }: { data: IntelBase | undefined }): JSX.Element | null {
  if (!data?.source) return null
  const proxy = data.source === 'proxy'
  return (
    <span className={`isrc ${proxy ? 'warn' : ''}`} title={data.disclaimer || data.source}>
      {proxy ? 'vekil' : data.source}
    </span>
  )
}

/**
 * Widget kabuğu. `data.ok === false` ise içerik yerine gerekçe gösterir —
 * böylece "anahtar yok" ile "upstream düştü" ayırt edilebilir kalır.
 */
export function Widget({
  title,
  hint,
  data,
  right,
  wide,
  children
}: {
  title: string
  hint?: string
  data?: IntelBase
  right?: ReactNode
  wide?: boolean
  children: ReactNode
}): JSX.Element {
  const failed = data && data.ok === false
  const why = data?.reason || data?.error
  return (
    <section className={`card iwidget${wide ? ' span2' : ''}`}>
      <div className="card-head">
        <h3 title={hint}>{title}</h3>
        <div className="iwidget-right">
          <SourceTag data={data} />
          {right}
        </div>
      </div>
      {failed ? (
        <div className="iempty">
          <span className="iempty-ico">○</span>
          <span>{why || 'veri yok'}</span>
        </div>
      ) : (
        children
      )}
    </section>
  )
}

/** Etiket + değer satırı. */
export function Row({
  label,
  value,
  tone,
  sub
}: {
  label: ReactNode
  value: ReactNode
  tone?: string
  sub?: ReactNode
}): JSX.Element {
  return (
    <div className="irow">
      <span className="irow-l">
        {label}
        {sub && <em className="irow-sub">{sub}</em>}
      </span>
      <span className={`irow-v ${tone || ''}`}>{value}</span>
    </div>
  )
}

/** Büyük tek sayı (KPI). */
export function Stat({
  label,
  value,
  tone,
  sub
}: {
  label: string
  value: ReactNode
  tone?: string
  sub?: ReactNode
}): JSX.Element {
  return (
    <div className="istat">
      <div className="istat-l">{label}</div>
      <div className={`istat-v ${tone || ''}`}>{value}</div>
      {sub && <div className="istat-s">{sub}</div>}
    </div>
  )
}
