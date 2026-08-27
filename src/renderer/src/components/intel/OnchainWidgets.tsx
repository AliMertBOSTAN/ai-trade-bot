// On-chain & akış widget'ları: stablecoin likiditesi, zincir ücretleri,
// sektör/zincir rotasyonu, dominans, DeFi getirileri, unlock takvimi,
// hack radarı ve BTC gerçekleşmiş fiyat (UTXO) paneli.
import type { JSX } from 'react'
import type {
  IntelChainFees,
  IntelChains,
  IntelDexVolumes,
  IntelDominance,
  IntelHacks,
  IntelSectors,
  IntelStablecoinChains,
  IntelStablecoins,
  IntelUnlocks,
  IntelUtxo,
  IntelYields
} from '@shared/types'
import { Row, Spark, Stat, Widget, compact, pct, sign } from './common'

const day = (t: number): string =>
  new Date(t).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })

/** Stablecoin arzı = piyasaya giren taze likidite. */
export function StablecoinWidget({
  data,
  chains
}: {
  data?: IntelStablecoins
  chains?: IntelStablecoinChains
}): JSX.Element {
  return (
    <Widget
      title="Stablecoin Likiditesi"
      hint="Toplam stablecoin arzı büyürken piyasaya taze alım gücü giriyor; daralma likidite çekilmesidir."
      data={data}
      wide
    >
      {data?.ok && (
        <>
          <div className="istats">
            <Stat label="Toplam Arz" value={compact(data.total_supply)} />
            <Stat
              label="30 günlük değişim"
              value={compact(data.change_30d)}
              tone={sign(data.change_30d)}
              sub={pct(data.change_30d_pct)}
            />
            <Stat label="7 günlük değişim" value={compact(data.change_7d)} tone={sign(data.change_7d)} />
          </div>
          <Spark values={data.series?.map((s) => s.supply)} width={320} height={44} />
          <div className="igrid2">
            <div>
              <h4 className="ih4">Varlıklar</h4>
              {data.assets.map((a) => (
                <Row
                  key={a.symbol}
                  label={a.symbol}
                  sub={compact(a.supply)}
                  value={compact(a.change_30d)}
                  tone={sign(a.change_30d)}
                />
              ))}
            </div>
            <div>
              <h4 className="ih4">Zincir dağılımı (7g)</h4>
              {(chains?.rows || []).slice(0, 8).map((c) => (
                <Row
                  key={c.chain}
                  label={c.chain}
                  sub={compact(c.supply)}
                  value={pct(c.change_7d_pct)}
                  tone={sign(c.change_7d_pct)}
                />
              ))}
            </div>
          </div>
          <p className="ifoot">{data.note}</p>
        </>
      )}
    </Widget>
  )
}

