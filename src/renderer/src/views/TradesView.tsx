import { CHAIN_NAMES, usd } from '../lib/ui'
import type { Position, TradeOrder } from '@shared/types'
import PositionsTable from '../components/PositionsTable'

export default function TradesView({
  trades,
  logs,
  positions = [],
  onClear
}: {
  trades: TradeOrder[]
  logs: string[]
  positions?: Position[]
  onClear: () => void
}): JSX.Element {
  return (
    <div className="grid">
      <PositionsTable positions={positions} />

      <div className="card span2">
        <div className="card-head">
          <h3>İşlemler</h3>
          <button
            className="btn-ghost danger small"
            onClick={onClear}
            disabled={!trades.length}
            title="İşlem geçmişini kalıcı olarak siler (portföye dokunmaz)"
          >
            🗑 Geçmişi temizle
          </button>
        </div>
        <div className="scroll" style={{ maxHeight: 560 }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Zaman</th>
                <th>İşlem</th>
                <th>Token</th>
                <th>Borsa (nerede)</th>
                <th>Mod</th>
                <th>Adet</th>
                <th>Fiyat</th>
                <th>Ücret</th>
                <th>Nonce</th>
                <th>Durum</th>
                <th>Neden / bilgi</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td className="muted small">{new Date(t.timestamp).toLocaleTimeString()}</td>
                  <td>
                    <span className={`tag ${t.side.toLowerCase()}`}>
                      {t.side === 'BUY' ? 'AL' : 'SAT'}
                    </span>{' '}
                    <span className="muted small">
                      {t.side === 'BUY' ? 'Alım · poz. aç' : 'Satım · poz. kapat'}
                    </span>
                  </td>
                  <td>
                    <b>{t.base}</b>
                    <span className="muted small">/{t.quote}</span>
                  </td>
                  <td className="muted small">
                    <span className={`vbadge ${t.venueType ?? 'dex'}`}>
                      {(t.venueType ?? 'dex') === 'cex' ? 'CEX' : 'DEX'}
                    </span>{' '}
                    {CHAIN_NAMES[t.chainId] ?? t.chainId} · {t.dex}
                  </td>
                  <td>
                    <span className={`badge ${t.mode}`}>{t.mode.toUpperCase()}</span>
                  </td>
                  <td>{t.amount.toFixed(4)}</td>
                  <td>{usd(t.filledPrice || t.price)}</td>
                  <td className="muted">{usd(t.feeUsd ?? 0)}</td>
                  <td className="muted mono">{(t.nonce ?? -1) >= 0 ? t.nonce : '—'}</td>
                  <td className={t.status === 'filled' ? 'pos' : t.status === 'failed' ? 'neg' : ''}>
                    {t.status}
                  </td>
                  <td className="muted small reason" title={t.reason ?? ''}>
                    {t.reason ?? '—'}
                  </td>
                </tr>
              ))}
              {!trades.length && (
                <tr>
                  <td colSpan={11} className="muted">
                    işlem yok
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Log</h3>
        <div className="scroll logbox">
          {logs.map((l, i) => (
            <div key={i} className="logline">
              {l}
            </div>
          ))}
          {!logs.length && <div className="muted">—</div>}
        </div>
      </div>
    </div>
  )
}
