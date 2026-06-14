import { useState } from 'react'
import { api } from '../api'
import type { AnalystReport } from '@shared/types'

const SYMBOLS = ['ETH', 'BTC', 'BNB', 'MATIC', 'ARB', 'OP', 'LINK', 'UNI']

const sentimentTone = (s?: string): string =>
  s === 'BULLISH' ? 'pos' : s === 'BEARISH' ? 'neg' : 'neu'

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
        <span className="muted small">CEX/DEX + haber → LLM yorumu</span>
      </div>

      {err && <div className="muted">Hata: {err}</div>}

      {report && (
        <div className="analyst-body">
          {llm?.note && <div className="callout">{llm.note}</div>}

          {llm?.sentiment && (
            <div className={`sentiment ${sentimentTone(llm.sentiment)}`}>
              {llm.sentiment}
              {typeof llm.confidence === 'number' && (
                <span className="muted small"> · güven {(llm.confidence * 100).toFixed(0)}%</span>
              )}
            </div>
          )}

          {llm?.summary && <p className="analyst-summary">{llm.summary}</p>}

          <div className="analyst-grid">
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
