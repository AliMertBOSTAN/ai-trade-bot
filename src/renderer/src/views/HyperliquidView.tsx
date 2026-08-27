// Hyperliquid perp işlem masası — hem sen hem AI buradan işlem yapar.
//
// Yerleşim: solda ARANABİLİR piyasa listesi (tüm perp evreni, fiyat/24s/funding/
// OI/kaldıraç ile), sağda seçili piyasanın emir formu. Bir satıra tıklamak
// piyasayı seçer.
//
// Emir yolu: form → /hl/preview (kapı sonucu + likidasyon fiyatı) → /hl/order.
// Backend her emri risk kapısından geçirir; kapı reddederse `blocked: true`
// döner ve emir GÖNDERİLMEZ. AI otopilotu da aynı kapıdan geçer.
//
// TASARIM KURALI: hiçbir istek sessizce yutulmaz. Liste boşsa NEDEN boş
// olduğu yazılır (engine kapalı / eski sürüm / Hyperliquid erişilemiyor).
import { useCallback, useEffect, useMemo, useState, type JSX } from 'react'
import { api } from '../api'
import DecisionCard from '../components/intel/DecisionCard'
import type {
  AIAnalystStatus,
  AIDecision,
  AIReport,
  HLOrderResult,
  HLPreview,
  HLState,
  HLUniverseRow
} from '@shared/types'

const usd = (n?: number | null, d = 2): string =>
  n == null ? '—' : `$${n.toLocaleString('en-US', { maximumFractionDigits: d })}`
const px = (n?: number | null): string =>
  n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: 6 })
const compact = (n?: number | null): string => {
  if (n == null || !Number.isFinite(n)) return '—'
  const a = Math.abs(n)
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `$${(n / 1e3).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}
const pctStr = (n?: number | null, d = 2): string =>
  n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(d)}%`
const tone = (n?: number | null): string =>
  n == null || n === 0 ? 'muted' : n > 0 ? 'pos' : 'neg'
const clock = (t?: number): string => (t ? new Date(t).toLocaleTimeString('tr-TR') : '—')

/** Hata mesajını kullanıcının ne yapacağını bilebileceği hâle çevirir. */
function explain(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e)
  if (/Failed to fetch|NetworkError|ECONNREFUSED/i.test(m))
    return 'Engine çalışmıyor gibi. Terminalde: uvicorn engine.app:app --port 8787'
  if (/: 404/.test(m))
    return 'Engine ayakta ama /hl/* uçlarını tanımıyor — eski sürüm çalışıyor. uvicorn’u yeniden başlat.'
  if (/: 5\d\d/.test(m)) return `Engine hata döndürdü (${m}). Terminal loguna bak.`
  return m
}

type SortKey = 'volume' | 'symbol' | 'change' | 'funding' | 'oi'

const POLL_MS = 6000

