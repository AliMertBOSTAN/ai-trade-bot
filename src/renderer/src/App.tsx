import { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectEvents } from './api'
import EquityChart from './components/EquityChart'
import TechnicalChart from './components/TechnicalChart'
import Indicators from './components/Indicators'
import MarketPanel from './components/MarketPanel'
import NewsPanel from './components/NewsPanel'
import AnalystPanel from './components/AnalystPanel'
import type {
  ArbitrageOpportunity,
  BotState,
  GasInfo,
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

type Tab = 'overview' | 'market' | 'signals' | 'arbitrage' | 'news' | 'analyst' | 'trades'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Genel' },
  { id: 'market', label: 'Piyasa' },
  { id: 'signals', label: 'Sinyaller' },
  { id: 'arbitrage', label: 'Arbitraj' },
  { id: 'news', label: 'Haberler' },
  { id: 'analyst', label: 'AI Analist' },
  { id: 'trades', label: 'İşlemler' }
]

const usd = (n: number | null | undefined): string =>
  Number.isFinite(n)
    ? (n as number).toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2
      })
    : '—'

export default function App(): JSX.Element {
  const [state, setState] = useState<BotState>({ status: 'stopped', mode: 'paper', lastTick: 0 })
  const [prices, setPrices] = useState<PriceQuote[]>([])
  const [arbs, setArbs] = useState<ArbitrageOpportunity[]>([])
  const [signals, setSignals] = useState<TradeSignal[]>([])
  const [trades, setTrades] = useState<TradeOrder[]>([])
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [equity, setEquity] = useState<{ t: number; equity: number }[]>([])
  const [gas, setGas] = useState<GasInfo[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [tab, setTab] = useState<Tab>('overview')
  const logRef = useRef<string[]>([])

  const pushLog = useCallback((msg: string) => {
    logRef.current = [`${new Date().toLocaleTimeString()}  ${msg}`, ...logRef.current].slice(0, 80)
    setLogs([...logRef.current])
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [s, pr, ar, sg, tr, pf, eq] = await Promise.all([
        api.state(),
        api.prices(),
        api.arbitrage(),
        api.signals(),
        api.trades(60),
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

  const refreshGas = useCallback(async () => {
    try {
      setGas(await api.gas())
    } catch {
      /* gas opsiyonel */
    }
  }, [])

  useEffect(() => {
    refresh()
    refreshGas()
    const poll = setInterval(refresh, 5000)
    const gasPoll = setInterval(refreshGas, 15000)
    const off = connectEvents((e) => {
      if (e.type === 'tick') setState(e.state)
      else if (e.type === 'signal') setSignals((p) => [e.signal, ...p].slice(0, 40))
      else if (e.type === 'trade') {
        setTrades((p) => [e.order, ...p].slice(0, 60))
        const o = e.order
        pushLog(
          `İŞLEM ${o.side} ${o.amount.toFixed(4)} ${o.base} @ ${usd(o.filledPrice || o.price)}` +
            (o.reason ? ` — ${o.reason}` : '')
        )
      }
      else if (e.type === 'arbitrage') setArbs((p) => [e.opp, ...p].slice(0, 20))
      else if (e.type === 'log') pushLog(`[${e.level}] ${e.message}`)
    })
    return () => {
      clearInterval(poll)
      clearInterval(gasPoll)
      off()
    }
  }, [refresh, refreshGas, pushLog])

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
  const ethGas = gas.find((g) => g.chain_id === 1) ?? gas[0]

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◆</span> AI Trade Bot
          <span className={`badge ${state.mode}`}>{state.mode.toUpperCase()}</span>
        </div>
        <div className="controls">
          {ethGas && (
            <span className="gaschip" title="Canlı gas (ETH)">
              ⛽ {ethGas.gwei} gwei · {usd(ethGas.swap_usd)}
            </span>
          )}
          <span className={`dot ${connected ? 'on' : 'off'}`} />
          <span className="muted">{connected ? 'engine bağlı' : 'engine yok (uvicorn?)'}</span>
          <div className="seg">
            <button className={state.mode === 'paper' ? 'active' : ''} onClick={() => switchMode('paper')}>
              Paper
            </button>
            <button
              className={state.mode === 'live' ? 'active live' : ''}
              onClick={() => switchMode('live')}
            >
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
        <Kpi label="Gas (ETH)" value={ethGas ? `${ethGas.gwei} gwei` : '—'} />
      </section>

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? 'tab active' : 'tab'}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === 'arbitrage' && arbs.length > 0 && <span className="pill">{arbs.length}</span>}
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === 'overview' && (
          <Overview equity={equity} portfolio={portfolio} prices={prices} gas={gas} />
        )}
        {tab === 'market' && <MarketPanel />}
        {tab === 'signals' && <SignalsView signals={signals} />}
        {tab === 'arbitrage' && <ArbitrageView arbs={arbs} />}
        {tab === 'news' && <NewsPanel />}
        {tab === 'analyst' && <AnalystPanel />}
        {tab === 'trades' && <TradesView trades={trades} logs={logs} />}
      </main>
    </div>
  )
}

function Overview({
  equity,
  portfolio,
  prices,
  gas
}: {
  equity: { t: number; equity: number }[]
  portfolio: PortfolioSnapshot | null
  prices: PriceQuote[]
  gas: GasInfo[]
}): JSX.Element {
  return (
    <div className="grid">
      <div className="card">
        <h3>Equity Eğrisi</h3>
        <div className="chartbox">
          <EquityChart data={equity} />
        </div>
      </div>

      <div className="card">
        <h3>Teknik Analiz</h3>
        <div className="chartbox">
          <TechnicalChart />
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
                  <td>{CHAIN_NAMES[p.chainId] ?? p.chainId}</td>
                  <td>{p.base}</td>
                  <td>{p.amount.toFixed(4)}</td>
                  <td>{usd(p.avgEntry)}</td>
                  <td className={p.unrealizedPnlUsd >= 0 ? 'pos' : 'neg'}>{usd(p.unrealizedPnlUsd)}</td>
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

      <div className="card">
        <h3>Canlı Gas</h3>
        <div className="gaslist">
          {gas.length ? (
            gas.map((g) => (
              <div className="gasrow" key={g.chain_id}>
                <span>{g.chain}</span>
                <span className="muted">{g.gwei} gwei</span>
                <span className="mono">{usd(g.swap_usd)}</span>
              </div>
            ))
          ) : (
            <div className="muted">gas verisi yok</div>
          )}
        </div>
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
                  <td>{CHAIN_NAMES[q.chainId] ?? q.chainId}</td>
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
    </div>
  )
}

const TRADE_THRESHOLD = 80 // emin olma eşiği (%) — üzerindekilere işlem açılır

function SignalBreakdownView({ s }: { s: TradeSignal }): JSX.Element | null {
  const b = s.breakdown
  if (!b) return null
  const conf = Math.round(b.finalConfidence * 100)
  const willTrade = conf >= TRADE_THRESHOLD && s.action !== 'HOLD'
  const techPct = Math.round(b.technicalScore * 100)
  const newsCls = b.newsLabel === 'pozitif' ? 'pos' : b.newsLabel === 'negatif' ? 'neg' : 'muted'
  return (
    <div className="sig-bd">
      <div className="sig-bd-row">
        <span className="sig-bd-k">Teknik</span>
        <div className="sig-bd-bar">
          <div className="sig-bd-fill tech" style={{ width: `${techPct}%` }} />
        </div>
        <span className="sig-bd-v">
          {techPct}% <span className="muted">×{b.weights.technical}</span>
        </span>
      </div>
      <div className="sig-bd-row">
        <span className="sig-bd-k">Haber</span>
        <span className={`sig-bd-v ${newsCls}`}>
          {b.newsLabel} ({b.newsScore >= 0 ? '+' : ''}
          {b.newsScore.toFixed(2)})
        </span>
        <span className="muted small">
          {b.newsCount} başlık{b.newsMarket ? ' · piyasa geneli' : ` · ${b.newsMatched} ${s.base}`} ·
          ×{b.weights.news}
        </span>
      </div>
      {b.llmUsed && (
        <div className="sig-bd-row">
          <span className="sig-bd-k">LLM</span>
          <span className="sig-bd-v muted small">{b.llmNote}</span>
        </div>
      )}
      <div className={`sig-bd-final ${willTrade ? 'pos' : 'muted'}`}>
        Emin olma: <b>{conf}%</b> {willTrade ? '✓ işlem açılır' : `· eşik %${TRADE_THRESHOLD} altı`}
      </div>
      {b.newsHeadlines.length > 0 && (
        <div className="sig-bd-news">
          {b.newsHeadlines.map((h, i) => (
            <div key={i} className="muted small">
              • {h}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SignalsView({ signals }: { signals: TradeSignal[] }): JSX.Element {
  if (!signals.length) return <div className="muted card">sinyal yok — bot çalışıyor mu?</div>
  return (
    <div className="siglist">
      {signals.slice(0, 16).map((s) => {
        const conf = Math.round((s.breakdown?.finalConfidence ?? s.confidence) * 100)
        const willTrade = conf >= TRADE_THRESHOLD && s.action !== 'HOLD'
        return (
          <div className={`sigcard ${willTrade ? 'trade' : ''}`} key={s.id}>
            <div className="sigcard-head">
              <span className={`tag ${s.action.toLowerCase()}`}>{s.action}</span>
              <b>{s.base}</b>
              <span className={`sig-conf ${willTrade ? 'pos' : 'muted'}`}>{conf}%</span>
              <span className="muted small">{s.source}</span>
            </div>
            <SignalBreakdownView s={s} />
            <Indicators tech={s.technical} />
          </div>
        )
      })}
    </div>
  )
}

function ArbitrageView({ arbs }: { arbs: ArbitrageOpportunity[] }): JSX.Element {
  if (!arbs.length) return <div className="muted card">fırsat yok (gas + slippage düşülmüş net)</div>
  return (
    <div className="arblist">
      {arbs.map((o) => (
        <div className="arb card" key={o.id}>
          <div className="arb-top">
            <b>{o.base}</b>
            <span className="pos">+{usd(o.estNetProfitUsd)}</span>
            <span className="muted small">net · {o.spreadPct.toFixed(2)}% spread</span>
          </div>
          <div className="muted small">
            Al {CHAIN_NAMES[o.buyChain] ?? o.buyChain} {o.buyDex} @ {usd(o.buyPrice)} → Sat{' '}
            {CHAIN_NAMES[o.sellChain] ?? o.sellChain} {o.sellDex} @ {usd(o.sellPrice)}
          </div>
          <div className="muted small">İşlem büyüklüğü ≈ {usd(o.notionalUsd)}</div>
        </div>
      ))}
    </div>
  )
}

function TradesView({ trades, logs }: { trades: TradeOrder[]; logs: string[] }): JSX.Element {
  return (
    <div className="grid">
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
                <th>Ücret</th>
                <th>Durum</th>
                <th>Neden</th>
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
                  <td className="muted">{usd(t.feeUsd ?? 0)}</td>
                  <td className={t.status === 'filled' ? 'pos' : t.status === 'failed' ? 'neg' : ''}>
                    {t.status}
                  </td>
                  <td className="muted small reason" title={t.reason ?? ''}>
                    {t.reason ?? '—'}
                  </td>
                </tr>
              ))}
              {!trades.length && (
                <tr>
                  <td colSpan={9} className="muted">
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
  )
}

function Kpi({
  label,
  value,
  accent
}: {
  label: string
  value: string
  accent?: 'pos' | 'neg'
}): JSX.Element {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-val ${accent ?? ''}`}>{value}</div>
    </div>
  )
}
