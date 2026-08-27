// Seçili pair için AI kararı: POZİSYON AL / BEKLE / GİRME.
//
// Neden ayrı bir kart: otopilot kapalıyken hiçbir işlem açılmıyor ve geçmişte
// bu, "AI hiç bakmadı mı?" hissi veriyordu. Artık karar HER ZAMAN üretilip
// burada gösteriliyor — analist ne düşündü, risk kapısı ne dedi, neden emir
// gönderilmedi. Plan bir tıkla emir formuna aktarılabiliyor.
import type { JSX } from 'react'
import type { AIDecision } from '@shared/types'

const usd = (n?: number | null, d = 0): string =>
  n == null ? '—' : `$${n.toLocaleString('en-US', { maximumFractionDigits: d })}`
const px = (n?: number | null): string =>
  n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: 6 })
const ago = (t?: number): string => {
  if (!t) return 'hiç'
  const s = (Date.now() - t) / 1000
  if (s < 90) return `${Math.round(s)} sn önce`
  if (s < 5400) return `${Math.round(s / 60)} dk önce`
  return `${(s / 3600).toFixed(1)} sa önce`
}

/** Durum → kullanıcının ne yapması gerektiğini söyleyen tek cümle. */
const HINT: Record<string, string> = {
  READY: 'Kapı onayladı. Otopilot kapalı olduğu için emir gönderilmedi — planı forma aktarıp elle açabilirsin.',
  ACTED: 'Otopilot bu planı uyguladı; pozisyon listesinde görünmeli.',
  NO_PLAN: 'Analist net bir yön göremedi. Kurulum oluşana kadar bekle.',
  LOW_CONF: 'Yön var ama güven eşiğin altında. Eşiği HL_AI_MIN_CONFIDENCE ile değiştirebilirsin.',
  HEURISTIC: 'LLM kapalı olduğu için plan üretilmiyor. .env → LLM_PROVIDER + API anahtarı.',
  NO_SCAN: 'Bu pair için henüz analiz yok.',
  BLOCKED: 'Risk kapısı bu işlemi durdurdu. Sebep aşağıda — tavanları gözden geçir ya da bekle.',
  FAILED: 'Emir gönderildi ama borsa reddetti. Gerekçe aşağıda.'
}

export default function DecisionCard({
  decision,
  busy,
  onScan,
  onDryRun,
  onApply
}: {
  decision: AIDecision | null
  busy: boolean
  onScan: () => void
  onDryRun: () => void
  onApply: (side: 'LONG' | 'SHORT', leverage: number, notionalUsd: number) => void
}): JSX.Element {
  const d = decision
  const v = d?.verdict ?? 'wait'
  const plan = d?.plan
  const canApply =
    !!plan && !!d?.side && (plan.approved_notional_usd ?? plan.requested_notional_usd) > 0

  return (
    <section className={`card hl-decision v-${v}`}>
      <div className="card-head">
        <h3>AI Kararı{d?.symbol ? ` · ${d.symbol}` : ''}</h3>
        <div className="iwidget-right">
          <span className="muted small">{d?.ts ? ago(d.ts) : 'tarama yok'}</span>
          <button className="btn small" onClick={onDryRun} disabled={busy || !d || d.state === 'NO_SCAN'} title="Son analizi risk kapısından tekrar geçir — emir gönderilmez">
            Kapıyı dene
          </button>
          <button className="btn small" onClick={onScan} disabled={busy}>
            {busy ? '…' : '🧠 Bu pair’i tara'}
          </button>
        </div>
      </div>

      <div className="dec-hero">
        <span className={`dec-verdict ${v}`}>{d?.label ?? 'BEKLE'}</span>
        {d?.side && <span className={`side-badge ${d.side === 'LONG' ? 'long' : 'short'}`}>{d.side}</span>}
        {d && d.confidence > 0 && (
          <span className="pill">güven %{Math.round(d.confidence * 100)}</span>
        )}
        {d && !d.autopilot && <span className="pill warn">otopilot kapalı</span>}
        {d?.executed && <span className="pill pos">emir gönderildi</span>}
      </div>

      <p className="dec-reason">{d?.reason || 'Karar üretilmedi.'}</p>
      {d && HINT[d.state] && <p className="ifoot muted">{HINT[d.state]}</p>}

      {plan && (
        <>
          <div className="dec-grid">
            <div>
              <span className="dec-k">Kaldıraç (AI seçimi)</span>
              <span className="dec-v">
                {plan.requested_leverage}×
                {plan.approved_leverage && plan.approved_leverage !== plan.requested_leverage && (
                  <span className="muted"> → {plan.approved_leverage}× (kırpıldı)</span>
                )}
              </span>
            </div>
            <div>
              <span className="dec-k">Nosyonel</span>
              <span className="dec-v">
                {usd(plan.requested_notional_usd)}
                {plan.approved_notional_usd != null &&
                  plan.approved_notional_usd !== plan.requested_notional_usd && (
                    <span className="muted"> → {usd(plan.approved_notional_usd)}</span>
                  )}
              </span>
            </div>
            <div>
              <span className="dec-k">Giriş / Stop / Hedef</span>
              <span className="dec-v mono">
                {px(plan.entry)} · <span className="neg">{px(plan.stop)}</span> ·{' '}
                <span className="pos">{px(plan.target)}</span>
              </span>
            </div>
            <div>
              <span className="dec-k">Borsa tavanı</span>
              <span className="dec-v">{plan.exchange_max_leverage}×</span>
            </div>
          </div>

          {plan.leverage_note && (
            <p className="dec-note">
              <b>Kaldıraç gerekçesi:</b> {plan.leverage_note}
            </p>
          )}
          {plan.rationale && <p className="dec-note">{plan.rationale}</p>}

          {d?.gate?.warnings?.map((w, i) => (
            <p key={i} className="ifoot warn">
              ⚠ {w}
            </p>
          ))}

          {canApply && (
            <button
              className="btn primary dec-apply"
              onClick={() =>
                onApply(
                  d!.side as 'LONG' | 'SHORT',
                  plan.approved_leverage || plan.requested_leverage,
                  plan.approved_notional_usd ?? plan.requested_notional_usd
                )
              }
            >
              ↧ Planı emir formuna aktar
            </button>
          )}
        </>
      )}

      {d?.report && (
        <details className="dec-more">
          <summary>Analistin gerekçesi</summary>
          {d.report.macro_view && (
            <p>
              <b>Zemin:</b> {d.report.macro_view}
            </p>
          )}
          {d.report.flow_view && (
            <p>
              <b>Akış:</b> {d.report.flow_view}
            </p>
          )}
          {d.report.chart_view && (
            <p>
              <b>Yapı:</b> {d.report.chart_view}
            </p>
          )}
          {d.report.crowd_view && (
            <p>
              <b>Kalabalık:</b> {d.report.crowd_view}
            </p>
          )}
          {(d.report.conflicts?.length ?? 0) > 0 && (
            <p className="warn">
              <b>Çelişki:</b> {d.report.conflicts!.join(' · ')}
            </p>
          )}
        </details>
      )}
    </section>
  )
}
