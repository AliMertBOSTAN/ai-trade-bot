import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import TechnicalChart from './TechnicalChart'
import type { MarketDescriptor, MarketInstrument, MarketsResponse } from '@shared/types'

const CHAIN_NAMES: Record<number, string> = {
  1: 'Ethereum',
  42161: 'Arbitrum',
  8453: 'Base',
  10: 'Optimism',
  56: 'BNB',
  137: 'Polygon'
}

const usd = (n: number | null | undefined): string =>
  Number.isFinite(n)
    ? (n as number).toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: (n as number) < 10 ? 4 : 2
      })
    : '—'

const compact = (n: number | null | undefined): string => {
  if (!Number.isFinite(n)) return '—'
  const v = n as number
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

const pct = (n: number | null | undefined): string =>
  Number.isFinite(n) ? `${(n as number) >= 0 ? '+' : ''}${(n as number).toFixed(2)}%` : '—'

type SortKey = 'symbol' | 'market' | 'price' | 'change' | 'value'
type SortDir = 'asc' | 'desc'

function sortVal(i: MarketInstrument, key: SortKey): number | string {
  switch (key) {
    case 'symbol':
      return i.symbol
    case 'market':
      return i.venue || i.market
    case 'price':
      return i.price ?? 0
    case 'change':
      return i.change_pct_24h ?? -Infinity
    case 'value':
      return (i.liquidity_usd ?? i.volume_usd ?? 0) as number
  }
}

export default function ExplorePanel({ active }: { active: boolean }): JSX.Element {
  const [data, setData] = useState<MarketsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(false)
  const [q, setQ] = useState('')
  const [marketFilter, setMarketFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<SortKey>('value')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await api.markets())
      setErr(false)
    } catch {
      setErr(true)
    } finally {
      setLoading(false)
    }
  }, [])

  // Sadece sekme AÇIKKEN tazele. Sekme değişince panel mount kalır (App'te
  // gizlenir), bu yüzden veriler/filtreler durur; arka planda boşuna ağ isteği
  // atılmaz. Kapatınca (uygulama kapanınca) tüm state ile birlikte gider.
  useEffect(() => {
    if (!active) return
    load()
    const t = setInterval(load, 20000) // 20 sn'de bir tazele (ağ-yoğun)
    return () => clearInterval(t)
  }, [active, load])

  const toggleSort = (key: SortKey): void => {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir(key === 'symbol' || key === 'market' ? 'asc' : 'desc')
    }
  }

  const rows = useMemo(() => {
    if (!data) return []
    const needle = q.trim().toLowerCase()
    let list = data.instruments.filter((i) => {
      if (marketFilter !== 'all' && i.market !== marketFilter) return false
      if (needle && !i.symbol.toLowerCase().includes(needle)) return false
      return true
    })
    list = [...list].sort((a, b) => {
      const va = sortVal(a, sortKey)
      const vb = sortVal(b, sortKey)
      let c: number
      if (typeof va === 'string' || typeof vb === 'string') c = String(va).localeCompare(String(vb))
      else c = va - vb
      return sortDir === 'asc' ? c : -c
    })
    return list
  }, [data, q, marketFilter, sortKey, sortDir])

  if (loading) return <div className="muted">piyasalar yükleniyor…</div>
  if (err && !data) return <div className="muted">piyasa verisine ulaşılamadı (engine?)</div>

  const markets: MarketDescriptor[] = data?.markets ?? []
  const arrow = (k: SortKey): string => (k === sortKey ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')

  return (
    <div className="explore">
      {selected && (
        <div className="card explore-chart">
          <div className="explore-chart-head">
            <h3>{selected} · grafik</h3>
            <button className="xbtn" onClick={() => setSelected(null)}>
              ✕ kapat
            </button>
          </div>
          <TechnicalChart key={selected} symbol={selected} />
        </div>
      )}

      <div className="explore-bar">
        <input
          className="search"
          placeholder="🔎 token / sembol ara…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="mfilters">
          <button
            className={marketFilter === 'all' ? 'mf active' : 'mf'}
            onClick={() => setMarketFilter('all')}
          >
            Tümü <span className="muted small">{data?.instruments.length ?? 0}</span>
          </button>
          {markets.map((m) =>
            m.status === 'live' ? (
              <button
                key={m.id}
                className={marketFilter === m.id ? 'mf active' : 'mf'}
                onClick={() => setMarketFilter(m.id)}
              >
                {m.label}
              </button>
            ) : (
              <button key={m.id} className="mf soon" disabled title="Yakında eklenecek">
                {m.label} <span className="soon-badge">yakında</span>
              </button>
            )
          )}
        </div>
      </div>

      <div className="card explore-table">
        <div className="scroll" style={{ maxHeight: 520 }}>
          <table className="tbl">
            <thead>
              <tr>
                <th className="sortable" onClick={() => toggleSort('symbol')}>
                  Sembol{arrow('symbol')}
                </th>
                <th className="sortable" onClick={() => toggleSort('market')}>
                  Piyasa / Borsa{arrow('market')}
                </th>
                <th className="sortable num" onClick={() => toggleSort('price')}>
                  Fiyat{arrow('price')}
                </th>
                <th className="sortable num" onClick={() => toggleSort('change')}>
                  24s %{arrow('change')}
                </th>
                <th className="sortable num" onClick={() => toggleSort('value')}>
                  Likidite / Hacim{arrow('value')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i, idx) => (
                <tr
                  key={`${i.market}:${i.symbol}:${i.venue}:${idx}`}
                  className="clickrow"
                  onClick={() => setSelected(i.symbol)}
                  title={
                    i.kind === 'perp'
                      ? `Perp · funding ${(i.funding_pct ?? 0).toFixed(4)}%/sa · OI ${compact(i.open_interest_usd)} · grafiği aç`
                      : 'Grafiği aç (uygulama içi)'
                  }
                >
                  <td>
                    <b>{i.symbol}</b>
                    <span className="muted small">/{i.quote}</span>
                    {i.kind === 'perp' && i.max_leverage ? (
                      <span className="lev">{i.max_leverage}×</span>
                    ) : null}
                    {i.url ? (
                      <a
                        className="ext-link"
                        href={i.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        onClick={(e) => e.stopPropagation()}
                        title="DexScreener'da aç (yeni sekme)"
                      >
                        ↗
                      </a>
                    ) : null}
                  </td>
                  <td className="muted">
                    {i.venue || i.market}
                    {i.chain_id ? ` · ${CHAIN_NAMES[i.chain_id] ?? i.chain_id}` : ''}
                    {i.market_cap_usd ? ` · MC ${compact(i.market_cap_usd)}` : ''}
                    {i.url ? ' ↗' : ''}
                  </td>
                  <td className="num">{usd(i.price)}</td>
                  <td className={`num ${(i.change_pct_24h ?? 0) >= 0 ? 'pos' : 'neg'}`}>
                    {pct(i.change_pct_24h)}
                  </td>
                  <td className="num muted">{compact(i.liquidity_usd ?? i.volume_usd)}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={5} className="muted">
                    eşleşen enstrüman yok
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div className="muted small explore-foot">
        {rows.length} enstrüman · bir satıra tıkla → mum grafiği + göstergeler
      </div>
    </div>
  )
}
