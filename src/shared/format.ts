// Paylaşılan, saf (yan etkisiz) biçimlendirme yardımcıları.
// Bileşenlerde tekrarlanan usd/pct/compact mantığı burada toplandı → test edilebilir.

/** ABD doları biçimi. Küçük fiyatlarda (<10) daha çok ondalık gösterir. */
export function usd(n: number | null | undefined, digits?: number): string {
  if (!Number.isFinite(n)) return '—'
  const v = n as number
  const d = digits ?? (Math.abs(v) < 10 ? 4 : 2)
  return v.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: d
  })
}

/** Büyük sayıları kısaltır: 1.2B / 3.4M / 5.6K / $789. */
export function compact(n: number | null | undefined): string {
  if (!Number.isFinite(n)) return '—'
  const v = n as number
  const sign = v < 0 ? '-' : ''
  const a = Math.abs(v)
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`
  return `${sign}$${a.toFixed(0)}`
}

/** Yüzde değişimi işaretli gösterir: +2.50% / -1.30%. */
export function pct(n: number | null | undefined): string {
  if (!Number.isFinite(n)) return '—'
  const v = n as number
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

/** Sinyal güvenini 0..1'den 0..100 tam sayıya çevirir. */
export function toConfPct(confidence: number, finalConfidence?: number): number {
  return Math.round((finalConfidence ?? confidence) * 100)
}
