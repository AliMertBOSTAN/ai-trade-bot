// Makro & duyarlılık widget'ları: korku endeksleri, endeks şeridi, risk modu,
// Coinbase primi, ETF akışı, BTC-makro korelasyonu.
import type { JSX } from 'react'
import type {
  IntelCorrelation,
  IntelEtf,
  IntelFearGreed,
  IntelIndices,
  IntelPremium,
  IntelRiskOnOff
} from '@shared/types'
import { BiasBar, Gauge, Row, Spark, Stat, Widget, compact, pct, sign } from './common'

/** İki korku & açgözlülük endeksi yan yana (kripto + ABD borsası). */
export function FearGreedWidget({ data }: { data?: IntelFearGreed }): JSX.Element {
  const cards = [
    { key: 'crypto', title: 'Kripto', d: data?.crypto },
    { key: 'us', title: 'ABD Borsası', d: data?.us }
  ]
  return (
    <Widget
      title="Korku & Açgözlülük"
      hint="Contrarian gösterge: aşırı korku (<25) tarihsel alım, aşırı açgözlülük (>75) risk bölgesidir."
      data={data}
    >
      <div className="ifng">
        {cards.map((c) => (
          <div key={c.key} className="ifng-card">
            <div className="ifng-t">{c.title}</div>
            {c.d?.ok ? (
              <>
                <div className={`ifng-v ${c.d.value >= 62 ? 'pos' : c.d.value <= 38 ? 'neg' : ''}`}>
                  {c.d.value}
                </div>
                <div className="ifng-l">{c.d.label}</div>
                <Gauge value={c.d.value} />
                <div className="ifng-chg">
                  <span className={sign(c.d.change_1d)}>1g {c.d.change_1d >= 0 ? '+' : ''}{c.d.change_1d}</span>
                  <span className={sign(c.d.change_7d)}>7g {c.d.change_7d >= 0 ? '+' : ''}{c.d.change_7d}</span>
                </div>
                <Spark values={c.d.series?.map((s) => s.value)} width={120} />
              </>
            ) : (
              <div className="iempty small">veri yok</div>
            )}
          </div>
        ))}
      </div>
    </Widget>
  )
}

/** Endeks/emtia/faiz şeridi — kriptoyu çevreleyen makro zemin. */
export function IndicesWidget({ data }: { data?: IntelIndices }): JSX.Element {
  const rows = (data?.rows || []).filter((r) => r.ok)
  return (
    <Widget
      title="Makro Zemin"
      hint="Kripto boşlukta hareket etmez: dolar, faiz, volatilite ve hisse momentumu risk iştahını belirler."
      data={data}
      wide
    >
      <div className="tbl-scroll">
        <table className="tbl">
          <thead>
            <tr>
              <th>Endeks</th>
              <th className="num">Değer</th>
              <th className="num">1g</th>
              <th className="num">7g</th>
              <th className="num">30g</th>
              <th>14g</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td>
                  <strong>{r.symbol}</strong> <span className="muted">{r.name}</span>
                </td>
                <td className="num mono">{r.value?.toLocaleString('en-US', { maximumFractionDigits: 2 })}</td>
                <td className={`num ${sign(r.change_pct, r.kind === 'vol')}`}>{pct(r.change_pct)}</td>
                <td className={`num ${sign(r.change_pct_7d, r.kind === 'vol')}`}>{pct(r.change_pct_7d)}</td>
                <td className={`num ${sign(r.change_pct_30d, r.kind === 'vol')}`}>{pct(r.change_pct_30d)}</td>
                <td>
                  <Spark values={r.spark} invert={r.kind === 'vol'} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ifoot muted">
        VIX için düşüş, diğerleri için yükseliş risk-on olarak renklendirilir.
      </p>
    </Widget>
  )
}

/** Risk-On / Risk-Off skoru ve oy veren göstergeler. */
export function RiskModeWidget({ data }: { data?: IntelRiskOnOff }): JSX.Element {
  return (
    <Widget
      title="Piyasa Risk Modu"
      hint="Her gösterge risk-on / risk-off / nötr oyu verir; skor bu oyların ortalamasıdır."
      data={data}
      right={
        data?.ok ? (
          <span className={`pill ${data.score >= 62 ? 'pos' : data.score <= 38 ? 'neg' : ''}`}>{data.mode}</span>
        ) : null
      }
    >
      {data?.ok && (
        <>
          <div className="irisk-top">
            <div className={`irisk-score ${data.score >= 62 ? 'pos' : data.score <= 38 ? 'neg' : ''}`}>
              {data.score}
            </div>
            <div className="irisk-meta">
              <Gauge value={data.score} />
              <span className="muted small">
                {data.positive}/{data.total} gösterge olumlu · {data.negative} olumsuz
              </span>
            </div>
          </div>
          <div className="ilist">
            {data.components.map((c) => (
              <Row
                key={c.name}
                label={c.label}
                sub={c.detail}
                value={c.value == null ? '—' : c.value.toFixed(2)}
                tone={c.positive === true ? 'pos' : c.positive === false ? 'neg' : 'muted'}
              />
            ))}
          </div>
        </>
      )}
    </Widget>
  )
}

