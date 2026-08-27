import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { GoalReport, LeverageAssessment, LeverageSweep } from '@shared/types'
import { usd } from '../lib/ui'

const pct = (n: number | null | undefined, d = 2): string =>
  Number.isFinite(n) ? `${(n as number).toFixed(d)}%` : '—'

/** Gerçekçilik bandı -> renk sınıfı. */
function feasClass(f: string | undefined): string {
  if (f === 'makul') return 'ok'
  if (f === 'zorlu') return 'warn'
  return 'bad'
}

function GoalCard({ g, onSave }: { g: GoalReport; onSave: (t: number, m: number) => void }): JSX.Element {
  const [target, setTarget] = useState(g.goal?.target_usd || 420000)
  const [months, setMonths] = useState(g.goal?.horizon_months || 24)

  return (
    <div className="card">
      <div className="card-head">
        <h3>Hedef</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="input"
            type="number"
            value={target}
            onChange={(e) => setTarget(Number(e.target.value))}
            style={{ width: 120 }}
            aria-label="Hedef tutar (USD)"
          />
          <input
            className="input"
            type="number"
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            style={{ width: 70 }}
            aria-label="Ufuk (ay)"
          />
          <button className="btn" onClick={() => onSave(target, months)}>
            Kaydet
          </button>
        </div>
      </div>

      {!g.active ? (
        <div className="muted">{g.message || 'Hedef tanımlı değil.'}</div>
      ) : (
        <>
          <div className="kpis">
            <div className="kpi">
              <span className="kpi-label">Mevcut</span>
              <span className="kpi-value">{usd(g.current_equity_usd)}</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Hedef</span>
              <span className="kpi-value">{usd(g.goal.target_usd)}</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Gereken çarpan</span>
              <span className="kpi-value">
                {g.required_multiple ? `${g.required_multiple.toLocaleString('tr-TR')}×` : '—'}
              </span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Gereken yıllık</span>
              <span className={`kpi-value ${feasClass(g.feasibility)}`}>
                {pct(g.required_cagr_pct, 0)}
              </span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Gereken günlük</span>
              <span className={`kpi-value ${feasClass(g.feasibility)}`}>
                {pct(g.required_daily_pct, 3)}
              </span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Ölçülen yıllık</span>
              <span className="kpi-value">{pct(g.actual_cagr_pct, 1)}</span>
            </div>
          </div>

          <div className={`alert ${feasClass(g.feasibility)}`}>
            Gerçekçilik: <b>{g.feasibility}</b> — {g.feasibility_note}
          </div>

          <div className="muted small">
            İlerleme: %{(g.progress_pct ?? 0).toFixed(4)} · Kalan süre:{' '}
            {(g.remaining_years ?? 0).toFixed(2)} yıl
            {g.years_to_target_at_actual != null && (
              <>
                {' '}
                · Ölçülen hızla varış: {g.years_to_target_at_actual} yıl ({g.eta_at_actual})
              </>
            )}
            {g.monthly_dca_needed_usd != null && (
              <> · Gereken aylık ekleme: {usd(g.monthly_dca_needed_usd)}</>
            )}
          </div>

          {(g.warnings || []).map((w, i) => (
            <div className="muted small" key={i}>
              ⚠️ {w}
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function LeverageCard({ a }: { a: LeverageAssessment }): JSX.Element {
  const d = a.decision
  const ruinPct = (a.risk_of_ruin * 100).toFixed(2)
  return (
    <div className="card">
      <h3>Kaldıraç kararı (Kelly)</h3>
      <div className="kpis">
        <div className="kpi">
          <span className="kpi-label">Kaldıraç</span>
          <span className={`kpi-value ${d.leverage > 1 ? 'warn' : 'ok'}`}>
            {d.leverage.toFixed(2)}×
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Kelly kesri</span>
          <span className="kpi-value">{d.kelly.toFixed(3)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Likidasyon mesafesi</span>
          <span className="kpi-value">{pct(a.liquidation_distance_pct, 1)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">İflas olasılığı</span>
          <span className={`kpi-value ${a.risk_of_ruin >= 1 ? 'bad' : 'warn'}`}>
            {ruinPct}%
          </span>
        </div>
      </div>
      <div className="muted small">
        Gerekçe: {d.reason}
        {a.liquidation_price != null && <> · Likidasyon fiyatı: {usd(a.liquidation_price)}</>}
      </div>
      <div className="muted small">
        Ölçülen: {d.stats.samples} işlem · kazanma %{(d.stats.win_prob * 100).toFixed(0)} ·
        kazanç/kayıp {d.stats.win_loss_ratio} · net {usd(d.stats.net)}
      </div>
      {a.target && (
        <div className="alert bad">
          Hedef {a.target.multiple?.toLocaleString('tr-TR')}× — kenarsız piyasada ulaşma
          olasılığının üst sınırı <b>1 / {a.target.one_in?.toLocaleString('tr-TR')}</b> (%
          {a.target.fair_upper_bound_pct}). Bu sınır <b>kaldıraçla değişmez</b>.
        </div>
      )}
    </div>
  )
}

function SweepCard({ s }: { s: LeverageSweep }): JSX.Element {
  return (
    <div className="card">
      <h3>
        Kaldıraç taraması — {s.symbol} {s.interval} (kaldıraçsız {pct(s.spot_return_pct)})
      </h3>
      <table className="table">
        <thead>
          <tr>
            <th>Kaldıraç</th>
            <th>Getiri</th>
            <th>Maks. düşüş</th>
            <th>Funding</th>
            <th>Komisyon</th>
            <th>Durum</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.map((r) => (
            <tr key={r.leverage} className={r.liquidated ? 'bad' : undefined}>
              <td>{r.leverage}×</td>
              <td className={r.total_return_pct >= 0 ? 'ok' : 'bad'}>
                {pct(r.total_return_pct)}
              </td>
              <td>{pct(r.max_drawdown_pct, 1)}</td>
              <td className="muted">{pct(r.funding_cost_pct, 2)}</td>
              <td className="muted">{pct(r.fee_cost_pct, 2)}</td>
              <td>{r.liquidated ? `LİKİDE (bar ${r.liquidation_bar})` : 'ayakta'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="muted small">
        Geçmişte en iyi: <b>{s.best_leverage}×</b> ({pct(s.best_return_pct)})
        {s.first_liquidating_leverage != null && (
          <> · İlk likide olan: {s.first_liquidating_leverage}×</>
        )}
        <br />
        {s.note}
      </div>
    </div>
  )
}

/**
 * Hedef & Risk paneli — hedefin gerektirdiği getiriyi, botun ölçülen
 * getirisini, kaldıraç kararını ve likidasyon/iflas matematiğini gösterir.
 * Hiçbir ayarı DEĞİŞTİRMEZ.
 */
export default function RiskPanel(): JSX.Element {
  const [goal, setGoal] = useState<GoalReport | null>(null)
  const [lev, setLev] = useState<LeverageAssessment | null>(null)
  const [sweep, setSweep] = useState<LeverageSweep | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const [g, l] = await Promise.all([api.goal(), api.leverage(0.8, 0)])
      setGoal(g)
      setLev(l)
      setErr('')
    } catch {
      setErr('hedef/risk verisine ulaşılamadı (engine çalışıyor mu?)')
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  const saveGoal = async (t: number, m: number): Promise<void> => {
    try {
      setGoal(await api.setGoal(t, m))
    } catch {
      setErr('hedef kaydedilemedi')
    }
  }

  const runSweep = async (): Promise<void> => {
    setBusy(true)
    try {
      setSweep(await api.leverageSweep('BTCUSDT', '4h'))
    } catch {
      setErr('kaldıraç taraması başarısız (ağ?)')
    } finally {
      setBusy(false)
    }
  }

  if (err && !goal) return <div className="muted">{err}</div>
  if (!goal || !lev) return <div className="muted">hedef/risk yükleniyor…</div>

  return (
    <>
      <GoalCard g={goal} onSave={saveGoal} />
      <LeverageCard a={lev} />
      <div className="card">
        <div className="card-head">
          <h3>Kaldıracın gerçek veride etkisi</h3>
          <button className="btn" onClick={runSweep} disabled={busy}>
            {busy ? 'ölçülüyor…' : 'Taramayı çalıştır'}
          </button>
        </div>
        {!sweep && (
          <div className="muted">
            Gerçek Binance verisiyle 1×–50× arası kaldıracı ölçer; ücret, funding ve
            likidasyon bariyeri dahildir.
          </div>
        )}
      </div>
      {sweep && <SweepCard s={sweep} />}
      {err && <div className="muted small">⚠️ {err}</div>}
    </>
  )
}
