// "Piyasa İstihbaratı" sekmesi — makro, on-chain akış ve Hyperliquid/whale
// panellerinin tek ekranı. Veri /intel/overview'dan tek istekte gelir; backend
// zaten TTL cache'lidir, bu yüzden yenileme ucuzdur.
//
// Tasarım notu: `active` false iken hiç istek atılmaz (App.tsx sekmeyi DOM'da
// tutuyor ama görünmez yapıyor). Böylece arka planda boşuna trafik olmaz.
import { useCallback, useEffect, useState, type JSX } from 'react'
import { api } from '../api'
import type { IntelOverview } from '@shared/types'
import { timeAgo } from '../components/intel/common'
import {
  CorrelationWidget,
  EtfWidget,
  FearGreedWidget,
  IndicesWidget,
  PremiumWidget,
  RiskModeWidget
} from '../components/intel/MacroWidgets'
import {
  ChainFeesWidget,
  ChainRotationWidget,
  HacksWidget,
  SectorRotationWidget,
  StablecoinWidget,
  UnlocksWidget,
  UtxoWidget,
  YieldsWidget
} from '../components/intel/OnchainWidgets'
import {
  BiasWidget,
  HlWalletsWidget,
  HyperliquidWidget,
  ReservesWidget,
  SmartMoneyWidget
} from '../components/intel/FlowWidgets'

type Group = 'all' | 'macro' | 'onchain' | 'hl'

const GROUPS: { id: Group; label: string }[] = [
  { id: 'all', label: 'Tümü' },
  { id: 'macro', label: 'Makro & Duyarlılık' },
  { id: 'onchain', label: 'On-chain & Akışlar' },
  { id: 'hl', label: 'Hyperliquid & Whale' }
]

/** UI'da 5 dakikada bir tazele — backend cache'i zaten upstream'i korur. */
const POLL_MS = 300_000

export default function IntelView({ active }: { active: boolean }): JSX.Element {
  const [data, setData] = useState<IntelOverview | null>(null)
  const [group, setGroup] = useState<Group>('all')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [loadedOnce, setLoadedOnce] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    try {
      setErr('')
      setData(await api.intelOverview())
      setLoadedOnce(true)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'engine yanıt vermedi')
    }
  }, [])

  const forceRefresh = useCallback(async (): Promise<void> => {
    setBusy(true)
    try {
      await api.refreshIntel()
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'tazeleme başarısız')
    } finally {
      setBusy(false)
    }
  }, [load])

  useEffect(() => {
    if (!active) return
    if (!loadedOnce) load()
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [active, loadedOnce, load])

  const p = data?.panels
  const src = data?.sources
  const show = (g: Group): boolean => group === 'all' || group === g

  const offProviders = Object.entries(src?.providers || {}).filter(
    ([, v]) => v.key_required && !v.enabled
  )
  const oldest = Object.values(src?.panels || {})
    .map((x) => x.age_s)
    .filter((x): x is number => x != null)
  const freshness = oldest.length ? Math.max(...oldest) : null

  return (
    <>
      <section className="card span2 iheader">
        <div className="card-head">
          <h3>Piyasa İstihbaratı</h3>
          <div className="iwidget-right">
            {data?.refresher && (
              <span className="muted small">
                {data.refresher.running
                  ? `otomatik tazeleme ${Math.round(data.refresher.interval_s / 60)} dk`
                  : 'otomatik tazeleme kapalı'}
                {freshness != null && ` · en eski veri ${timeAgo(freshness)}`}
              </span>
            )}
            <button className="btn small" onClick={forceRefresh} disabled={busy}>
              {busy ? 'tazeleniyor…' : '⟳ Tazele'}
            </button>
          </div>
        </div>

        <div className="seg igroups">
          {GROUPS.map((g) => (
            <button
              key={g.id}
              className={group === g.id ? 'mf active' : 'mf'}
              onClick={() => setGroup(g.id)}
            >
              {g.label}
            </button>
          ))}
        </div>

        {err && <p className="ifoot neg">⚠ {err}</p>}
        {offProviders.length > 0 && (
          <p className="ifoot muted">
            Anahtarsız çalışan kaynaklarla dolduruldu. Şu sağlayıcılar kapalı:{' '}
            {offProviders.map(([k, v]) => `${k} (${v.env})`).join(', ')} — .env'e ekleyince
            ilgili paneller gerçek veriye geçer.
          </p>
        )}
      </section>

      {!data && !err && <section className="card">Yükleniyor…</section>}

      {p && (
        <>
          <BiasWidget data={data?.bias} />

          {show('macro') && (
            <>
              <RiskModeWidget data={p.risk_on_off} />
              <FearGreedWidget data={p.fear_greed} />
              <IndicesWidget data={p.indices} />
              <PremiumWidget data={p.premium} />
              <EtfWidget data={p.etf} />
              <CorrelationWidget data={p.correlation} />
            </>
          )}

          {show('onchain') && (
            <>
              <StablecoinWidget data={p.stablecoins} chains={p.stablecoin_chains} />
              <SectorRotationWidget data={p.sectors} />
              <ChainFeesWidget data={p.chain_fees} dex={p.dex_volumes} />
              <UtxoWidget data={p.utxo} />
              <ChainRotationWidget data={p.chains} dominance={p.dominance} />
              <UnlocksWidget data={p.unlocks} />
              <YieldsWidget data={p.yields} />
              <HacksWidget data={p.hacks} />
            </>
          )}

          {show('hl') && (
            <>
              <HyperliquidWidget data={p.hyperliquid} />
              <HlWalletsWidget data={p.hyperliquid} />
              <SmartMoneyWidget data={p.smart_money} />
              <ReservesWidget data={p.reserves} />
            </>
          )}
        </>
      )}
    </>
  )
}
