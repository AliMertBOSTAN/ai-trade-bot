import { useEffect, useState } from 'react'
import { api, type PerformanceReport } from '../api'

/**
 * Risk-ayarlı performans paneli: Sharpe, Sortino, Max Drawdown, Calmar,
 * kazanma oranı, profit factor ve beklenti (expectancy). Veriler backend
 * /performance ucundan gelir; equity eğrisi + işlem geçmişinden hesaplanır.
 */
export default function PerformancePanel({ active = true }: { active?: boolean }): JSX.Element {
  const [p, setP] = useState<PerformanceReport | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    if (!active) return
    const load = async (): Promise<void> => {
      try {
        setP(await api.performance())
        setErr(false)
      } catch {
        setErr(true)
      }
    }
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [active])

  const pct = (v?: number): string => (v == null ? '—' : `${(v * 100).toFixed(0)}%`)
  const num = (v?: number, d = 2): string => (v == null || !isFinite(v) ? '—' : v.toFixed(d))

  if (err && !p)
    return (
      <div className="card">
        <h3>Performans</h3>
        <div className="muted small">veri yok — engine çalışıyor mu?</div>
      </div>
    )

  const ret = p?.total_return_pct ?? 0
  const wr = p?.win_rate
  const pf = p?.profit_factor

  return (
    <div className="card">
      <div className="card-head">
        <h3>Performans</h3>
        <span className="muted small">
          {p?.trades ?? 0} kapanış · çıkış: {p?.exit_style === 'atr' ? 'ATR trailing' : 'sabit %'}
        </span>
      </div>
      <div className="perf-grid">
        <Metric
          label="Toplam Getiri"
          value={`${ret >= 0 ? '+' : ''}${num(ret, 2)}%`}
          cls={ret > 0 ? 'pos' : ret < 0 ? 'neg' : ''}
          hint="Equity eğrisinin başından bugüne değişim"
        />
        <Metric
          label="Sharpe"
          value={num(p?.sharpe)}
          cls={(p?.sharpe ?? 0) > 1 ? 'pos' : ''}
          hint="Risk başına getiri (yıllıklandırılmış); >1 iyi, >2 çok iyi"
        />
        <Metric
          label="Sortino"
          value={num(p?.sortino)}
          cls={(p?.sortino ?? 0) > 1 ? 'pos' : ''}
          hint="Sadece aşağı yön oynaklığını cezalandırır"
        />
        <Metric
          label="Max Drawdown"
          value={`−${num(p?.max_drawdown_pct, 2)}%`}
          cls={(p?.max_drawdown_pct ?? 0) > 15 ? 'neg' : ''}
          hint="En büyük tepe→dip düşüş"
        />
        <Metric
          label="Calmar"
          value={num(p?.calmar)}
          hint="Yıllık getiri / max drawdown"
        />
        <Metric
          label="Kazanma Oranı"
          value={pct(wr)}
          cls={wr != null && wr >= 0.5 ? 'pos' : ''}
          hint="Kârla kapanan işlemlerin oranı"
        />
        <Metric
          label="Profit Factor"
          value={num(pf)}
          cls={pf != null && pf > 1.5 ? 'pos' : pf != null && pf < 1 ? 'neg' : ''}
          hint="Brüt kâr / brüt zarar; >1.5 sağlıklı"
        />
        <Metric
          label="Beklenti"
          value={p?.expectancy_usd != null ? `$${num(p.expectancy_usd)}` : '—'}
          cls={(p?.expectancy_usd ?? 0) > 0 ? 'pos' : (p?.expectancy_usd ?? 0) < 0 ? 'neg' : ''}
          hint="İşlem başına ortalama kazanç/kayıp"
        />
      </div>
      <div className="muted small" style={{ marginTop: 8 }}>
        Günlük gerçekleşen: {p ? `$${num(p.day_realized_pnl_usd)}` : '—'} · işlem başına risk: %
        {p ? num((p.risk_pct_per_trade ?? 0) * 100, 1) : '—'} (ATR boyutlama)
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  cls,
  hint
}: {
  label: string
  value: string
  cls?: string
  hint?: string
}): JSX.Element {
  return (
    <div className="perf-metric" title={hint}>
      <div className="perf-label">{label}</div>
      <div className={`perf-value ${cls ?? ''}`}>{value}</div>
    </div>
  )
}