/** Coinbase primi — ABD kurumsal talebinin en hızlı okunan göstergesi. */
export function PremiumWidget({ data }: { data?: IntelPremium }): JSX.Element {
  const btc = data?.rows?.find((r) => r.coin === 'BTC')
  const series = data?.series?.BTC?.map((s) => s.premium_pct)
  return (
    <Widget
      title="Coinbase Primi"
      hint="Coinbase (ABD) ile offshore borsa fiyat farkı. Pozitif = ABD tarafında agresif alım."
      data={data}
      right={btc ? <span className="isrc">{btc.venue}</span> : null}
    >
      {data?.ok && (
        <>
          <div className="istats">
            {(data.rows || []).map((r) => (
              <Stat
                key={r.coin}
                label={r.coin}
                value={pct(r.premium_pct, 4)}
                tone={sign(r.premium_pct)}
                sub={`${r.coinbase.toLocaleString('en-US')} / ${r.offshore.toLocaleString('en-US')}`}
              />
            ))}
          </div>
          <Spark values={series} width={280} height={40} />
          <p className="ifoot">{data.note}</p>
        </>
      )}
    </Widget>
  )
}

/** Spot ETF net akışı (CoinGlass varsa gerçek dolar, yoksa vekil). */
export function EtfWidget({ data }: { data?: IntelEtf }): JSX.Element {
  const sides = [
    { key: 'BTC', d: data?.bitcoin },
    { key: 'ETH', d: data?.ethereum }
  ]
  const proxy = data?.source === 'proxy'
  return (
    <Widget
      title="Spot ETF Akışı"
      hint="Kurumsal talebin doğrudan ölçüsü: ETF'lere net giriş fiyat için yapısal destektir."
      data={data}
    >
      <div className="istats">
        {sides.map((s) => {
          const rows = s.d?.rows || []
          const vals = rows.map((r) => (r.flow_usd ?? r.flow_proxy_usd ?? 0) as number)
          const five = s.d?.flow_5d ?? 0
          return (
            <Stat
              key={s.key}
              label={`${s.key} · 5 gün`}
              value={proxy ? (five >= 0 ? 'Net Alım' : 'Net Satış') : compact(five)}
              tone={sign(five)}
              sub={<Spark values={vals} width={110} />}
            />
          )
        })}
      </div>
      <p className="ifoot">{data?.note}</p>
      {data?.disclaimer && <p className="ifoot warn">⚠ {data.disclaimer}</p>}
      {data?.bitcoin?.etfs?.length ? (
        <p className="ifoot muted">Kapsanan ETF'ler: {data.bitcoin.etfs.join(', ')}</p>
      ) : null}
    </Widget>
  )
}

/** BTC'nin makro varlıklarla korelasyonu — çeşitlendirme mi, kaldıraç mı? */
export function CorrelationWidget({ data }: { data?: IntelCorrelation }): JSX.Element {
  return (
    <Widget
      title="Makro Korelasyon (BTC)"
      hint="30/90 günlük getiri korelasyonu. Nasdaq ile yüksek korelasyon = BTC bir risk varlığı gibi işlem görüyor."
      data={data}
    >
      <div className="ilist">
        {(data?.rows || []).map((r) => (
          <div key={r.symbol} className="icorr">
            <span className="icorr-s">{r.symbol}</span>
            <BiasBar score={r.corr_30d ?? 0} />
            <span className={`icorr-v ${sign(r.corr_30d)}`}>
              {r.corr_30d == null ? '—' : r.corr_30d.toFixed(2)}
            </span>
            <span className="icorr-v muted">{r.corr_90d == null ? '—' : r.corr_90d.toFixed(2)}</span>
          </div>
        ))}
      </div>
      <p className="ifoot muted">Sol sütun 30 günlük, sağ sütun 90 günlük korelasyon.</p>
    </Widget>
  )
}
