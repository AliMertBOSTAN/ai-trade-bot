import { useEffect, useRef, useState } from 'react'
import {
  api,
  type StrategiesResponse,
  type StrategyAdvice,
  type StrategySignalRow
} from '../api'
import { REGIME_LABELS } from '../lib/ui'

/** Genel strateji profilleri — backend STRATEGY_PRESETS ile hizalı. */
const PRESET_UI: { id: string; icon: string; title: string; desc: string }[] = [
  {
    id: 'safe',
    icon: '🛡️',
    title: 'Güvenli',
    desc: 'Yüksek giriş eşiği (%80) — az ama emin işlem. Hibrit ağırlıklı, kırılım kapalı.'
  },
  {
    id: 'balanced',
    icon: '⚖️',
    title: 'Dengeli',
    desc: 'Orta eşik (%73) — dört strateji eşit ağırlıkta çalışır. Varsayılan profil.'
  },
  {
    id: 'aggressive',
    icon: '🔥',
    title: 'Agresif',
    desc: 'Düşük eşik (%62) — daha sık işlem. Kırılım ve trend ağırlıklı, risk daha yüksek.'
  }
]

/**
 * Strateji KONTROL paneli — işlemleri açan katman burasıdır.
 * Kullanıcı her stratejiyi açıp kapatabilir ve ağırlığını ayarlayabilir;
 * sermaye ağırlıklara göre otomatik bölünür. Rejim yönlendirici (router),
 * o anki piyasa rejimine uymayan stratejileri tick bazında devre dışı bırakır.
 * Değişiklikler backend'e kaydedilir (data/strategies.json) ve kalıcıdır.
 */

const STATUS_STYLE: Record<string, string> = {
  'işlem açıldı': 'pos',
  işlem: 'pos',
  'rejim dışı': 'muted',
  'eşik altı': 'muted',
  cooldown: 'warn',
  'risk reddi': 'neg',
  "aynı tick'te işlendi": 'muted',
  sinyal: 'muted'
}

