import { CHAIN_NAMES, usd } from '../lib/ui'
import type { Position } from '@shared/types'

/**
 * Açık pozisyonların detaylı tablosu: yön (long/short), platform/zincir, açılış
 * zamanı, adet, ort. giriş, anlık fiyat, maliyet, değer ve PnL ($ + %).
 * Hem "Genel" hem "İşlemler" sekmesinde paylaşılır.
 */
export default function PositionsTable({
  positions,
  title = 'Açık Pozisyonlar',
  onReset
}: {
  positions: Position[]
  title?: string
  onReset?: () => void
}): JSX.Element {
  return (
    <div className="card span2">
      <div className="card-head">
        <h3>{title}</h3>
        <div className="ph-actions">
          <span className="muted small">{positions.length} pozisyon</span>
          {onReset && (
            <button
              className="btn-ghost small"
              onClick={onReset}
              title="Paper portföyü sıfırla — tutarı ve başlangıç türünü sen seç"
            >
              ↺ Paper'ı sıfırla…
            </button>
          )}
        </div>
      </div>
      <div className="tbl-scroll">
        <table className="tbl">
          <thead>
            <tr>
              <th>Token</th>
              <th>Yön</th>
              <th>Platform / Zincir</th>
              <th>Açılış</th>
              <th>Adet</th>
              <th>Ort. Giriş</th>
              <th>Anlık Fiyat</th>
              <th>Maliyet</th>
              <th>Değer</th>
              <th>PnL ($)</th>
              <th>PnL (%)</th>
            </tr>
          </thead>
          <tbody>
            {positions.length ? (
              positions.map((p) => {
                const side = p.side ?? (p.amount >= 0 ? 'LONG' : 'SHORT')
                const value = p.valueUsd ?? p.amount * p.lastPrice
                const cost = p.costUsd ?? Math.abs(p.amount) * p.avgEntry
                const pnlPct = p.pnlPct ?? 0
                const opened = p.openedTs ? new Date(p.openedTs).toLocaleString() : '—'
                return (
                  <tr key={p.key}>
                    <td className="mono">
                      {p.base}/{p.quote}
                    </td>
                    <td>
                      <span className={`side-badge ${side === 'LONG' ? 'long' : 'short'}`}>
                        {side}
                      </span>
                    </td>
                    <td className="muted small">
                      {p.dex ? `${p.dex} · ` : ''}
                      {CHAIN_NAMES[p.chainId] ?? p.chainId}
                    </td>
                    <td className="muted small">{opened}</td>
                    <td className="mono">{Math.abs(p.amount).toFixed(4)}</td>
                    <td>{usd(p.avgEntry)}</td>
                    <td>{usd(p.lastPrice)}</td>
                    <td className="muted">{usd(cost)}</td>
                    <td>{usd(Math.abs(value))}</td>
                    <td className={p.unrealizedPnlUsd >= 0 ? 'pos' : 'neg'}>
                      {usd(p.unrealizedPnlUsd)}
                    </td>
                    <td className={pnlPct >= 0 ? 'pos' : 'neg'}>
                      {pnlPct >= 0 ? '+' : ''}
                      {pnlPct.toFixed(2)}%
                    </td>
                  </tr>
                )
              })
            ) : (
              <tr>
                <td colSpan={11} className="muted">
                  açık pozisyon yok
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
