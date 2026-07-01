import { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectEvents, type ConnStatus } from './api'
import { useI18n } from './lib/i18n'
import EquityChart from './components/EquityChart'
import TechnicalChart from './components/TechnicalChart'
import MarketPanel from './components/MarketPanel'
import NewsPanel from './components/NewsPanel'
import AnalystPanel from './components/AnalystPanel'
import ExplorePanel from './components/ExplorePanel'
import SignalsView from './views/SignalsView'
import StrategiesView from './views/StrategiesView'
import ArbitrageView from './views/ArbitrageView'
import TradesView from './views/TradesView'
import PositionsTable from './components/PositionsTable'
import ChainsPanel from './components/ChainsPanel'
import { CHAIN_NAMES, TABS, usd, type Tab } from './lib/ui'
import type {
  ArbitrageOpportunity,
  BotState,
  GasInfo,
  PortfolioSnapshot,
  PriceQuote,
  TradeOrder,
  TradeSignal,
  WalletInfo
} from '@shared/types'

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
  const [wallet, setWallet] = useState<WalletInfo | null>(null)
  const [walletModal, setWalletModal] = useState(false)
  const [walletInput, setWalletInput] = useState('')
  const [walletErr, setWalletErr] = useState('')
  const [wsStatus, setWsStatus] = useState<ConnStatus>('connecting')
  const [tab, setTab] = useState<Tab>('overview')
  const { t, lang, setLang } = useI18n()
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
        api.trades(200),
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
    api.wallet().then(setWallet).catch(() => {})
    const poll = setInterval(refresh, 5000)
    const gasPoll = setInterval(refreshGas, 15000)
    const off = connectEvents((e) => {
      if (e.type === 'tick') setState(e.state)
      else if (e.type === 'signal') setSignals((p) => [e.signal, ...p].slice(0, 40))
      else if (e.type === 'trade') {
        setTrades((p) => [e.order, ...p].slice(0, 200))
        const o = e.order
        pushLog(
          `İŞLEM ${o.side} ${o.amount.toFixed(4)} ${o.base} @ ${usd(o.filledPrice || o.price)}` +
            (o.reason ? ` — ${o.reason}` : '')
        )
      }
      else if (e.type === 'arbitrage') setArbs((p) => [e.opp, ...p].slice(0, 20))
      else if (e.type === 'log') pushLog(`[${e.level}] ${e.message}`)
    }, setWsStatus)
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

  const connectWallet = (): void => {
    // İmzalayıcı (live anahtar) varsa adres ondan türetilir; değiştirilemez.
    if (wallet?.source === 'signer') {
      pushLog(`İmzalayıcı cüzdan (live anahtar) bağlı: ${wallet.address}`)
      return
    }
    // Electron'da window.prompt desteklenmez → uygulama-içi modal aç.
    setWalletInput(wallet?.address ?? '')
    setWalletErr('')
    setWalletModal(true)
  }

  const submitWallet = async (addr: string): Promise<void> => {
    try {
      const w = await api.connectWallet(addr.trim())
      setWallet(w)
      setWalletModal(false)
      setWalletErr('')
      pushLog(addr.trim() ? `Cüzdan bağlandı: ${addr.trim()}` : 'Cüzdan bağlantısı kesildi')
    } catch (e) {
      setWalletErr((e as Error).message || 'Bağlanamadı')
    }
  }

  const shortAddr = (a?: string | null): string =>
    a ? `${a.slice(0, 6)}…${a.slice(-4)}` : ''

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
          <button
            className={`wallet-chip ${wallet?.address ? 'on' : ''}`}
            onClick={connectWallet}
            title={
              wallet?.address
                ? `${wallet.address}\n(${wallet.source === 'signer' ? 'imzalayıcı' : 'izleme'})`
                : 'Cüzdan bağla (public adres)'
            }
          >
            {wallet?.address ? (
              <>
                👛 {shortAddr(wallet.address)}
                {wallet.source === 'watch' && <span className="muted small"> · izleme</span>}
              </>
            ) : (
              '👛 Cüzdan Bağla'
            )}
          </button>
        </div>
        <div className="controls">
          {ethGas && (
            <span className="gaschip" title="Canlı gas (ETH)">
              ⛽ {ethGas.gwei} gwei · {usd(ethGas.swap_usd)}
            </span>
          )}
          <span
            className={`dot ${connected ? 'on' : wsStatus === 'reconnecting' ? 'warn' : 'off'}`}
          />
          <span className="muted" role="status" aria-live="polite">
            {connected
              ? t('conn.open')
              : wsStatus === 'reconnecting'
                ? t('conn.reconnecting')
                : wsStatus === 'connecting'
                  ? t('conn.connecting')
                  : t('conn.down')}
          </span>
          <button
            className="btn-ghost small"
            onClick={() => setLang(lang === 'tr' ? 'en' : 'tr')}
            aria-label="Dil değiştir / change language"
            title="TR / EN"
          >
            🌐 {lang.toUpperCase()}
          </button>
          <div className="seg" role="group" aria-label="İşlem modu">
            <button
              className={state.mode === 'paper' ? 'active' : ''}
              aria-pressed={state.mode === 'paper'}
              onClick={() => switchMode('paper')}
            >
              {t('mode.paper')}
            </button>
            <button
              className={state.mode === 'live' ? 'active live' : ''}
              aria-pressed={state.mode === 'live'}
              onClick={() => switchMode('live')}
            >
              {t('mode.live')}
            </button>
          </div>
          <button
            className={`run ${state.status}`}
            onClick={toggleRun}
            aria-label={state.status === 'running' ? t('run.stop') : t('run.start')}
          >
            {state.status === 'running' ? t('run.stop') : t('run.start')}
          </button>
        </div>
      </header>

      <section className="kpis">
        <Kpi label={t('kpi.equity')} value={usd(equityVal)} />
        <Kpi label={t('kpi.cash')} value={usd(portfolio?.cashUsd ?? 0)} />
        <Kpi label={t('kpi.pnl')} value={usd(pnl)} accent={pnl >= 0 ? 'pos' : 'neg'} />
        <Kpi label={t('kpi.positions')} value={String(portfolio?.positions.length ?? 0)} />
        <Kpi label={t('kpi.arb')} value={String(arbs.length)} />
        <Kpi label={t('kpi.gas')} value={ethGas ? `${ethGas.gwei} gwei` : '—'} />
      </section>

      <nav className="tabs" role="tablist">
        {TABS.map((tb) => (
          <button
            key={tb.id}
            className={tab === tb.id ? 'tab active' : 'tab'}
            role="tab"
            aria-selected={tab === tb.id}
            onClick={() => setTab(tb.id)}
          >
            {t(`tab.${tb.id}`)}
            {tb.id === 'arbitrage' && arbs.length > 0 && (
              <span className="pill">{arbs.length}</span>
            )}
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === 'overview' && (
          <Overview
            equity={equity}
            portfolio={portfolio}
            prices={prices}
            gas={gas}
            onResetPaper={async () => {
              if (state.mode === 'live') {
                pushLog('Live modda paper sıfırlama yapılmaz')
                return
              }
              if (!window.confirm('Paper portföy sıfırlanıp $100 değerinde ETH ile başlatılacak. Onaylıyor musun?'))
                return
              const r = await api.resetPaper()
              if (r.ok) {
                setTrades([])
                pushLog(`Paper sıfırlandı → $${r.seed_usd} ${r.asset}`)
              } else {
                pushLog(`Sıfırlama başarısız: ${r.reason ?? 'bilinmiyor'}`)
              }
            }}
          />
        )}
        {/* Keşfet ve Piyasa her zaman mount kalır; sekme değişince sadece gizlenir
            → yüklenen veriler, filtreler ve seçim KAYBOLMAZ (yeniden yükleme yok).
            Uygulamayı kapatınca tüm state ile birlikte temizlenir. */}
        <div style={{ display: tab === 'explore' ? 'contents' : 'none' }}>
          <ExplorePanel active={tab === 'explore'} />
        </div>
        <div style={{ display: tab === 'market' ? 'contents' : 'none' }}>
          <MarketPanel active={tab === 'market'} />
        </div>
        {tab === 'signals' && <SignalsView signals={signals} />}
        {tab === 'strategies' && <StrategiesView active={tab === 'strategies'} />}
        {tab === 'arbitrage' && <ArbitrageView arbs={arbs} />}
        {tab === 'news' && <NewsPanel />}
        {tab === 'analyst' && <AnalystPanel />}
        {tab === 'trades' && (
          <TradesView
            trades={trades}
            logs={logs}
            positions={portfolio?.positions ?? []}
            onClear={async () => {
              if (!window.confirm('Tüm işlem geçmişi silinecek. Emin misin?')) return
              await api.clearTrades()
              setTrades([])
            }}
          />
        )}
      </main>

      {walletModal && (
        <div className="modal-overlay" onClick={() => setWalletModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>👛 Cüzdan Bağla</h3>
            <p className="muted small">
              İzlemek istediğin public adresi (0x…) gir. Özel anahtar ASLA girilmez.
              Boş bırakıp “Bağla” dersen bağlantı kesilir.
            </p>
            <input
              className="wallet-input"
              type="text"
              autoFocus
              spellCheck={false}
              placeholder="0x..."
              value={walletInput}
              onChange={(e) => setWalletInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void submitWallet(walletInput)
                if (e.key === 'Escape') setWalletModal(false)
              }}
            />
            {walletErr && <div className="muted small err">{walletErr}</div>}
            <div className="modal-actions">
              <button className="btn" onClick={() => setWalletModal(false)}>
                İptal
              </button>
              {wallet?.address && (
                <button className="btn warn" onClick={() => void submitWallet('')}>
                  Bağlantıyı Kes
                </button>
              )}
              <button className="btn primary" onClick={() => void submitWallet(walletInput)}>
                Bağla
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Overview({
  equity,
  portfolio,
  prices,
  gas,
  onResetPaper
}: {
  equity: { t: number; equity: number }[]
  portfolio: PortfolioSnapshot | null
  prices: PriceQuote[]
  gas: GasInfo[]
  onResetPaper?: () => void
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

      <ChainsPanel />

      <PositionsTable positions={portfolio?.positions ?? []} onReset={onResetPaper} />

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
