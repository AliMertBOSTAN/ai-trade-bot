import { useEffect, useState } from 'react'
import { api, type ChainsResponse } from '../api'

/**
 * Ağ (zincir) seçimi: kullanıcı botun HANGİ zincirlerde işlem yapacağını
 * toggle anahtarlarıyla açıp kapatır. "Hepsi" / "Hiçbiri" kısayolları var.
 * Seçim backend'e kaydedilir (data/chains.json) ve yeniden başlatınca korunur.
 * Hiçbiri açık değilse bot fiyat çekmez/işlem yapmaz (duraklatma gibi).
 */
export default function ChainsPanel(): JSX.Element {
  const [data, setData] = useState<ChainsResponse | null>(null)
  const [busy, setBusy] = useState(false)

  const load = async (): Promise<void> => {
    try {
      setData(await api.chains())
    } catch {
      /* engine kapalı olabilir */
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  const toggle = async (id: number, active: boolean): Promise<void> => {
    setBusy(true)
    try {
      setData(await api.setChain(id, active))
    } finally {
      setBusy(false)
    }
  }

  const setAll = async (all: boolean): Promise<void> => {
    if (!data) return
    setBusy(true)
    try {
      const ids = all ? data.chains.map((c) => c.chain_id) : []
      setData(await api.setChains(ids))
    } finally {
      setBusy(false)
    }
  }

  const chains = data?.chains ?? []
  const activeCount = data?.active_count ?? 0

  return (
    <div className="card">
      <div className="card-head">
        <h3>Ağlar (İşlem Zincirleri)</h3>
        <span className="muted small">
          {activeCount}/{chains.length} aktif
        </span>
      </div>
      <div className="muted small" style={{ marginBottom: 10 }}>
        Botun işlem yapabileceği zincirleri aç/kapat. Yalnızca açık olanlarda
        fiyat çekilir ve işlem yapılır.
      </div>

      <div className="chain-actions">
        <button className="btn small" disabled={busy} onClick={() => setAll(true)}>
          Hepsini Aç
        </button>
        <button className="btn small" disabled={busy} onClick={() => setAll(false)}>
          Hepsini Kapat
        </button>
      </div>

      <div className="chain-list">
        {chains.map((c) => (
          <label key={c.chain_id} className={`chain-row ${c.active ? 'on' : ''}`}>
            <span className="chain-info">
              <span className="chain-dot" />
              <b>{c.name}</b>
              <span className="muted small"> · {c.native}</span>
            </span>
            <span className="chain-state muted small">{c.active ? 'açık' : 'kapalı'}</span>
            <span className="switch">
              <input
                type="checkbox"
                checked={c.active}
                disabled={busy}
                onChange={(e) => toggle(c.chain_id, e.target.checked)}
              />
              <span className="slider" />
            </span>
          </label>
        ))}
        {!chains.length && (
          <div className="muted small">ağ verisi yok — engine çalışıyor mu?</div>
        )}
      </div>

      {activeCount === 0 && chains.length > 0 && (
        <div className="muted small err" style={{ marginTop: 10 }}>
          ⚠ Hiç ağ açık değil — bot işlem yapmaz (duraklatıldı).
        </div>
      )}
    </div>
  )
}
