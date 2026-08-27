// AI Analist — tek sembol için tam görüş.
// Eskiden 8 sembole sabitti ve LLM bütçesi 600 token'dı; artık:
//   · sembol arama kutusu (Hyperliquid + izleme listesi, yüzlerce token)
//   · analiz derinliği seçimi (token bütçesi) — kısa/normal/derin/çok derin
//   · zengin çıktı: makro zemin, akış, teknik, kalabalık, seviyeler,
//     senaryolar, çelişkiler ve somut perp işlem planı
import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from 'react'
import { api } from '../api'
import type { AnalystDepthOption, AnalystReport, AnalystUniverseRow } from '@shared/types'

const sentimentTone = (s?: string): string =>
  s === 'BULLISH' ? 'pos' : s === 'BEARISH' ? 'neg' : 'neu'

const biasTone = (b?: string): string => (b === 'AL' ? 'pos' : b === 'SAT' ? 'neg' : 'neu')

const usd0 = (n?: number | null): string =>
  n == null ? '—' : `$${Math.round(n).toLocaleString('en-US')}`

const px = (n?: number | null): string =>
  n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: 6 })

export default function AnalystPanel(): JSX.Element {
  const [symbol, setSymbol] = useState('BTC')
  const [query, setQuery] = useState('')
  const [openList, setOpenList] = useState(false)
  const [universe, setUniverse] = useState<AnalystUniverseRow[]>([])
  const [depths, setDepths] = useState<AnalystDepthOption[]>([])
  const [depth, setDepth] = useState('normal')
  const [report, setReport] = useState<AnalystReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api
      .analystUniverse(400)
      .then((u) => setUniverse(u.rows))
      .catch(() => {})
    api
      .analystDepths()
      .then((d) => {
        setDepths(d.options)
        setDepth(d.default)
      })
      .catch(() => {})
  }, [])

  // Dışarı tıklayınca arama listesini kapat
  useEffect(() => {
    const onDoc = (e: MouseEvent): void => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpenList(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase()
    const rows = q ? universe.filter((r) => r.symbol.includes(q)) : universe
    return rows.slice(0, 40)
  }, [query, universe])

  const run = useCallback(async (): Promise<void> => {
    setLoading(true)
    setErr('')
    try {
      setReport(await api.analystRun(symbol, depth))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [symbol, depth])

  const llm = report?.llm
  const whale = report?.whales
  const deriv = report?.derivatives
  const trade = llm?.trade
  const wTone = (s?: number): string => ((s ?? 0) > 0.15 ? 'pos' : (s ?? 0) < -0.15 ? 'neg' : 'neu')
  const tokens = depths.find((d) => d.id === depth)?.tokens

  return (
    <div className="analyst">
      <div className="analyst-bar">
        <div className="sym-picker" ref={boxRef}>
          <input
            className="search"
            value={openList ? query : symbol}
            placeholder="Sembol ara — BTC, HYPE, SOL…"
            onFocus={() => {
              setOpenList(true)
              setQuery('')
            }}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Analiz edilecek sembol"
          />
          {openList && (
            <div className="sym-list">
              {matches.length === 0 && <div className="sym-empty">eşleşme yok</div>}
              {matches.map((r) => (
                <button
                  key={r.symbol}
                  className="sym-item"
                  onClick={() => {
                    setSymbol(r.symbol)
                    setOpenList(false)
                  }}
                >
                  <span className="sym-s">{r.symbol}</span>
                  {r.perp && <span className="sym-lev">{r.max_leverage}×</span>}
                  {r.volume_usd != null && (
                    <span className="sym-v muted">{usd0(r.volume_usd)}</span>
                  )}
                  <span className="sym-src muted">{r.source}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="seg depth-seg" role="group" aria-label="Analiz derinliği">
          {depths.map((d) => (
            <button
              key={d.id}
              className={depth === d.id ? 'active' : ''}
              title={`${d.note} · ${d.tokens} token`}
              onClick={() => setDepth(d.id)}
            >
              {d.label}
            </button>
          ))}
        </div>

        <button className="run" onClick={run} disabled={loading}>
          {loading ? 'Analiz ediliyor…' : '🧠 AI Analiz'}
        </button>
        <span className="muted small">
          makro + akış + teknik + haber → görüş{tokens ? ` · ${tokens} token` : ''}
        </span>
      </div>

      {err && <div className="muted">Hata: {err}</div>}

      {report && (
        <div className="analyst-body">
          {llm?.note && <div className="callout">{llm.note}</div>}
          {llm?.heuristic && (
            <div className="callout muted small">
              LLM kapalı — bu görüş teknik sinyal + haber tonu + yapı skorundan üretildi
              (sezgisel). Tam analiz için .env'de LLM_PROVIDER + API key tanımlayın.
            </div>
          )}

          <div className="analyst-verdict">
            {llm?.bias && <span className={`bias-badge ${biasTone(llm.bias)}`}>{llm.bias}</span>}
            {llm?.sentiment && (
              <span className={`sentiment ${sentimentTone(llm.sentiment)}`}>{llm.sentiment}</span>
            )}
            {llm?.confidence != null && (
              <span className="pill">güven %{Math.round(llm.confidence * 100)}</span>
            )}
            {llm?.horizon && <span className="pill">{llm.horizon}</span>}
            <span className="muted small">{report.symbol}</span>
          </div>

          {llm?.summary && <div className="analyst-summary">{llm.summary}</div>}

          {/* Katman katman görüş — promptun çalışma sırasıyla aynı */}
          <div className="analyst-grid">
            {llm?.macro_view && (
              <div className="acard">
                <h4>1 · Makro zemin</h4>
                <p>{llm.macro_view}</p>
              </div>
            )}
            {llm?.flow_view && (
              <div className="acard">
                <h4>2 · Akışlar</h4>
                <p>{llm.flow_view}</p>
              </div>
            )}
            {llm?.chart_view && (
              <div className="acard">
                <h4>3 · Teknik yapı</h4>
                <p>{llm.chart_view}</p>
              </div>
            )}
            {llm?.crowd_view && (
              <div className="acard">
                <h4>4 · Kalabalık</h4>
                <p>{llm.crowd_view}</p>
              </div>
            )}
          </div>

          {(llm?.levels || trade) && (
            <div className="analyst-grid">
              {llm?.levels && (
                <div className="acard">
                  <h4>Seviyeler</h4>
                  <ul>
                    <li>
                      Destek:{' '}
                      <span className="pos">
                        {(llm.levels.support || []).map(px).join(' · ') || '—'}
                      </span>
                    </li>
                    <li>
                      Direnç:{' '}
                      <span className="neg">
                        {(llm.levels.resistance || []).map(px).join(' · ') || '—'}
                      </span>
                    </li>
                    <li>
                      Geçersizleşme: <span className="mono">{px(llm.levels.invalidation)}</span>
                    </li>
                  </ul>
                </div>
              )}
              {trade && trade.side !== 'YOK' && (
                <div className="acard trade-plan">
                  <h4>
                    İşlem planı ·{' '}
                    <span className={trade.side === 'LONG' ? 'pos' : 'neg'}>{trade.side}</span>
                  </h4>
                  <ul>
                    <li>Giriş: <span className="mono">{px(trade.entry)}</span></li>
                    <li>Stop: <span className="mono neg">{px(trade.stop)}</span></li>
                    <li>Hedef: <span className="mono pos">{px(trade.target)}</span></li>
                    <li>
                      Kaldıraç: <b>{trade.leverage}×</b> · boyut ipucu %{trade.size_hint_pct}
                    </li>
                  </ul>
                  <p className="muted small">{trade.rationale}</p>
                  <p className="muted small">
                    Bu plan otomatik uygulanmaz — Hyperliquid sekmesinde otopilot açıksa
                    risk kapılarından geçtikten sonra işleme dönüşür.
                  </p>
                </div>
              )}
            </div>
          )}

          {llm?.scenarios && llm.scenarios.length > 0 && (
            <div className="acard">
              <h4>Senaryolar</h4>
              <ul>
                {llm.scenarios.map((s, i) => (
                  <li key={i}>
                    <b>{s.name}</b> <span className="pill">%{Math.round(s.probability * 100)}</span>{' '}
                    {s.note}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {llm?.conflicts && llm.conflicts.length > 0 && (
            <div className="callout warn">
              <b>Katmanlar arası çelişki:</b>
              <ul>
                {llm.conflicts.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}

          {llm?.risks && llm.risks.length > 0 && (
            <div className="acard">
              <h4>Riskler</h4>
              <ul>
                {llm.risks.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Sayısal dayanaklar */}
          <div className="analyst-grid">
            {whale && (
              <div className="acard">
                <h4>Balina akışı</h4>
                <p>
                  <span className={`whale-badge ${wTone(whale.pressure?.score)}`}>
                    {whale.label}
                  </span>{' '}
                  alım {usd0(whale.pressure?.buy_usd)} · satım {usd0(whale.pressure?.sell_usd)}
                </p>
              </div>
            )}
            {deriv?.ok && (
              <div className="acard">
                <h4>Türev</h4>
                <p>
                  funding {deriv.funding_pct?.toFixed(4)}% · OI {deriv.oi_change_pct}% · L/S{' '}
                  {deriv.ls_ratio} · {deriv.squeeze?.direction}
                </p>
              </div>
            )}
          </div>

          {llm?.raw && (
            <details className="analyst-raw">
              <summary>Ham LLM yanıtı</summary>
              <pre>{llm.raw}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