/** Zincir ücret/gelir — gerçek kullanım nerede yoğunlaşıyor. */
export function ChainFeesWidget({
  data,
  dex
}: {
  data?: IntelChainFees
  dex?: IntelDexVolumes
}): JSX.Element {
  return (
    <Widget
      title="Zincir Komisyonları & DEX Hacmi"
      hint="Ücret geliri = gerçek kullanım. Ücretlerin arttığı zincire sermaye ve kullanıcı akıyor demektir."
      data={data}
      wide
      right={data?.approx ? <span className="isrc warn">yaklaşık</span> : null}
    >
      {data?.ok && (
        <>
          <div className="istats">
            <Stat label="24s toplam ücret" value={compact(data.total_24h)} />
            <Stat label="30g toplam" value={compact(data.total_30d)} />
            <Stat label="24s lider" value={data.leader || '—'} sub={compact(data.leader_fees)} />
          </div>
          <div className="tbl-scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Zincir</th>
                  <th className="num">Ücret 24s</th>
                  <th className="num">30g ort. farkı</th>
                  <th className="num">DEX hacmi 24s</th>
                  <th className="num">TVL</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.chain}>
                    <td>{r.chain}</td>
                    <td className="num mono">{compact(r.fees_24h)}</td>
                    <td className={`num ${sign(r.fees_change_pct)}`}>{pct(r.fees_change_pct, 1)}</td>
                    <td className="num mono">{compact(r.dex_volume_24h)}</td>
                    <td className="num mono muted">{compact(r.tvl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {dex?.ok && (
            <>
              <h4 className="ih4">DEX hacim liderleri (24s)</h4>
              <div className="ichips">
                {dex.rows.slice(0, 8).map((d) => (
                  <span key={d.name} className="ichip">
                    {d.name} <b>{compact(d.volume_24h)}</b>
                  </span>
                ))}
              </div>
            </>
          )}
          {data.approx && (
            <p className="ifoot muted">
              Bazı protokoller zincir kırılımı vermiyor; o kalemler zincirlerine eşit bölüştürüldü.
            </p>
          )}
        </>
      )}
    </Widget>
  )
}

/** Sektör rotasyonu — para hangi anlatıdan hangisine geçiyor. */
export function SectorRotationWidget({ data }: { data?: IntelSectors }): JSX.Element {
  const max = Math.max(1, ...(data?.rows || []).map((r) => Math.abs(r.net_flow_usd)))
  return (
    <Widget
      title="Sektör Rotasyonu"
      hint="24 saatte sektör piyasa değerindeki net değişim. Girişin arttığı sektör o anki anlatıyı taşıyor."
      data={data}
      wide
    >
      {data?.ok && (
        <>
          <div className="ilist">
            {data.rows.map((r) => (
              <div key={r.id} className="iflow">
                <span className="iflow-n">{r.sector}</span>
                <span className="iflow-bar">
                  <span
                    className={`iflow-fill ${r.net_flow_usd >= 0 ? 'pos' : 'neg'}`}
                    style={{ width: `${(Math.abs(r.net_flow_usd) / max) * 100}%` }}
                  />
                </span>
                <span className={`iflow-v ${sign(r.net_flow_usd)}`}>{compact(r.net_flow_usd)}</span>
                <span className={`iflow-p ${sign(r.change_24h_pct)}`}>{pct(r.change_24h_pct)}</span>
              </div>
            ))}
          </div>
          {data.edges?.length > 0 && (
            <>
              <h4 className="ih4">Rotasyon kenarları</h4>
              <div className="ichips">
                {data.edges.map((e, i) => (
                  <span key={i} className="ichip">
                    {e.from} <span className="muted">→</span> {e.to} <b>{compact(e.flow_usd)}</b>
                  </span>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </Widget>
  )
}

/** Zincir TVL payları + BTC/ETH/stable dominansı. */
export function ChainRotationWidget({
  data,
  dominance
}: {
  data?: IntelChains
  dominance?: IntelDominance
}): JSX.Element {
  return (
    <Widget title="Zincir & Dominans" hint="TVL payı ve BTC/ETH dominansı — sermaye hangi katmanda duruyor." data={data}>
      {dominance?.ok && (
        <div className="istats">
          <Stat label="BTC dominans" value={`${dominance.btc_dominance ?? '—'}%`} />
          <Stat label="ETH dominans" value={`${dominance.eth_dominance ?? '—'}%`} />
          <Stat
            label="Toplam piyasa"
            value={compact(dominance.total_market_cap_usd)}
            tone={sign(dominance.mcap_change_24h)}
            sub={pct(dominance.mcap_change_24h)}
          />
        </div>
      )}
      <div className="ilist">
        {(data?.rows || []).slice(0, 10).map((r) => (
          <Row key={r.chain} label={r.chain} sub={`${r.share_pct ?? 0}% pay`} value={compact(r.tvl)} />
        ))}
      </div>
    </Widget>
  )
}

/** DeFi getiri havuzları — nakit park etme fırsatları. */
export function YieldsWidget({ data }: { data?: IntelYields }): JSX.Element {
  return (
    <Widget
      title="DeFi Getirileri"
      hint="TVL filtreli havuzlar. Stablecoin sekmesi, boşta duran nakdin risksiz-benzeri alternatifidir."
      data={data}
    >
      {data?.ok && (
        <>
          <h4 className="ih4">Stablecoin havuzları</h4>
          <div className="tbl-scroll">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Havuz</th>
                  <th>Zincir</th>
                  <th className="num">APY</th>
                  <th className="num">TVL</th>
                </tr>
              </thead>
              <tbody>
                {(data.stable_rows || []).slice(0, 8).map((p, i) => (
                  <tr key={`${p.project}-${p.symbol}-${i}`}>
                    <td>
                      {p.symbol} <span className="muted">{p.project}</span>
                    </td>
                    <td className="muted">{p.chain}</td>
                    <td className="num pos mono">{p.apy.toFixed(2)}%</td>
                    <td className="num mono muted">{compact(p.tvl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="ifoot muted">{data.count} havuz tarandı (min. $5M TVL).</p>
        </>
      )}
    </Widget>
  )
}

/** Token unlock takvimi — programlı arz şokları. */
export function UnlocksWidget({ data }: { data?: IntelUnlocks }): JSX.Element {
  return (
    <Widget
      title="Token Unlock Takvimi"
      hint="Piyasa değerinin %1'ini aşan unlock'lar genelde öncesinde satış baskısı yaratır."
      data={data}
      right={data?.ok ? <span className="pill">{data.window_days} gün</span> : null}
    >
      {data?.ok && (
        <>
          {data.significant?.length > 0 && (
            <>
              <h4 className="ih4">Kritik olanlar</h4>
              {data.significant.map((u, i) => (
                <Row
                  key={`${u.symbol}-${u.t}-${i}`}
                  label={<strong>{u.symbol}</strong>}
                  sub={`${day(u.t)} · ${u.category || u.unlock_type || ''}`}
                  value={`${compact(u.value_usd)} (${u.pct_of_mcap}%)`}
                  tone="neg"
                />
              ))}
            </>
          )}
          <h4 className="ih4">Yaklaşanlar</h4>
          <div className="ilist iscroll">
            {data.rows.slice(0, 15).map((u, i) => (
              <Row
                key={`${u.symbol}-${u.t}-r${i}`}
                label={u.symbol}
                sub={day(u.t)}
                value={compact(u.value_usd)}
                tone={(u.pct_of_mcap ?? 0) >= 1 ? 'neg' : 'muted'}
              />
            ))}
          </div>
          <p className="ifoot muted">{data.scanned} protokol tarandı.</p>
        </>
      )}
    </Widget>
  )
}

/** BTC gerçekleşmiş fiyat / MVRV — piyasanın maliyet tabanı. */
export function UtxoWidget({ data }: { data?: IntelUtxo }): JSX.Element {
  return (
    <Widget
      title="BTC Maliyet Tabanı (MVRV)"
      hint="Gerçekleşmiş fiyat = tüm BTC'nin ortalama alım maliyeti. MVRV bu tabana göre kaç kat primli olduğumuzu söyler."
      data={data}
    >
      {data?.ok && (
        <>
          <div className="istats">
            <Stat label="Spot" value={`$${data.price.toLocaleString('en-US')}`} />
            <Stat label="Gerçekleşmiş fiyat" value={`$${data.realized_price.toLocaleString('en-US')}`} />
            <Stat
              label="MVRV"
              value={data.mvrv.toFixed(2)}
              tone={data.mvrv >= 2.4 ? 'neg' : data.mvrv <= 1.2 ? 'pos' : ''}
              sub={pct(data.premium_pct, 1) + ' prim'}
            />
          </div>
          {data.sth_realized && (
            <Row
              label="Kısa vadeli sahip maliyeti"
              value={`$${data.sth_realized.toLocaleString('en-US')}`}
              tone={data.price >= data.sth_realized ? 'pos' : 'neg'}
              sub={data.sth_note || undefined}
            />
          )}
          <Spark values={data.series?.map((s) => s.mvrv)} width={300} height={40} />
          <p className="ifoot">{data.zone}</p>
        </>
      )}
    </Widget>
  )
}

/** Son hack/exploit olayları — sektörel risk radarı. */
export function HacksWidget({ data }: { data?: IntelHacks }): JSX.Element {
  return (
    <Widget title="Son Exploit'ler" hint="Büyük hack'ler ilgili zincirde/sektörde kısa vadeli güven kaybı yaratır." data={data}>
      <div className="ilist iscroll">
        {(data?.rows || []).map((h, i) => (
          <Row
            key={`${h.name}-${i}`}
            label={h.name}
            sub={`${day(h.t)} · ${h.chain || '—'} · ${h.technique || ''}`}
            value={compact(h.amount_usd)}
            tone="neg"
          />
        ))}
      </div>
    </Widget>
  )
}
