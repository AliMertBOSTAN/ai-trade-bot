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
import PerformancePanel from './components/PerformancePanel'
import { CHAIN_NAMES, TABS, TAB_HINTS, TRADE_THRESHOLD, usd, type Tab } from './lib/ui'
import type { LivePreflight } from './api'
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
  // Paper sıfırlama modalı: tutar + nakit/ETH başlangıç seçimi
  const [resetModal, setResetModal] = useState(false)
  const [resetAmount, setResetAmount] = useState('1000')
  const [resetCash, setResetCash] = useState(false)
  // Live ön-uçuş kontrolü: geçmeden önce cüzdan/RPC/bakiye raporu göster
  const [preflight, setPreflight] = useState<LivePreflight | null>(null)
  const [preflightModal, setPreflightModal] = useState(false)
  const [preflightBusy, setPreflightBusy] = useState(false)
  const [walletInput, setWalletInput] = useState('')
  const [walletErr, setWalletErr] = useState('')
  const [wsStatus, setWsStatus] = useState<ConnStatus>('connecting')
  const [tab, setTab] = useState<Tab>('overview')
  // İşlem eşiği backend'ten okunur (risk.min_confidence); sabit yazılmaz.
  const [tradeThreshold, setTradeThreshold] = useState<number>(TRADE_THRESHOLD)
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
    api
      .config()
      .then((c) => {
        const mc = (c as { risk?: { min_confidence?: number } }).risk?.min_confidence
        if (typeof mc === 'number' && mc > 0) setTradeThreshold(Math.round(mc * 100))
      })
      .catch(() => {})
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

  const doSwitchMode = async (mode: 'paper' | 'live'): Promise<void> => {
    try {
      const s = await api.setMode(mode)
      setState(s)
      pushLog(`Mod -> ${mode.toUpperCase()}`)
      if (s.message) pushLog(`UYARI: ${s.message}`)
    } catch (err) {
      pushLog(`Mod değişimi başarısız: ${(err as Error).message}`)
    }
  }

  const switchMode = async (mode: 'paper' | 'live'): Promise<void> => {
    if (mode !== 'live') {
      await doSwitchMode(mode)
      return
    }
    // Live: önce ön-uçuş raporu göster; kullanıcı onaylarsa geç.
    setPreflightBusy(true)
    try {
      const p = await api.livePreflight()
      setPreflight(p)
      setPreflightModal(true)
    } catch {
      pushLog('Ön kontrol alınamadı — engine çalışıyor mu?')
    } finally {
      setPreflightBusy(false)
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
              disabled={preflightBusy}
              onClick={() => switchMode('live')}
            >
              {preflightBusy ? '⏳' : t('mode.live')}
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

      {TAB_HINTS[tab] && <div className="tab-hint">ℹ️ {TAB_HINTS[tab]}</div>}

      <main className="content">
        {tab === 'overview' && (
          <Overview
            equity={equity}
            portfolio={portfolio}
            prices={prices}
            gas={gas}
            onResetPaper={() => {
              if (state.mode === 'live') {
                pushLog('Live modda paper sıfırlama yapılmaz')
                return
              }
              setResetModal(true)
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
        {tab === 'signals' && <SignalsView signals={signals} threshold={tradeThreshold} />}
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

      {preflightModal && preflight && (
        <div className="modal-overlay" onClick={() => setPreflightModal(false)}>
          <div className="modal preflight" onClick={(e) => e.stopPropagation()}>
            <h3>🛫 Canlıya Geçiş Ön Kontrolü</h3>
            <div className="pf-checks">
              <PfCheck ok={preflight.checks.signer_wallet} label="İmzalayıcı cüzdan">
                {preflight.wallet_address
                  ? `${preflight.wallet_address.slice(0, 8)}…${preflight.wallet_address.slice(-6)}`
                  : 'WALLET_PRIVATE_KEY veya keystore tanımlı değil'}
              </PfCheck>
              <PfCheck ok={preflight.checks.rpc_available} label="RPC bağlantısı">
                {preflight.checks.rpc_available
                  ? 'en az bir zincir erişilebilir'
                  : 'hiçbir zincire bağlanılamadı'}
              </PfCheck>
              <PfCheck ok={preflight.checks.funded_chain} label="Bakiye">
                {preflight.checks.funded_chain
                  ? 'en az bir zincirde stable + gas var'
                  : 'hiçbir zincirde yeterli stable (≥$10) + native gas yok'}
              </PfCheck>
              <PfCheck ok={preflight.checks.llm_ready} label="LLM">
                {preflight.llm_provider === 'none'
                  ? 'kapalı (saf teknik karar)'
                  : `${preflight.llm_provider} yapılandırılmış`}
              </PfCheck>
              <PfCheck ok={preflight.checks.kill_switch_clear} label="Kill-switch">
                {preflight.checks.kill_switch_clear
                  ? 'temiz'
                  : 'AKTİF — günlük zarar limiti aşılmış'}
              </PfCheck>
            </div>
            <div className="scroll" style={{ maxHeight: 180 }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Zincir</th>
                    <th>RPC</th>
                    <th>Gas</th>
                    <th>Stable</th>
                    <th>Native</th>
                  </tr>
                </thead>
                <tbody>
                  {preflight.chains.map((c) => (
                    <tr key={c.chain_id}>
                      <td>
                        <b>{c.name}</b>
                      </td>
                      <td className={c.rpc_ok ? 'pos' : 'neg'}>{c.rpc_ok ? '✓' : '✗'}</td>
                      <td className={c.gas_ok === false ? 'neg' : 'muted'}>
                        {c.gas_gwei != null ? `${c.gas_gwei} gwei` : '—'}
                      </td>
                      <td className={(c.stable_balance ?? 0) >= 10 ? 'pos' : 'muted'}>
                        {c.stable_balance != null
                          ? `${c.stable_balance} ${c.stable_symbol}`
                          : '—'}
                      </td>
                      <td className={(c.native_balance ?? 0) > 0 ? 'pos' : 'muted'}>
                        {c.native_balance != null
                          ? `${c.native_balance} ${c.native_symbol}`
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted small" style={{ marginTop: 8 }}>
              Limitler: pozisyon ≤ ${preflight.limits.max_position_usd} · günlük zarar ≤ $
              {preflight.limits.max_daily_loss_usd} · gas ≤ {preflight.limits.max_gas_gwei} gwei
              · slippage {preflight.limits.slippage_bps / 100}% · günlük harcama{' '}
              {preflight.limits.daily_spend_limit_usd > 0
                ? `≤ $${preflight.limits.daily_spend_limit_usd}`
                : 'LİMİTSİZ (MAX_DAILY_SPEND_USD önerilir)'}
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setPreflightModal(false)}>
                Vazgeç (paper'da kal)
              </button>
              <button
                className="btn warn"
                disabled={!preflight.checks.signer_wallet || !preflight.checks.rpc_available}
                title={
                  preflight.ready
                    ? 'Gerçek fonla işlem başlar'
                    : 'Eksik kontroller var — yine de geçilebilir ama önerilmez'
                }
                onClick={async () => {
                  setPreflightModal(false)
                  await doSwitchMode('live')
                }}
              >
                {preflight.ready ? '✓ Live moduna geç' : '⚠ Yine de Live moduna geç'}
              </button>
            </div>
          </div>
        </div>
      )}

      {resetModal && (
        <div className="modal-overlay" onClick={() => setResetModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>↺ Paper Portföyü Sıfırla</h3>
            <p className="muted small">
              Tüm pozisyonlar ve işlem geçmişi silinir; portföy aşağıdaki tutarla
              yeniden başlar. Bu işlem geri alınamaz.
            </p>
            <label className="muted small" htmlFor="reset-amount">
              Başlangıç tutarı (USD)
            </label>
            <input
              id="reset-amount"
              className="wallet-input"
              type="number"
              min={10}
              step={100}
              autoFocus
              value={resetAmount}
              onChange={(e) => setResetAmount(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setResetModal(false)
              }}
            />
            <div className="reset-quick">
              {[100, 1000, 5000, 10000].map((v) => (
                <button
                  key={v}
                  className={`btn small ${Number(resetAmount) === v ? 'primary' : ''}`}
                  onClick={() => setResetAmount(String(v))}
                >
                  ${v.toLocaleString('en-US')}
                </button>
              ))}
            </div>
            <label className="reset-cash-row">
              <input
                type="checkbox"
                checked={resetCash}
                onChange={(e) => setResetCash(e.target.checked)}
              />
              <span>
                Nakit olarak başlat{' '}
                <span className="muted small">
                  (işaretli değilse tutar ETH'ye çevrilerek başlar)
                </span>
              </span>
            </label>
            <div className="modal-actions">
              <button className="btn" onClick={() => setResetModal(false)}>
                İptal
              </button>
              <button
                className="btn warn"
                onClick={async () => {
                  const amount = Number(resetAmount)
                  if (!Number.isFinite(amount) || amount < 10) {
                    pushLog('Geçersiz tutar — en az $10 girilmeli')
                    return
                  }
                  const r = await api.resetPaper(amount, resetCash)
                  if (r.ok) {
                    setTrades([])
                    setResetModal(false)
                    pushLog(
                      `Paper sıfırlandı → $${amount.toLocaleString('en-US')} ${
                        resetCash ? 'nakit' : r.asset ?? 'ETH'
                      }`
                    )
                  } else {
                    pushLog(`Sıfırlama başarısız: ${r.reason ?? 'bilinmiyor'}`)
                  }
                }}
              >
                Sıfırla ve Başlat
              </button>
            </div>
          </div>
        </div>
      )}

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

/* ---- Ana sayfa panel ızgarası: sürükle-bırak + boyutlandırma ----
   Kart sırası/genişliği/yüksekliği localStorage'da saklanır ve kalıcıdır.
   ⠿ tutamacıyla sürükle, ⇔ ile tam/yarım genişlik, alt kenardan yükseklik. */
type DashSpan = 1 | 2
interface DashLayout {
  order: string[]
  span: Record<string, DashSpan>
  h: Record<string, number>
}

const DASH_KEY = 'dash-layout-v1'
const DASH_DEFAULT: DashLayout = {
  order: ['equity', 'perf', 'tech', 'chains', 'positions', 'gas', 'prices'],
  span: { equity: 1, perf: 1, tech: 1, chains: 1, positions: 1, gas: 1, prices: 2 },
  h: {}
}

function loadDashLayout(): DashLayout {
  try {
    const raw = localStorage.getItem(DASH_KEY)
    if (!raw) return DASH_DEFAULT
    const p = JSON.parse(raw) as Partial<DashLayout>
    const order = (Array.isArray(p.order) ? p.order : []).filter((id) =>
      DASH_DEFAULT.order.includes(id)
    )
    for (const id of DASH_DEFAULT.order) if (!order.includes(id)) order.push(id)
    return {
      order,
      span: { ...DASH_DEFAULT.span, ...(p.span ?? {}) },
      h: { ...(p.h ?? {}) }
    }
  } catch {
    return DASH_DEFAULT
  }
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
  const [layout, setLayout] = useState<DashLayout>(loadDashLayout)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const refs = useRef<Record<string, HTMLDivElement | null>>({})

  const save = (l: DashLayout): void => {
    setLayout(l)
    try {
      localStorage.setItem(DASH_KEY, JSON.stringify(l))
    } catch {
      /* dolu olabilir; kritik değil */
    }
  }

  const dropOn = (targetId: string): void => {
    if (dragId && dragId !== targetId) {
      const order = layout.order.filter((x) => x !== dragId)
      order.splice(order.indexOf(targetId), 0, dragId)
      save({ ...layout, order })
    }
    setDragId(null)
    setOverId(null)
  }

  const toggleSpan = (id: string): void => {
    const span: Record<string, DashSpan> = {
      ...layout.span,
      [id]: layout.span[id] === 2 ? 1 : 2
    }
    save({ ...layout, span })
  }

  // Native resize (alt kenar) bırakılınca yüksekliği kalıcılaştır.
  const persistHeight = (id: string): void => {
    const el = refs.current[id]
    if (!el) return
    const cur = el.offsetHeight
    const stored = layout.h[id]
    if (el.style.height && cur > 0 && cur !== stored) {
      save({ ...layout, h: { ...layout.h, [id]: cur } })
    }
  }

  const resetLayout = (): void => {
    try {
      localStorage.removeItem(DASH_KEY)
    } catch {
      /* yok say */
    }
    setLayout({ ...DASH_DEFAULT, h: {} })
    for (const el of Object.values(refs.current)) if (el) el.style.height = ''
  }

  const cards: Record<string, JSX.Element> = {
    equity: (
      <div className="card">
        <h3>Equity Eğrisi</h3>
        <div className="chartbox">
          <EquityChart data={equity} />
        </div>
      </div>
    ),
    tech: (
      <div className="card">
        <h3>Teknik Analiz</h3>
        <div className="chartbox">
          <TechnicalChart />
        </div>
      </div>
    ),
    perf: <PerformancePanel />,
    chains: <ChainsPanel />,
    positions: <PositionsTable positions={portfolio?.positions ?? []} onReset={onResetPaper} />,
    gas: (
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
    ),
    prices: (
      <div className="card">
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
    )
  }

  return (
    <>
      <div className="dashgrid">
        {layout.order.map((id) => (
          <div
            key={id}
            ref={(el) => {
              refs.current[id] = el
            }}
            className={`dash-item ${layout.span[id] === 2 ? 'span2' : ''} ${
              overId === id ? 'drag-over' : ''
            } ${dragId === id ? 'dragging' : ''}`}
            style={layout.h[id] ? { height: layout.h[id] } : undefined}
            onDragOver={(e) => {
              if (!dragId || dragId === id) return
              e.preventDefault()
              setOverId(id)
            }}
            onDragLeave={() => setOverId((o) => (o === id ? null : o))}
            onDrop={(e) => {
              e.preventDefault()
              dropOn(id)
            }}
            onMouseUp={() => persistHeight(id)}
          >
            <div className="dash-tools">
              <span
                className="dash-handle"
                title="Sürükleyip başka bir kartın üzerine bırak"
                draggable
                onDragStart={(e) => {
                  setDragId(id)
                  e.dataTransfer.effectAllowed = 'move'
                  const el = refs.current[id]
                  if (el) e.dataTransfer.setDragImage(el, 60, 20)
                }}
                onDragEnd={() => {
                  setDragId(null)
                  setOverId(null)
                }}
              >
                ⠿
              </span>
              <button
                className="dash-size"
                title={layout.span[id] === 2 ? 'Yarım genişliğe daralt' : 'Tam genişliğe yay'}
                onClick={() => toggleSpan(id)}
              >
                ⇔
              </button>
            </div>
            {cards[id]}
          </div>
        ))}
      </div>
      <div className="dash-foot muted small">
        ⠿ ile kartları sürükle · ⇔ ile genişlik değiştir · alt kenardan yüksekliği çek ·{' '}
        <button className="linklike" onClick={resetLayout}>
          düzeni sıfırla
        </button>
      </div>
    </>
  )
}

function PfCheck({
  ok,
  label,
  children
}: {
  ok: boolean
  label: string
  children?: React.ReactNode
}): JSX.Element {
  return (
    <div className={`pf-check ${ok ? 'ok' : 'fail'}`}>
      <span className="pf-ico">{ok ? '✅' : '❌'}</span>
      <b>{label}</b>
      <span className="muted small">{children}</span>
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
