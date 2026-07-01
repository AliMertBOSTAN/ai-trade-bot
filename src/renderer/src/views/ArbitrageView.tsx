import { CHAIN_NAMES, usd } from '../lib/ui'
import type { ArbitrageOpportunity } from '@shared/types'

export default function ArbitrageView({ arbs }: { arbs: ArbitrageOpportunity[] }): JSX.Element {
  if (!arbs.length) return <div className="muted card">fırsat yok (gas + slippage düşülmüş net)</div>
  return (
    <div className="arblist">
      {arbs.map((o) => (
        <div className="arb card" key={o.id}>
          <div className="arb-top">
            <b>{o.base}</b>
            <span className="pos">+{usd(o.estNetProfitUsd)}</span>
            <span className="muted small">net · {o.spreadPct.toFixed(2)}% spread</span>
          </div>
          <div className="muted small">
            Al {CHAIN_NAMES[o.buyChain] ?? o.buyChain} {o.buyDex} @ {usd(o.buyPrice)} → Sat{' '}
            {CHAIN_NAMES[o.sellChain] ?? o.sellChain} {o.sellDex} @ {usd(o.sellPrice)}
          </div>
          <div className="muted small">İşlem büyüklüğü ≈ {usd(o.notionalUsd)}</div>
        </div>
      ))}
    </div>
  )
}
