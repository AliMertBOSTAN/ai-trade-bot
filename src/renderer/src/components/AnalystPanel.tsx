import { useState } from 'react'
import { api } from '../api'
import type { AnalystReport } from '@shared/types'

const SYMBOLS = ['ETH', 'BTC', 'BNB', 'MATIC', 'ARB', 'OP', 'LINK', 'UNI']

const sentimentTone = (s?: string): string =>
  s === 'BULLISH' ? 'pos' : s === 'BEARISH' ? 'neg' : 'neu'

const biasTone = (b?: string): string =>
  b === 'AL' ? 'pos' : b === 'SAT' ? 'neg' : 'neu'

export default function AnalystPanel(): JSX.Element {
  const [symbol, setSymbol] = useState('ETH')
  const [report, setReport] = useState<AnalystReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async (): Promise<void> => {
    setLoading(true)
    setErr('')
    try {
      setReport(await api.analyst(symbol))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const llm = report?.llm
  const whale = report?.whales
  const deriv = report?.derivatives
  const wTone = (s?: number): string => ((s ?? 0) > 0.15 ? 'pos' : (s ?? 0) < -0.15 ? 'neg' : 'neu')
  const sqTone = (s?: number): string => ((s ?? 0) > 0.2 ? 'pos' : (s ?? 0) < -0.2 ? 'neg' : 'neu')
  const usd0 = (n?: number): string =>
    n == null ? '—' : `$${Math.round(n).toLocaleString('en-US')}`
  return (
    <div className="analyst">
      <div className="analyst-bar">
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {SYMBOLS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="run" onClick={run} disabled={loading}>
          {loading ? 'Analiz ediliyor…' : '🧠 AI Analiz'}
        </button>
        <span className="muted small">grafik + haber + balina akışı → al/sat görüşü</span>
      </div>

      {err && <div className="muted">Hata: {err}</div>}

      {report && (
        <div className="analyst-body">
          {llm?.note && <div className="callout">{llm.note}</div>}
          {llm?.heuristic && (
            <div className="callout muted small">
              LLM kapalı — bu görüş teknik sinyal + haber tonundan üretildi (sezgisel).
              Daha derin yorum için .env'de LLM_PROVIDER + API key tanımlayın.
            </div>
          )}

          <div className="analyst-verdict">
            {llm?.bias && (
              <span className={`bias-badge ${biasTone(llm.bias)}`}>{llm.bias}</span>
            )}
            {llm?.sentiment && (
              <span className={`sentiment ${sentimentTone(llm.sentiment)}`}>
                {llm.sentiment}
                {typeof llm.confidence === 'number' && (
                  <span className="muted small"> · güven {(llm.confidence * 100).toFixed(0)}%</span>
                )}
              </span>
            )}
          </div>

          {llm?.summary && <p className="analyst-summary">{llm.summary}</p>}

          {whale && whale.pressure && (
            <div className="acard whale-card">
              <h4>🐋 Balina Akışı</h4>
              <div className="whale-row">
                <span className={`whale-badge ${wTone(whale.pressure.score)}`}>
                  {whale.label}
                </span>
                <span className="muted small">
                  alım {usd0(whale.pressure.buy_usd)} ({whale.pressure.buy_count}) · satım{' '}
                  {usd0(whale.pressure.sell_usd)} ({whale.pressure.sell_count}) ·{' '}
                  {whale.pressure.big_count} büyük emir
                </span>
              </div>
              {(whale.walls?.bids?.length > 0 || whale.walls?.asks?.length > 0) && (
                <div className="muted small whale-walls">
                  {whale.walls.bids[0] && (
                    <span className="pos">
                      Destek (alış duvarı): {whale.walls.bids[0].price} · {usd0(whale.walls.bids[0].usd)}
                    </span>
                  )}
                  {whale.walls.asks[0] && (
                    <span className="neg">
                      Direnç (satış duvarı): {whale.walls.asks[0].price} · {usd0(whale.walls.asks[0].usd)}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}

          {deriv && deriv.ok && (
            <div className="acard whale-card">
              <h4>⚡ Türev / Likidasyon</h4>
              <div className="whale-row">
                <span className={`whale-badge ${sqTone(deriv.squeeze?.score)}`}>
                  {deriv.squeeze?.direction ?? 'nötr'}
                </span>
                <span className="muted small">
                  funding {deriv.funding_pct?.toFixed(4)}% · OI {deriv.oi_change_pct >= 0 ? '+' : ''}
                  {deriv.oi_change_pct?.toFixed(2)}% · L/S {deriv.ls_ratio}
                  {deriv.squeeze?.cascade && <span className="neg"> · likidasyon kaskadı</span>}
                </span>
              </div>
              {deriv.squeeze?.notes?.length > 0 && (
                <div className="muted small whale-walls">{deriv.squeeze.notes.join(' · ')}</div>
              )}
            </div>
          )}

          <div className="analyst-grid">
            {llm?.chart_view && (
              <div className="acard">
                <h4>📈 Grafik Yorumu</h4>
                <p>{llm.chart_view}</p>
              </div>
            )}
            {llm?.crowd_view && (
              <div className="acard">
                <h4>👥 Kalabalık Ne Planlıyor</h4>
                <p>{llm.crowd_view}</p>
              </div>
            )}
            {llm?.cex_dex_view && (
              <div className="acard">
                <h4>CEX / DEX</h4>
                <p>{llm.cex_dex_view}</p>
              </div>
            )}
            {llm?.news_impact && (
              <div className="acard">
                <h4>Haber Etkisi</h4>
                <p>{llm.news_impact}</p>
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
          </div>

          {llm?.raw && <pre className="analyst-raw">{llm.raw}</pre>}

          {report.headlines?.length > 0 && (
            <div className="acard">
              <h4>Kullanılan başlıklar</h4>
              <ul>
                {report.headlines.slice(0, 6).map((h, i) => (
                  <li key={i} className="muted small">
                    [{h.source}] {h.title}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {!report && !loading && (
        <div className="muted">Bir sembol seçip “AI Analiz”e basın.</div>
      )}
    </div>
  )
}