export default function HyperliquidView({ active }: { active: boolean }): JSX.Element {
  const [state, setState] = useState<HLState | null>(null)
  const [uni, setUni] = useState<HLUniverseRow[]>([])
  const [uniErr, setUniErr] = useState('')
  const [uniBusy, setUniBusy] = useState(false)
  const [reports, setReports] = useState<AIReport[]>([])
  const [ai, setAi] = useState<AIAnalystStatus | null>(null)
  const [err, setErr] = useState('')

  // piyasa listesi
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('volume')

  // emir formu
  const [symbol, setSymbol] = useState('BTC')
  const [side, setSide] = useState<'LONG' | 'SHORT'>('LONG')
  const [notional, setNotional] = useState('100')
  const [leverage, setLeverage] = useState(3)
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market')
  const [limitPrice, setLimitPrice] = useState('')
  const [decision, setDecision] = useState<AIDecision | null>(null)
  const [decBusy, setDecBusy] = useState(false)
  // Kaldıracı kim seçiyor: sen mi, AI mı? "ai" iken AI'ın önerdiği kaldıraç
  // forma otomatik uygulanır (borsa/risk tavanlarıyla kırpılmış hâli).
  const [levMode, setLevMode] = useState<'manual' | 'ai'>('manual')
  const [preview, setPreview] = useState<HLPreview | null>(null)
  const [result, setResult] = useState<HLOrderResult | null>(null)
  const [busy, setBusy] = useState(false)

  /* ------------------------------------------------------------ veri --- */
  const loadState = useCallback(async (): Promise<void> => {
    try {
      const [s, r] = await Promise.all([api.hlState(), api.aiReports(20)])
      setState(s)
      setReports(r.reports)
      setAi(r.status)
      setErr('')
    } catch (e) {
      setErr(explain(e))
    }
  }, [])

  const loadUniverse = useCallback(async (): Promise<void> => {
    setUniBusy(true)
    try {
      const u = await api.hlUniverse(400)
      if (!u.ok || u.rows.length === 0) {
        setUni([])
        setUniErr(u.error || 'Hyperliquid piyasa listesi boş döndü.')
      } else {
        setUni(u.rows)
        setUniErr('')
        // Seçili sembol listede yoksa en yüksek hacimliye geç — form asla boş kalmaz.
        setSymbol((cur) => (u.rows.some((r) => r.symbol === cur) ? cur : u.rows[0].symbol))
      }
    } catch (e) {
      setUni([])
      setUniErr(explain(e))
    } finally {
      setUniBusy(false)
    }
  }, [])

  /** Seçili pair'in son AI kararını oku (analiz ÇALIŞTIRMAZ, token harcamaz). */
  const loadDecision = useCallback(
    async (sym: string): Promise<void> => {
      try {
        setDecision(await api.aiDecision(sym))
      } catch (e) {
        setDecision(null)
        setErr(explain(e))
      }
    },
    []
  )

  const scanSymbol = useCallback(async (): Promise<void> => {
    setDecBusy(true)
    try {
      setDecision(await api.aiDecision(symbol, true))
      await loadState()
    } catch (e) {
      setErr(explain(e))
    } finally {
      setDecBusy(false)
    }
  }, [symbol, loadState])

  const dryRun = useCallback(async (): Promise<void> => {
    setDecBusy(true)
    try {
      setDecision(await api.aiDryRun(symbol))
    } catch (e) {
      setErr(explain(e))
    } finally {
      setDecBusy(false)
    }
  }, [symbol])

  // Sembol değişince kararı da değiştir — kart daima seçili pair'i gösterir.
  useEffect(() => {
    if (!active || !symbol) return
    loadDecision(symbol)
  }, [active, symbol, loadDecision])

  useEffect(() => {
    if (!active) return
    loadState()
    loadUniverse()
    const t = setInterval(loadState, POLL_MS)
    const tu = setInterval(loadUniverse, 30_000) // fiyatlar tazelensin
    return () => {
      clearInterval(t)
      clearInterval(tu)
    }
  }, [active, loadState, loadUniverse])

  /* ------------------------------------------------------- piyasa listesi */
  const market = useMemo(() => uni.find((u) => u.symbol === symbol), [uni, symbol])

  const rows = useMemo(() => {
    const needle = q.trim().toUpperCase()
    const filtered = needle ? uni.filter((u) => u.symbol.includes(needle)) : uni
    const sorted = [...filtered]
    sorted.sort((a, b) => {
      switch (sortKey) {
        case 'symbol':
          return a.symbol.localeCompare(b.symbol)
        case 'change':
          return (b.change_pct_24h ?? -999) - (a.change_pct_24h ?? -999)
        case 'funding':
          return b.funding_hourly - a.funding_hourly
        case 'oi':
          return b.open_interest_usd - a.open_interest_usd
        default:
          return b.day_volume_usd - a.day_volume_usd
      }
    })
    return sorted
  }, [uni, q, sortKey])

  /* ------------------------------------------------------------- emir --- */
  const doPreview = useCallback(async (): Promise<void> => {
    if (!symbol) return
    setResult(null)
    try {
      setPreview(
        await api.hlPreview({
          symbol,
          side,
          notional_usd: Number(notional) || 0,
          leverage,
          order_type: orderType,
          ...(orderType === 'limit' && limitPrice ? { limit_price: Number(limitPrice) } : {})
        })
      )
    } catch (e) {
      setPreview(null)
      setErr(explain(e))
    }
  }, [symbol, side, notional, leverage, orderType, limitPrice])

  useEffect(() => {
    if (!active) return
    const t = setTimeout(doPreview, 350)
    return () => clearTimeout(t)
  }, [active, doPreview])

  const submit = async (): Promise<void> => {
    setBusy(true)
    setResult(null)
    try {
      const res = await api.hlOrder({
        symbol,
        side,
        notional_usd: Number(notional) || 0,
        leverage,
        order_type: orderType,
        ...(orderType === 'limit' && limitPrice ? { limit_price: Number(limitPrice) } : {})
      })
      setResult(res)
      await loadState()
    } catch (e) {
      setErr(explain(e))
    } finally {
      setBusy(false)
    }
  }

  const closePos = async (sym: string): Promise<void> => {
    setBusy(true)
    try {
      setResult(await api.hlClose(sym))
      await loadState()
    } catch (e) {
      setErr(explain(e))
    } finally {
      setBusy(false)
    }
  }

  const limits = state?.limits
  const maxLev = Math.min(market?.max_leverage ?? 20, limits?.max_leverage ?? 20)

  // AI kaldıraç modu: karar tazelendikçe formdaki kaldıracı AI'ın seçimine çek.
  const aiLev = decision?.plan
    ? decision.plan.approved_leverage || decision.plan.requested_leverage
    : null
  useEffect(() => {
    if (levMode !== 'ai' || !aiLev) return
    setLeverage(Math.max(1, Math.min(aiLev, maxLev)))
  }, [levMode, aiLev, maxLev])

  /** AI planını forma aktar: yön + kaldıraç + nosyonel. */
  const applyPlan = (s2: 'LONG' | 'SHORT', lev: number, notionalUsd: number): void => {
    setSide(s2)
    setLeverage(Math.max(1, Math.min(lev, maxLev)))
    setNotional(String(Math.max(10, Math.round(notionalUsd))))
    setLevMode('ai')
  }
  const free = state?.cash_usd ?? 0
  const isLive = state?.mode === 'live'
  const live = state?.live
  const coinSize = market && Number(notional) > 0 ? Number(notional) / market.mark : 0

  // Serbest teminatın yüzdesi kadar nosyonel (kaldıraç dahil)
  const setPctSize = (pct: number): void => {
    const n = free * (pct / 100) * Math.max(1, leverage)
    setNotional(String(Math.max(10, Math.floor(n))))
  }

  return (
    <div className="hl-wrap">
      {/* ---------------------------------------------------- durum şeridi */}
      <section className="card hl-head">
        <div className="card-head">
          <h3>Hyperliquid · Perp Masası</h3>
          <div className="iwidget-right">
            <span className={`badge ${isLive ? 'live' : 'paper'}`}>
              {isLive ? 'CANLI' : 'KAĞIT'}
            </span>
            {live?.testnet && <span className="pill">testnet</span>}
            {ai?.autopilot && <span className="pill warn">AI OTOPİLOT AÇIK</span>}
            <button className="btn small" onClick={loadState} title="Yenile">
              ⟳
            </button>
          </div>
        </div>

        {err && (
          <div className="callout warn">
            <b>Bağlantı sorunu:</b> {err}
          </div>
        )}

        {!isLive && live && live.reasons.length > 0 && (
          <details className="hl-why">
            <summary>
              Kağıt modda çalışıyor — canlı emir için {live.reasons.length} eksik var
            </summary>
            <ul>
              {live.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            <p className="muted small">
              İmzalama: <code>HL_API_WALLET_KEY</code> + <code>HL_ACCOUNT_ADDRESS</code>{' '}
              (Hyperliquid → API Wallets; para çekemez) ya da şifreli keystore. Anahtarı
              yalnızca sen <code>.env</code> dosyasına yazarsın.
            </p>
          </details>
        )}

        <div className="istats">
          <div className="istat">
            <div className="istat-l">Equity</div>
            <div className="istat-v">{usd(state?.equity_usd)}</div>
          </div>
          <div className="istat">
            <div className="istat-l">Serbest teminat</div>
            <div className="istat-v">{usd(free)}</div>
          </div>
          <div className="istat">
            <div className="istat-l">Kullanılan marj</div>
            <div className="istat-v">{usd(state?.margin_used_usd)}</div>
          </div>
          <div className="istat">
            <div className="istat-l">Açık PnL</div>
            <div className={`istat-v ${tone(state?.unrealized_pnl)}`}>
              {usd(state?.unrealized_pnl)}
            </div>
          </div>
          <div className="istat">
            <div className="istat-l">Bugünkü PnL</div>
            <div className={`istat-v ${tone(state?.day_realized_pnl)}`}>
              {usd(state?.day_realized_pnl)}
            </div>
            {limits && (
              <div className="istat-s">kill-switch −{usd(limits.max_daily_loss_usd, 0)}</div>
            )}
          </div>
        </div>

        {limits && (
          <p className="ifoot muted">
            Tavanlar: kaldıraç {limits.max_leverage}× · pozisyon {usd(limits.max_notional_usd, 0)}{' '}
            · toplam {usd(limits.max_total_notional_usd, 0)} · en fazla {limits.max_positions}{' '}
            pozisyon · likidasyona en az %{limits.min_liq_distance_pct} · bekleme{' '}
            {limits.cooldown_s}sn
            {limits.ai_enabled && (
              <>
                {' '}
                · <b>AI:</b> {usd(limits.ai_max_notional_usd, 0)} / {limits.ai_max_leverage}× /
                güven ≥ {limits.ai_min_confidence}
              </>
            )}
          </p>
        )}
      </section>

      {/* Piyasa listesi + emir formu KENDİ ızgara satırında: yapışkan liste
          böylece bu satırın sonunda durur, alttaki kartların üstüne binmez. */}
      <div className="hl-top">
      {/* ------------------------------------------------------ piyasalar */}
      <section className="card hl-markets">
        <div className="card-head">
          <h3>Piyasalar</h3>
          <div className="iwidget-right">
            <span className="muted small">
              {uni.length ? `${rows.length}/${uni.length} perp` : '—'}
            </span>
            <button className="btn small" onClick={loadUniverse} disabled={uniBusy}>
              {uniBusy ? '…' : '⟳'}
            </button>
          </div>
        </div>

        <input
          className="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ara — BTC, HYPE, SOL…"
          aria-label="Piyasa ara"
        />

        <div className="seg hl-sort" role="group" aria-label="Sıralama">
          {(
            [
              ['volume', 'Hacim'],
              ['change', '24s'],
              ['funding', 'Funding'],
              ['oi', 'OI'],
              ['symbol', 'A-Z']
            ] as [SortKey, string][]
          ).map(([k, label]) => (
            <button key={k} className={sortKey === k ? 'active' : ''} onClick={() => setSortKey(k)}>
              {label}
            </button>
          ))}
        </div>

        {uniErr ? (
          <div className="callout warn hl-uni-err">
            <b>Piyasa listesi yüklenemedi.</b>
            <p>{uniErr}</p>
            <button className="btn small" onClick={loadUniverse}>
              Tekrar dene
            </button>
          </div>
        ) : uni.length === 0 ? (
          <div className="iempty">
            <span className="iempty-ico">○</span>
            <span>{uniBusy ? 'yükleniyor…' : 'piyasa yok'}</span>
          </div>
        ) : (
          <div className="hl-list">
            {rows.map((m) => (
              <button
                key={m.symbol}
                className={`hl-mkt${m.symbol === symbol ? ' on' : ''}`}
                onClick={() => setSymbol(m.symbol)}
              >
                <span className="hl-mkt-s">{m.symbol}</span>
                <span className="hl-mkt-p mono">{px(m.mark)}</span>
                <span className={`hl-mkt-c ${tone(m.change_pct_24h)}`}>
                  {pctStr(m.change_pct_24h)}
                </span>
                <span className={`hl-mkt-f mono ${tone(-m.funding_hourly)}`}>
                  {(m.funding_hourly * 100).toFixed(4)}%
                </span>
                <span className="hl-mkt-v muted">{compact(m.day_volume_usd)}</span>
                <span className="hl-mkt-l">{m.max_leverage}×</span>
              </button>
            ))}
            {rows.length === 0 && <div className="sym-empty">“{q}” için eşleşme yok</div>}
          </div>
        )}
        <p className="ifoot muted">
          Sütunlar: fiyat · 24s değişim · saatlik funding · 24s hacim · azami kaldıraç.
          Funding pozitifken LONG öder.
        </p>
      </section>

      {/* ----------------------------------------------------- emir formu */}
      <section className="card hl-order">
        <div className="card-head">
          <h3>Emir</h3>
          {market && <span className="muted small">azami {market.max_leverage}×</span>}
        </div>

        {!market ? (
          <div className="iempty">
            <span className="iempty-ico">○</span>
            <span>Soldaki listeden bir piyasa seç</span>
          </div>
        ) : (
          <>
            {/* seçili piyasanın canlı künyesi */}
            <div className="hl-ticker">
              <div className="hl-ticker-s">{market.symbol}</div>
              <div className="hl-ticker-p mono">{px(market.mark)}</div>
              <div className={`hl-ticker-c ${tone(market.change_pct_24h)}`}>
                {pctStr(market.change_pct_24h)}
              </div>
              <div className="hl-ticker-m">
                <span className="muted">funding/sa</span>
                <b className={tone(-market.funding_hourly)}>
                  {(market.funding_hourly * 100).toFixed(4)}%
                </b>
              </div>
              <div className="hl-ticker-m">
                <span className="muted">açık pozisyon</span>
                <b>{compact(market.open_interest_usd)}</b>
              </div>
              <div className="hl-ticker-m">
                <span className="muted">24s hacim</span>
                <b>{compact(market.day_volume_usd)}</b>
              </div>
            </div>

            <div className="seg hl-side" role="group" aria-label="Yön">
              <button
                className={side === 'LONG' ? 'active' : ''}
                onClick={() => setSide('LONG')}
              >
                LONG
              </button>
              <button
                className={side === 'SHORT' ? 'active' : ''}
                onClick={() => setSide('SHORT')}
              >
                SHORT
              </button>
            </div>

            <div className="hl-form">
              <label>
                Nosyonel (USD)
                <input
                  className="input"
                  inputMode="decimal"
                  value={notional}
                  onChange={(e) => setNotional(e.target.value)}
                />
                <span className="muted small">
                  ≈ {coinSize ? coinSize.toFixed(6) : '—'} {market.symbol} · teminat{' '}
                  {usd((Number(notional) || 0) / Math.max(1, leverage))}
                </span>
              </label>

              <div className="hl-pcts">
                {[25, 50, 75, 100].map((p) => (
                  <button key={p} className="btn small" onClick={() => setPctSize(p)}>
                    %{p}
                  </button>
                ))}
                <span className="muted small">serbest teminatın yüzdesi × kaldıraç</span>
              </div>

              <label>
                <span className="lev-head">
                  Kaldıraç: <b>{leverage}×</b>
                  <span className="seg lev-mode" role="group" aria-label="Kaldıracı kim seçsin">
                    <button
                      className={levMode === 'manual' ? 'active' : ''}
                      onClick={() => setLevMode('manual')}
                      title="Kaldıracı sen belirle"
                    >
                      Elle
                    </button>
                    <button
                      className={levMode === 'ai' ? 'active' : ''}
                      onClick={() => setLevMode('ai')}
                      disabled={!aiLev}
                      title={
                        aiLev
                          ? `AI bu pair için ${aiLev}× öneriyor`
                          : 'Önce bu pair’i tara — AI kaldıraç önerisi oluşsun'
                      }
                    >
                      AI{aiLev ? ` (${aiLev}×)` : ''}
                    </button>
                  </span>
                </span>
                <input
                  type="range"
                  min={1}
                  max={maxLev}
                  value={Math.min(leverage, maxLev)}
                  disabled={levMode === 'ai'}
                  onChange={(e) => setLeverage(Number(e.target.value))}
                />
                <span className="muted small">
                  borsa tavanı {market.max_leverage}× · risk tavanı {limits?.max_leverage ?? '—'}×
                  {levMode === 'ai' && decision?.plan?.leverage_note
                    ? ` · AI: ${decision.plan.leverage_note}`
                    : ''}
                </span>
              </label>

              <div className="seg" role="group" aria-label="Emir tipi">
                <button
                  className={orderType === 'market' ? 'active' : ''}
                  onClick={() => setOrderType('market')}
                >
                  Market
                </button>
                <button
                  className={orderType === 'limit' ? 'active' : ''}
                  onClick={() => setOrderType('limit')}
                >
                  Limit
                </button>
              </div>

              {orderType === 'limit' && (
                <label>
                  Limit fiyat
                  <input
                    className="input"
                    inputMode="decimal"
                    value={limitPrice}
                    onChange={(e) => setLimitPrice(e.target.value)}
                    placeholder={String(market.mark)}
                  />
                </label>
              )}
            </div>

            {preview && (
              <div className={`hl-preview ${preview.decision.approved ? '' : 'blocked'}`}>
                {/* Kapı reddettiğinde sayılar TALEP EDİLEN değerlerdir; onay
                    verilmediği için "onaylanan kaldıraç" gösterilmez. */}
                {!preview.decision.approved && (
                  <p className="hl-block">🚫 {preview.decision.reason}</p>
                )}
                <div className="irow">
                  <span className="irow-l">
                    {preview.decision.approved ? 'Boyut' : 'Talep edilen boyut'}
                  </span>
                  <span className="irow-v mono">
                    {preview.size} {preview.symbol}
                  </span>
                </div>
                <div className="irow">
                  <span className="irow-l">Gereken teminat</span>
                  <span className="irow-v mono">{usd(preview.margin_usd)}</span>
                </div>
                {preview.decision.approved && (
                  <>
                    <div className="irow">
                      <span className="irow-l">Likidasyon fiyatı</span>
                      <span className="irow-v mono neg">{px(preview.liq_price)}</span>
                    </div>
                    <div className="irow">
                      <span className="irow-l">Onaylanan kaldıraç</span>
                      <span className="irow-v mono">{preview.decision.leverage}×</span>
                    </div>
                  </>
                )}
                {preview.decision.warnings.map((w, i) => (
                  <p key={i} className="ifoot warn">
                    ⚠ {w}
                  </p>
                ))}
              </div>
            )}

            <button
              className={`btn primary hl-submit ${side === 'LONG' ? 'long' : 'short'}`}
              disabled={busy || !preview?.decision.approved}
              onClick={submit}
            >
              {busy
                ? 'Gönderiliyor…'
                : preview && !preview.decision.approved
                  ? 'Risk kapısı geçilmedi'
                  : `${side} ${market.symbol} · ${isLive ? 'CANLI' : 'kağıt'} · ${
                      preview?.decision.leverage || leverage
                    }×`}
            </button>

            {result && (
              <div className={`callout ${result.ok ? '' : 'warn'}`}>
                {result.ok ? (
                  <>
                    ✓ {result.mode === 'live' ? 'Canlı' : 'Kağıt'} emir işlendi
                    {result.price ? ` @ ${px(result.price)}` : ''}
                    {result.pnl_usd != null ? ` · PnL ${usd(result.pnl_usd)}` : ''}
                  </>
                ) : (
                  <>🚫 {result.reason || result.error}</>
                )}
              </div>
            )}

            {!isLive && (
              <button
                className="btn small"
                onClick={async () => {
                  await api.hlResetPaper(1000)
                  loadState()
                }}
              >
                ↺ Kağıt defterini sıfırla
              </button>
            )}
          </>
        )}
      </section>
      </div>

      {/* --------------------------------------------------- AI kararı --- */}
      <DecisionCard
        decision={decision}
        busy={decBusy}
        onScan={scanSymbol}
        onDryRun={dryRun}
        onApply={applyPlan}
      />

      {/* ------------------------------------------------ açık pozisyonlar */}
      <section className="card hl-span">
        <div className="card-head">
          <h3>Açık Pozisyonlar</h3>
          <span className="muted small">{state?.positions.length ?? 0} pozisyon</span>
        </div>
        {(state?.positions.length ?? 0) === 0 ? (
          <div className="iempty">
            <span className="iempty-ico">○</span>
            <span>açık pozisyon yok</span>
          </div>
        ) : (
          <div className="tbl-scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th className="num">Boyut</th>
                  <th className="num">Giriş</th>
                  <th className="num">Mark</th>
                  <th className="num">Kald.</th>
                  <th className="num">PnL</th>
                  <th className="num">Likidasyon</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {state?.positions.map((p) => (
                  <tr
                    key={p.symbol}
                    className="clickrow"
                    onClick={() => setSymbol(p.symbol)}
                    title="Bu piyasayı emir formunda seç"
                  >
                    <td>
                      <strong>{p.symbol}</strong>
                    </td>
                    <td>
                      <span className={`side-badge ${p.side === 'LONG' ? 'long' : 'short'}`}>
                        {p.side}
                      </span>
                    </td>
                    <td className="num mono">{p.size}</td>
                    <td className="num mono">{px(p.entry)}</td>
                    <td className="num mono">{px(p.mark)}</td>
                    <td className="num">{p.leverage}×</td>
                    <td className={`num mono ${tone(p.unrealized_pnl)}`}>
                      {usd(p.unrealized_pnl)}
                      {p.roe_pct != null && <span className="muted small"> ({p.roe_pct}%)</span>}
                    </td>
                    <td className="num mono">
                      <span className="neg">{px(p.liq_price)}</span>
                      {p.liq_distance_pct != null && (
                        <span className={`small ${p.liq_distance_pct < 8 ? 'neg' : 'muted'}`}>
                          {' '}
                          %{p.liq_distance_pct}
                        </span>
                      )}
                    </td>
                    <td>
                      <button
                        className="btn small"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation()
                          closePos(p.symbol)
                        }}
                      >
                        Kapat
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(state?.liquidations?.length ?? 0) > 0 && (
          <p className="ifoot neg">
            ⚠ Likide olan pozisyon: {state?.liquidations.map((l) => l.symbol).join(', ')}
          </p>
        )}
      </section>

      {/* --------------------------------------------------- AI otopilot */}
      <section className="card hl-span">
        <div className="card-head">
          <h3>AI Otopilot & Son Kararlar</h3>
          <div className="iwidget-right">
            {ai && (
              <span className="muted small">
                {ai.running ? `tarama açık · ${ai.interval_min} dk` : 'otonom tarama kapalı'} ·{' '}
                {ai.scans} tarama
                {ai.last_error ? ` · son hata: ${ai.last_error}` : ''}
              </span>
            )}
            <button
              className="btn small"
              onClick={async () => {
                try {
                  await api.aiScan()
                  setTimeout(loadState, 1500)
                } catch (e) {
                  setErr(explain(e))
                }
              }}
            >
              ▶ Şimdi tara
            </button>
          </div>
        </div>

        {ai && !ai.enabled && (
          <p className="ifoot muted">
            Otonom tarama kapalı. Açmak için <code>.env</code> → <code>ANALYST_AUTO=1</code>.
            İşlem de açmasını istiyorsan ayrıca <code>HL_AI_AUTOPILOT=1</code>.
          </p>
        )}
        {ai?.enabled && !ai.autopilot && (
          <p className="ifoot muted">
            AI analiz ediyor ama işlem AÇMIYOR (<code>HL_AI_AUTOPILOT=0</code>). Kararları
            aşağıda görüp elle uygulayabilirsin.
          </p>
        )}

        {reports.length === 0 ? (
          <div className="iempty">
            <span className="iempty-ico">○</span>
            <span>henüz AI kararı yok</span>
          </div>
        ) : (
          <div className="ilist iscroll">
            {reports.map((r, i) => (
              <div
                key={`${r.symbol}-${r.ts}-${i}`}
                className="ai-row clickrow"
                onClick={() => setSymbol(r.symbol)}
              >
                <span className="ai-sym">{r.symbol}</span>
                <span
                  className={`bias-badge ${
                    r.bias === 'AL' ? 'pos' : r.bias === 'SAT' ? 'neg' : 'neu'
                  }`}
                >
                  {r.bias || '—'}
                </span>
                <span className="pill">%{Math.round((r.confidence ?? 0) * 100)}</span>
                <span className="ai-trig muted">{r.trigger}</span>
                <span className="ai-sum">{r.summary || r.chart_view || '—'}</span>
                {r.autopilot && (
                  <span className={`pill ${r.autopilot.acted ? 'pos' : 'warn'}`}>
                    {r.autopilot.acted ? 'işlem açıldı' : r.autopilot.reason}
                  </span>
                )}
                <span className="ai-t muted">{clock(r.ts)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ------------------------------------------------------- geçmiş */}
      <section className="card hl-span">
        <div className="card-head">
          <h3>Perp İşlem Geçmişi</h3>
        </div>
        {(state?.history.length ?? 0) === 0 ? (
          <div className="iempty">
            <span className="iempty-ico">○</span>
            <span>işlem yok</span>
          </div>
        ) : (
          <div className="tbl-scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Saat</th>
                  <th>Sembol</th>
                  <th>İşlem</th>
                  <th className="num">Boyut</th>
                  <th className="num">Fiyat</th>
                  <th className="num">PnL</th>
                  <th>Kaynak</th>
                </tr>
              </thead>
              <tbody>
                {state?.history.map((h, i) => (
                  <tr key={`${h.t}-${i}`}>
                    <td className="muted">{clock(h.t)}</td>
                    <td>{h.symbol}</td>
                    <td className={h.action === 'LIQUIDATED' ? 'neg' : ''}>
                      {h.action} {h.side || ''}
                    </td>
                    <td className="num mono">{h.size ?? '—'}</td>
                    <td className="num mono">{px(h.price)}</td>
                    <td className={`num mono ${tone(h.pnl_usd)}`}>
                      {h.pnl_usd != null ? usd(h.pnl_usd) : '—'}
                    </td>
                    <td className="muted">
                      {h.source === 'ai' ? '🤖 AI' : '👤 elle'} · {h.mode}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
