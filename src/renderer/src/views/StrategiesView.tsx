import { useEffect, useState } from 'react'
import { api, type StrategiesResponse, type StrategySignalRow } from '../api'

/**
 * Strateji KONTROL paneli: kullanıcı her stratejiyi açıp kapatabilir ve
 * ağırlığını ayarlayabilir. Ayrıca her stratejinin ne yaptığını (detaylı
 * açıklama + uygun rejim + parametreler) ve canlı kararlarını gösterir.
 * Değişiklikler backend'e kaydedilir (data/strategies.json) ve kalıcıdır.
 */
export default function StrategiesView({ active }: { active: boolean }): JSX.Element {
  const [data, setData] = useState<StrategiesResponse | null>(null)
  const [rows, setRows] = useState<StrategySignalRow[]>([])
  const [err, setErr] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

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

  if (err && !data) return <div className="muted card">strateji verisi yok — engine çalışıyor mu?</div>

  // Aktif tahsisler (describe) + kayıttaki ağırlık/aç-kapa bilgisi
  const active_ = data?.active ?? []
  // Katalog: aktif olmayan ama kullanılabilir stratejiler
  const catalog = data?.catalog ?? []
  const notInUse = catalog.filter((c) => !c.in_use)

  return (
    <div className="grid">
      <div className="card span2">
        <div className="card-head">
          <h3>Strateji Kontrolü</h3>
          <span className="muted small">aç/kapa · ağırlık · sermaye otomatik bölünür</span>
        </div>
        <div className="strat-grid">
          {active_.map((s) => (
            <div key={s.name} className={`strat-card ${s.enabled ? '' : 'off'}`}>
              <div className="strat-name">
                <b>{s.title ?? s.name}</b>
                <label className="switch" title={s.enabled ? 'Açık' : 'Kapalı'}>
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

      <div className="card span2">
        <h3>Canlı Strateji Kararları</h3>
        <div className="scroll" style={{ maxHeight: 360 }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Strateji</th>
                <th>Token</th>
                <th>Karar</th>
                <th>Güven</th>
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
                  <td className="muted small reason" title={r.reason}>
                    {r.reason}
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={5} className="muted">
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
