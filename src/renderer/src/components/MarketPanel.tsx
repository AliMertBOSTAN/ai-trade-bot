import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { MarketSnapshot } from '@shared/types'

const usd = (n: number, d = 2): string =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: d })

const compact = (n: number): string =>
  n >= 1e9 ? `$${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : usd(n, 0)

const pct = (n: number): string => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

function MarketCard({ m }: { m: MarketSnapshot }): JSX.Element {
  const { cex, dex, comparison } = m
  return (
    <div className="mcard">
      <div className="mcard-head">
        <span className="sym">{m.symbol}</span>
        {cex && (
          <span className={`chg ${cex.change_pct_24h >= 0 ? 'pos' : 'neg'}`}>
            {pct(cex.change_pct_24h)}
          </span>
        )}
      </div>

      <div className="mrow">
        <span className="mk">CEX (Binance)</span>
        <span className="mv">{cex ? usd(cex.price, cex.price < 10 ? 4 : 2) : '—'}</span>
      </div>
      <div className="mrow">
        <span className="mk">DEX{dex ? ` (${dex.dex})` : ''}</span>
        <span className="mv">{dex ? usd(dex.price_usd, dex.price_usd < 10 ? 4 : 2) : '—'}</span>
      </div>

      {comparison && (
        <div className={`mspread ${Math.abs(comparison.spread_bps) > 5 ? (comparison.spread_bps > 0 ? 'neg' : 'pos') : 'neu'}`}>
          Spread {comparison.spread_bps >= 0 ? '+' : ''}{comparison.spread_bps} bps · {comparison.note}
        </div>
      )}

      <div className="mmeta">
        {cex && <span>24s Hacim {compact(cex.volume_quote_24h)}</span>}
        {dex && <span>Likidite {compact(dex.liquidity_usd)}</span>}
        {cex?.order_book && (
          <span title="Emir defteri alış/satış baskısı">
            Defter {cex.order_book.imbalance >= 0 ? '🟢' : '🔴'}{' '}
            {(cex.order_book.imbalance * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {m.errors?.length > 0 && <div className="muted small">⚠ {m.errors.join(' · ')}</div>}
    </div>
  )
}

const SYMBOLS = 'ETH,BTC,BNB,MATIC,ARB,OP,LINK,UNI'

export default function MarketPanel({ active }: { active: boolean }): JSX.Element {
  const [data, setData] = useState<MarketSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await api.marketdata(SYMBOLS)
      setData(d)
      setErr(false)
    } catch {
      setErr(true)
    } finally {
      setLoading(false)
    }
  }, [])

  // Sadece sekme AÇIKKEN tazele. Sekme değişince panel mount kalır (App'te
  // gizlenir) → veriler durur; gizliyken arka planda istek atılmaz.
  useEffect(() => {
    if (!active) return
    load()
    const t = setInterval(load, 15000) // piyasa verisi 15 sn'de bir (ağ-yoğun)
    return () => clearInterval(t)
  }, [active, load])

  if (loading) return <div className="muted">piyasa verisi yükleniyor…</div>
  if (err && !data.length)
    return <div className="muted">piyasa verisine ulaşılamadı (engine + internet?)</div>

  return (
    <div className="mgrid">
      {data.map((m) => (
        <MarketCard key={m.symbol} m={m} />
      ))}
    </div>
  )
}
