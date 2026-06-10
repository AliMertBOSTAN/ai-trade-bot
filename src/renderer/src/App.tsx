import { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectEvents } from './api'
import EquityChart from './components/EquityChart'
import type {
  ArbitrageOpportunity,
  MarketSnapshot,
  NewsItem,
  BotState,
  PortfolioSnapshot,
  PriceQuote,
  TradeOrder,
  TradeSignal
} from '@shared/types'

const CHAIN_NAMES: Record<number, string> = {
  1: 'Ethereum',
  42161: 'Arbitrum',
  8453: 'Base',
  10: 'Optimism',
  56: 'BNB',
  137: 'Polygon'
}

const CHAIN_COLORS: Record<number, string> = {
  1: '#8aa0ff',
  42161: '#2d9cdb',
  8453: '#3773f5',
  10: '#ff4757',
  56: '#f3ba2f',
  137: '#8247e5'
}

const timeAgo = (ts: number): string => {
  if (!ts) return ''
  const m = Math.max(0, Math.round((Date.now() - ts) / 60000))
  if (m < 60) return `${m}dk`
  if (m < 1440) return `${Math.round(m / 60)}sa`
  return `${Math.round(m / 1440)}g`
}

const usd = (n: number): string =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })

export default function App(): JSX.Element {
  const [state, setState] = useState<BotState>({ status: 'stopped', mode: 'paper', lastTick: 0 })
  const [prices, setPrices] = useState<PriceQuote[]>([])
  const [arbs, setArbs] = useState<ArbitrageOpportunity[]>([])
  const [signals, setSignals] = useState<TradeSignal[]>([])
  const [trades, setTrades] = useState<TradeOrder[]>([])
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [equity, setEquity] = useState<{ t: number; equity: number }[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [market, setMarket] = useState<MarketSnapshot[]>([])
  const [news, setNews] = useState<NewsItem[]>([])
  const [connected, setConnected] = useState(false)
  const logRef = useRef<string[]>([])

  const pushLog = useCallback((msg: string) => {
    logRef.current = [`${new Date().toLocaleTimeString()}  ${msg}`, ...logRef.current].slice(0, 60)
    setLogs([...logRef.current])
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [s, pr, ar, sg, tr, pf, eq] = await Promise.all([
        api.state(),
        api.prices(),
        api.arbitrage(),
        api.signals(),
        api.trades(50),
        api.portfolio(),
        api.equity()
      ])
      setState(s)
      setPrices(pr)
      setArbs(ar)
      setSignals(sg)
      setTrades(tr)
      setPortfolio(pf)
      setEquity(eq)
      setConnected(true)
    } catch {
      setConnected(false)
    }
  }, [])

  const refreshMarket = useCallback(async () => {
    try {
      const [md, nw] = await Promise.all([api.marketdata('ETH,BTC,ARB,OP'), api.news(10)])
      setMarket(md)
      setNews(nw)
    } catch {
      /* engine kapalıysa sessiz geç */
    }
  }, [])

  useEffect(() => {
    refresh()
    refreshMarket()
    const poll = setInterval(refresh, 5000)
    const pollMd = setInterval(refreshMarket, 30000)
    const off = connectEvents((e) => {
      if (e.type === 'tick') setState(e.state)
      else if (e.type === 'signal') setSignals((p) => [e.signal, ...p].slice(0, 40))
      else if (e.type === 'trade') setTrades((p) => [e.order, ...p].slice(0, 50))
      else if (e.type === 'arbitrage') setArbs((p) => [e.opp, ...p].slice(0, 20))
      else if (e.type === 'log') pushLog(`[${e.level}] ${e.message}`)
    })
    return () => {
      clearInterval(poll)
      clearInterval(pollMd)
      off()
    }
  }, [refresh, refreshMarket, pushLog])

  const toggleRun = async (): Promise<void> => {
    const s = state.status === 'running' ? await api.stop() : await api.start()
    setState(s)
    pushLog(s.status === 'running' ? 'Bot başlatıldı' : 'Bot durduruldu')
  }

  const switchMode = async (mode: 'paper' | 'live'): Promise<void> => {
    try {
      const s = await api.setMode(mode)
      setState(s)
      pushLog(`Mod -> ${mode.toUpperCase()}`)
      if (s.message) pushLog(`UYARI: ${s.message}`)
    } catch (err) {
      pushLog(`Mod değişimi başarısız: ${(err as Error).message}`)
    }
  }

  const equityVal = portfolio?.equityUsd ?? 0
  const pnl = (portfolio?.realizedPnlUsd ?? 0) + (portfolio?.unrealizedPnlUsd ?? 0)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">⬡</span> AI Trade Bot
          <span className={`badge ${state.mode}`}>{state.mode.toUpperCase()}</span>
        </div>
        <div className="controls">
          <span className={`dot ${connected ? 'on' : 'off'}`} />
          <span className="muted">{connected ? 'engine bağlı' : 'engine yok (uvicorn?)'}</span>
          <div className="seg">
            <button className={state.mode === 'paper' ? 'active' : ''} onClick={() => switchMode('paper')}>
              Paper
            </button>
            <button className={state.mode === 'live' ? 'active live' : ''} onClick={() => switchMode('live')}>
              Live
            </button>
          </div>
          <button className={`run ${state.status}`} onClick={toggleRun}>
            {state.status === 'running' ? '■ Durdur' : '▶ Başlat'}
          </button>
        </div>
      </header>

      <section className="kpis">
        <Kpi label="Equity" value={usd(equityVal)} />
        <Kpi label="Nakit" value={usd(portfolio?.cashUsd ?? 0)} />
        <Kpi label="Toplam PnL" value={usd(pnl)} accent={pnl >= 0 ? 'pos' : 'neg'} />
        <Kpi label="Açık Pozisyon" value={String(portfolio?.positions.length ?? 0)} />
        <Kpi label="Fırsat (arb)" value={String(arbs.length)} />
      </section>

      <div className="grid">
        <div className="card span2">
          <h3>Equity Eğrisi</h3>
          <div className="chartbox">
            <EquityChart data={equity} />
          </div>
        </div>

        <div className="card">
          <h3>Portföy</h3>
          <table className="tbl">
            <thead>
              <tr>
                <th>Zincir</th>
                <th>Token</th>
                <th>Adet</th>
                <th>Giriş</th>
                <th>PnL</th>
              </tr>
            </thead>
            <tbody>
              {portfolio?.positions.length ? (
                portfolio.positions.map((p) => (
                  <tr key={p.key}>
                    <td><Chain id={p.chainId} /></td>
                    <td>{p.base}</td>
                    <td>{p.amount.toFixed(4)}</td>
                    <td>{usd(p.avgEntry)}</td>
                    <td className={p.unrealizedPnlUsd >= 0 ? 'pos' : 'neg'}>
                      {usd(p.unrealizedPnlUsd)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="muted">
                    pozisyon yok
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card span2">
          <h3>Çoklu-Zincir Fiyatlar</h3>
          <div className="scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Token</th>
                  <th>Zincir</th>
                  <th>DEX</th>
                  <th>Fiyat</th>
                  <th>Likidite</th>
                </tr>
              </thead>
              <tbody>
                {prices.map((q, i) => (
                  <tr key={i}>
                    <td>
                      <b>{q.base}</b>/{q.quote}
                    </td>
                    <td><Chain id={q.chainId} /></td>
                    <td>{q.dex}</td>
                    <td>{usd(q.price)}</td>
                    <td className="muted">{usd(q.liquidityUsd)}</td>
                  </tr>
                ))}
                {!prices.length && (
                  <tr>
                    <td colSpan={5} className="muted">
                      veri bekleniyor…
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Arbitraj Fırsatları</h3>
          <div className="scroll">
            {arbs.length ? (
              arbs.map((o) => (
                <div className="arb" key={o.id}>
                  <div className="arb-top">
                    <b>{o.base}</b>
                    <span className="pos">+{usd(o.estNetProfitUsd)}</span>
                  </div>
                  <div className="muted small">
                    Al {CHAIN_NAMES[o.buyChain]} {o.buyDex} @ {usd(o.buyPrice)} → Sat{' '}
                    {CHAIN_NAMES[o.sellChain]} {o.sellDex} @ {usd(o.sellPrice)} ·{' '}
                    {o.spreadPct.toFixed(2)}%
                  </div>
                </div>
              ))
            ) : (
              <div className="muted">fırsat yok</div>
            )}
          </div>
        </div>

        <div className="card">
          <h3>Sinyaller (hibrit)</h3>
          <div className="scroll">
            {signals.map((s) => (
              <div className="sig" key={s.id}>
                <span className={`tag ${s.action.toLowerCase()}`}>{s.action}</span>
                <b>{s.base}</b>
                <span className="muted small">
                  {(s.confidence * 100).toFixed(0)}% · {s.source} · {s.rationale}
                </span>
              </div>
            ))}
            {!signals.length && <div className="muted">sinyal yok</div>}
          </div>
        </div>

        <div className="card">
          <h3>Piyasa — CEX vs DEX</h3>
          <div className="scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Token</th>
                  <th>Binance</th>
                  <th>DEX</th>
                  <th>Spread</th>
                  <th>24s</th>
                </tr>
              </thead>
              <tbody>
                {market.map((m) => (
                  <tr key={m.symbol}>
                    <td>
                      <b>{m.symbol}</b>
                    </td>
                    <td>{m.cex ? usd(m.cex.price) : <span className="muted">—</span>}</td>
                    <td>
                      {m.dex ? (
                        <span title={m.dex.pair}>
                          {usd(m.dex.price_usd)} <span className="muted small">{m.dex.dex}</span>
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {m.comparison ? (
                        <span
                          className={`spread ${
                            Math.abs(m.comparison.spread_bps) <= 5
                              ? 'ok'
                              : m.comparison.spread_bps > 0
                                ? 'dexp'
                                : 'cexp'
                          }`}
                        >
                          {m.comparison.spread_bps > 0 ? '+' : ''}
                          {m.comparison.spread_bps.toFixed(1)} bps
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className={m.cex && m.cex.change_pct_24h >= 0 ? 'pos' : 'neg'}>
                      {m.cex ? `${m.cex.change_pct_24h >= 0 ? '+' : ''}${m.cex.change_pct_24h.toFixed(2)}%` : ''}
                    </td>
                  </tr>
                ))}
                {!market.length && (
                  <tr>
                    <td colSpan={5} className="muted">
                      açık piyasa verisi bekleniyor…
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Anlık Haberler</h3>
          <div className="scroll">
            {news.map((n, i) => (
              <div className="news-item" key={i}>
                <a href={n.link} target="_blank" rel="noreferrer">
                  {n.title}
                </a>
                <div className="news-meta">
                  <span className="news-src">{n.source.replace(/\.(com|co|io)$/, '')}</span>
                  <span className="muted small">{timeAgo(n.ts)}</span>
                </div>
              </div>
            ))}
            {!news.length && <div className="muted">haber akışı bekleniyor…</div>}
          </div>
        </div>

        <div className="card span2">
          <h3>İşlemler</h3>
          <div className="scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Zaman</th>
                  <th>Mod</th>
                  <th>Yön</th>
                  <th>Token</th>
                  <th>Adet</th>
                  <th>Fiyat</th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td className="muted small">{new Date(t.timestamp).toLocaleTimeString()}</td>
                    <td>{t.mode}</td>
                    <td className={t.side === 'BUY' ? 'pos' : 'neg'}>{t.side}</td>
                    <td>{t.base}</td>
                    <td>{t.amount.toFixed(4)}</td>
                    <td>{usd(t.filledPrice || t.price)}</td>
                    <td className={t.status === 'filled' ? 'pos' : t.status === 'failed' ? 'neg' : ''}>
                      {t.status}
                    </td>
                  </tr>
                ))}
                {!trades.length && (
                  <tr>
                    <td colSpan={7} className="muted">
                      işlem yok
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Log</h3>
          <div className="scroll logbox">
            {logs.map((l, i) => (
              <div key={i} className="logline">
                {l}
              </div>
            ))}
            {!logs.length && <div className="muted">—</div>}
          </div>
        </div>
      </div>
    </div>
  )
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: 'pos' | 'neg' }): JSX.Element {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-val ${accent ?? ''}`}>{value}</div>
    </div>
  )
}

function Chain({ id }: { id: number }): JSX.Element {
  return (
    <span className="chain">
      <i style={{ background: CHAIN_COLORS[id] ?? '#6b7689' }} />
      {CHAIN_NAMES[id] ?? id}
    </span>
  )
}