export default function StrategiesView({ active }: { active: boolean }): JSX.Element {
  const [data, setData] = useState<StrategiesResponse | null>(null)
  const [rows, setRows] = useState<StrategySignalRow[]>([])
  const [err, setErr] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  // Eşik slider'ı: sürüklerken yerel değer, bırakınca backend'e yazılır.
  const [thrDraft, setThrDraft] = useState<number | null>(null)
  const thrTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // AI danışman: öneri al → göster → kullanıcı onaylarsa uygula
  const [advice, setAdvice] = useState<StrategyAdvice | null>(null)
  const [adviceBusy, setAdviceBusy] = useState(false)
  const [applyBusy, setApplyBusy] = useState(false)

  const fetchAdvice = async (): Promise<void> => {
    setAdviceBusy(true)
    try {
      setAdvice(await api.strategyAdvice())
    } catch {
      setAdvice(null)
    } finally {
      setAdviceBusy(false)
    }
  }

  const applyAdvice = async (): Promise<void> => {
    if (!advice) return
    setApplyBusy(true)
    try {
      const r = await api.applyStrategyAdvice(
        advice.strategies.map((s) => ({
          name: s.name,
          enabled: s.enabled,
          weight: s.weight
        })),
        advice.min_confidence
      )
      if (r.strategies) setData(r.strategies)
      setAdvice(null)
      setThrDraft(null)
    } catch {
      /* sonraki load düzeltir */
    } finally {
      setApplyBusy(false)
    }
  }

  const applyPreset = async (name: string): Promise<void> => {
    setBusy(name)
    try {
      const r = await api.applyPreset(name)
      if (r.strategies) setData(r.strategies)
      setThrDraft(null)
    } catch {
      /* sonraki load düzeltir */
    } finally {
      setBusy(null)
    }
  }

  const commitThreshold = (pct: number): void => {
    if (thrTimer.current) clearTimeout(thrTimer.current)
    thrTimer.current = setTimeout(async () => {
      try {
        await api.setRiskConfig(pct / 100)
        const s = await api.strategies()
        setData(s)
        setThrDraft(null)
      } catch {
        /* yok say */
      }
    }, 350)
  }

  const load = async (): Promise<void> => {
    try {
      const [s, sig] = await Promise.all([api.strategies(), api.strategySignals()])
      setData(s)
      setRows(sig)
      setErr(false)
    } catch {
      setErr(true)
    }
  }

  useEffect(() => {
    if (!active) return
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [active])

  const apply = async (
    name: string,
    cfg: { enabled?: boolean; weight?: number }
  ): Promise<void> => {
    setBusy(name)
    try {
      const r = await api.setStrategyConfig(name, cfg)
      setData(r.strategies)
    } catch {
      /* sessizce yoksay; bir sonraki load düzeltir */
    } finally {
      setBusy(null)
    }
  }

  if (err && !data)
    return <div className="muted card">strateji verisi yok — engine çalışıyor mu?</div>

  const active_ = data?.active ?? []
  const catalog = data?.catalog ?? []
  const notInUse = catalog.filter((c) => !c.in_use)
  const regimes = Object.entries(data?.regimes ?? {})
  const thr = thrDraft ?? Math.round((data?.min_confidence ?? 0.73) * 100)
  const preset = data?.preset ?? 'custom'

  return (
    <div className="grid">
      <div className="card span2">
        <div className="card-head">
          <h3>Genel Strateji Profili</h3>
          <span className="muted small">
            {preset === 'custom' ? 'özel ayar (elle değiştirilmiş)' : 'tek tıkla hazır ayar'}
          </span>
        </div>
        <div className="preset-row">
          {PRESET_UI.map((p) => (
            <button
              key={p.id}
              className={`preset-card ${preset === p.id ? 'active' : ''}`}
              disabled={busy === p.id}
              onClick={() => applyPreset(p.id)}
            >
              <div className="preset-title">
                <span className="preset-icon">{p.icon}</span> <b>{p.title}</b>
                {preset === p.id && <span className="preset-check">✓ aktif</span>}
              </div>
              <div className="muted small">{p.desc}</div>
            </button>
          ))}
        </div>
        <div className="thr-row">
          <div className="thr-label">
            <b>Pozisyon giriş eşiği: %{thr}</b>
            <span className="muted small">
              {' '}
              — sinyal güveni bu değerin altındaysa pozisyon AÇILMAZ. Düşük eşik = çok işlem
              (agresif), yüksek eşik = seçici (güvenli).
            </span>
          </div>
          <input
            type="range"
            min={50}
            max={95}
            step={1}
            value={thr}
            onChange={(e) => {
              const v = Number(e.target.value)
              setThrDraft(v)
              commitThreshold(v)
            }}
          />
        </div>
      </div>

      <div className="card span2">
        <div className="card-head">
          <h3>🤖 AI Danışman</h3>
          <span className="muted small">
            performans + rejim analizi → ağırlık/eşik önerisi · sen onaylamadan uygulanmaz
          </span>
        </div>
        {!advice ? (
          <div className="advice-empty">
            <span className="muted small">
              Stratejilerin gerçek performansını (kapanan işlemler) ve anlık piyasa
              rejimini analiz edip ayar önerir. LLM yapılandırılmışsa AI, yoksa
              kural-tabanlı analiz kullanılır.
            </span>
            <button className="btn primary" disabled={adviceBusy} onClick={fetchAdvice}>
              {adviceBusy ? '⏳ Analiz ediliyor…' : '✨ Öneri al'}
            </button>
          </div>
        ) : (
          <div className="advice-box">
            <div className="advice-head">
              <span className={`status-tag ${advice.source === 'llm' ? 'pos' : 'warn'}`}>
                {advice.source === 'llm' ? '🧠 LLM analizi' : '📐 kural-tabanlı analiz'}
              </span>
              <span className="muted small">{advice.rationale}</span>
            </div>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Strateji</th>
                  <th>Durum</th>
                  <th>Ağırlık</th>
                  <th>Performans</th>
                  <th>Not</th>
                </tr>
              </thead>
              <tbody>
                {advice.strategies.map((s) => {
                  const st = advice.stats[s.name]
                  const changed =
                    s.enabled !== s.current_enabled || s.weight !== s.current_weight
                  return (
                    <tr key={s.name} className={changed ? 'advice-changed' : ''}>
                      <td>
                        <b>{s.name}</b>
                      </td>
                      <td>
                        {s.current_enabled === s.enabled ? (
                          <span className="muted">{s.enabled ? 'açık' : 'kapalı'}</span>
                        ) : (
                          <span className={s.enabled ? 'pos' : 'neg'}>
                            {s.current_enabled ? 'açık' : 'kapalı'} → {s.enabled ? 'AÇIK' : 'KAPALI'}
                          </span>
                        )}
                      </td>
                      <td className="mono">
                        {s.current_weight === s.weight ? (
                          <span className="muted">{s.weight}</span>
                        ) : (
                          <span className="pos">
                            {s.current_weight} → <b>{s.weight}</b>
                          </span>
                        )}
                      </td>
                      <td className="muted small">
                        {st && st.trades > 0
                          ? `${st.trades} işlem · WR %${Math.round(st.win_rate * 100)} · ${st.pnl_usd >= 0 ? '+' : ''}${st.pnl_usd}$`
                          : 'veri yok'}
                      </td>
                      <td className="muted small reason" title={s.comment}>
                        {s.comment}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <div className="advice-foot">
              <span className="small">
                Giriş eşiği:{' '}
                {Math.round(advice.current_min_confidence * 100) ===
                Math.round(advice.min_confidence * 100) ? (
                  <span className="muted">%{Math.round(advice.min_confidence * 100)} (değişmedi)</span>
                ) : (
                  <b className="pos">
                    %{Math.round(advice.current_min_confidence * 100)} → %
                    {Math.round(advice.min_confidence * 100)}
                  </b>
                )}
              </span>
              <div className="advice-actions">
                <button className="btn" onClick={() => setAdvice(null)}>
                  Yoksay
                </button>
                <button className="btn" disabled={adviceBusy} onClick={fetchAdvice}>
                  ↻ Yenile
                </button>
                <button className="btn primary" disabled={applyBusy} onClick={applyAdvice}>
                  {applyBusy ? '⏳' : '✓ Öneriyi uygula'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="card span2">
        <div className="card-head">
          <h3>Strateji Kontrolü</h3>
          <span className="muted small">
            işlemleri açan katman — kapalı strateji işlem AÇAMAZ · sermaye otomatik bölünür
          </span>
        </div>
        <div className="hintbar">
          💡 Nasıl çalışır: Sinyaller sekmesindeki hibrit motor + buradaki stratejiler her
          tick karar üretir → rejim yönlendirici piyasaya uymayanları eler → güveni %{thr}
          eşiğini geçenler risk kapılarından geçip işleme dönüşür.
        </div>
        <div className="strat-grid">
          {active_.map((s) => (
            <div key={s.name} className={`strat-card ${s.enabled ? '' : 'off'}`}>
              <div className="strat-name">
                <b>{s.title ?? s.name}</b>
                <label className="switch" title={s.enabled ? 'Açık — işlem açabilir' : 'Kapalı — işlem açamaz'}>
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={busy === s.name}
                    onChange={(e) => apply(s.name, { enabled: e.target.checked })}
                  />
                  <span className="slider" />
                </label>
              </div>
              <div className="muted small strat-desc">{s.description}</div>
              <div className="strat-meta muted small">
                <span>🧭 {s.regime}</span>
                {s.params && s.params !== '—' && <span>⚙ {s.params}</span>}
              </div>
              <div className="strat-bar">
                <div
                  className="strat-fill"
                  style={{ width: `${Math.round(s.capital_fraction * 100)}%` }}
                />
              </div>
              <div className="strat-weight">
                <span className="muted small">
                  sermaye {Math.round(s.capital_fraction * 100)}%
                </span>
                <div className="weight-ctl">
                  <span className="muted small">ağırlık</span>
                  <input
                    type="range"
                    min={0}
                    max={3}
                    step={0.5}
                    value={s.weight}
                    disabled={busy === s.name || !s.enabled}
                    onChange={(e) => apply(s.name, { weight: Number(e.target.value) })}
                  />
                  <b className="mono">{s.weight}</b>
                </div>
              </div>
            </div>
          ))}
          {!active_.length && <div className="muted">strateji yapılandırılmamış</div>}
        </div>

        {notInUse.length > 0 && (
          <div className="catalog">
            <div className="muted small" style={{ margin: '10px 0 6px' }}>
              Kullanılabilir stratejiler (ekleyip açmak için tıkla):
            </div>
            <div className="strat-grid">
              {notInUse.map((c) => (
                <div key={c.name} className="strat-card off">
                  <div className="strat-name">
                    <b>{c.title ?? c.name}</b>
                    <button
                      className="btn primary small"
                      disabled={busy === c.name}
                      onClick={() => apply(c.name, { enabled: true })}
                    >
                      + Ekle
                    </button>
                  </div>
                  <div className="muted small strat-desc">{c.description}</div>
                  <div className="strat-meta muted small">
                    <span>🧭 {c.regime}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {regimes.length > 0 && (
        <div className="card span2">
          <div className="card-head">
            <h3>Anlık Piyasa Rejimi</h3>
            <span className="muted small">
              rejime uymayan stratejiler o token için otomatik beklemede kalır
            </span>
          </div>
          <div className="regime-row">
            {regimes.map(([key, r]) => (
              <span key={key} className={`regime-chip ${r}`}>
                <b>{key.split(':')[1] ?? key}</b> {REGIME_LABELS[r] ?? r}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="card span2">
        <div className="card-head">
          <h3>Canlı Strateji Kararları</h3>
          <span className="muted small">Durum sütunu her kararın akıbetini söyler</span>
        </div>
        <div className="scroll" style={{ maxHeight: 360 }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Strateji</th>
                <th>Token</th>
                <th>Karar</th>
                <th>Güven</th>
                <th>Rejim</th>
                <th>Durum</th>
                <th>Gerekçe</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.strategy}-${r.base}-${i}`}>
                  <td>
                    <b>{r.strategy}</b>
                  </td>
                  <td>{r.base}</td>
                  <td>
                    <span className={`tag ${r.action.toLowerCase()}`}>{r.action}</span>
                  </td>
                  <td className={r.confidence >= 0.6 ? 'pos' : 'muted'}>
                    {Math.round(r.confidence * 100)}%
                  </td>
                  <td className="muted small">{REGIME_LABELS[r.regime ?? ''] ?? r.regime ?? '—'}</td>
                  <td>
                    {r.status ? (
                      <span className={`status-tag ${STATUS_STYLE[r.status] ?? 'muted'}`}>
                        {r.status}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="muted small reason" title={r.reason}>
                    {r.reason}
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={7} className="muted">
                    henüz strateji kararı yok (bot çalışıyor mu?)
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
