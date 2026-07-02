import { memo } from 'react'
import Indicators from '../components/Indicators'
import { TRADE_THRESHOLD } from '../lib/ui'
import type { TradeSignal } from '@shared/types'

function SignalBreakdownView({ s, threshold }: { s: TradeSignal; threshold: number }): JSX.Element | null {
  const b = s.breakdown
  if (!b) return null
  const conf = Math.round(b.finalConfidence * 100)
  const willTrade = conf >= threshold && s.action !== 'HOLD'
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
        Emin olma: <b>{conf}%</b>{' '}
        {willTrade
          ? '✓ eşik üstü — strateji & risk kapılarına gider'
          : `· eşik %${threshold} altı — işlem açılmaz`}
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

// Tek sinyal kartı — memoize. 5sn poll + WS her tikte yeni dizi üretse de,
// id/aksiyon/güven aynıysa kart YENİDEN RENDER OLMAZ (gereksiz re-render önlenir).
const conf100 = (s: TradeSignal): number =>
  Math.round((s.breakdown?.finalConfidence ?? s.confidence) * 100)

const SignalCard = memo(
  function SignalCard({ s, threshold }: { s: TradeSignal; threshold: number }): JSX.Element {
    const conf = conf100(s)
    const willTrade = conf >= threshold && s.action !== 'HOLD'
    return (
      <div className={`sigcard ${willTrade ? 'trade' : ''}`}>
        <div className="sigcard-head">
          <span className={`tag ${s.action.toLowerCase()}`}>{s.action}</span>
          <b>{s.base}</b>
          <span className={`sig-conf ${willTrade ? 'pos' : 'muted'}`}>{conf}%</span>
          <span className="muted small">{s.source}</span>
        </div>
        <SignalBreakdownView s={s} threshold={threshold} />
        <Indicators tech={s.technical} />
      </div>
    )
  },
  (a, b) =>
    a.s.id === b.s.id &&
    a.s.action === b.s.action &&
    conf100(a.s) === conf100(b.s) &&
    a.threshold === b.threshold
)

export default function SignalsView({
  signals,
  threshold = TRADE_THRESHOLD
}: {
  signals: TradeSignal[]
  threshold?: number
}): JSX.Element {
  if (!signals.length) return <div className="muted card">sinyal yok — bot çalışıyor mu?</div>
  return (
    <div className="siglist">
      {signals.slice(0, 16).map((s) => (
        <SignalCard key={s.id} s={s} threshold={threshold} />
      ))}
    </div>
  )
}
