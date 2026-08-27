// Hyperliquid & whale widget'ları: perp duyarlılığı, kazanan/izlenen cüzdan
// konumlanması, smart-money radarı, borsa rezervleri ve birleşik yapı skoru.
import type { JSX } from 'react'
import type {
  HlWalletAggregate,
  IntelBias,
  IntelHyperliquid,
  IntelReserves,
  IntelSmartMoney
} from '@shared/types'
import { BiasBar, Row, Stat, Widget, compact, pct, sign } from './common'

/** Hyperliquid perp evreninin genel duyarlılığı. */
export function HyperliquidWidget({ data }: { data?: IntelHyperliquid }): JSX.Element {
  const s = data?.sentiment
  return (
    <Widget
      title="Hyperliquid Duyarlılığı"
      hint="OI ağırlıklı funding + yükselen coin oranı. Pozitif funding = kalabalık long (contrarian risk)."
      data={s}
      wide
      right={s?.ok ? <span className={`pill ${sign(s.score)}`}>{s.label}</span> : null}
    >
      {s?.ok && (
        <>
          <div className="istats">
            <Stat label="Toplam OI" value={compact(s.total_oi_usd)} />
            <Stat label="24s hacim" value={compact(s.total_volume_24h)} />
            <Stat
              label="Ağırlıklı funding"
              value={`${(s.weighted_funding_pct ?? 0).toFixed(4)}%`}
              tone={sign(s.weighted_funding_pct, true)}
              sub="saatlik"
            />
            <Stat
              label="Genişlik"
              value={`${s.breadth_pct}%`}
              tone={(s.breadth_pct ?? 50) >= 50 ? 'pos' : 'neg'}
              sub="yükselen coin oranı"
            />
          </div>
          <div className="igrid2">
            <div>
              <h4 className="ih4">En yüksek açık pozisyon</h4>
              {(s.top_oi || []).slice(0, 6).map((r) => (
                <Row
                  key={r.symbol}
                  label={r.symbol}
                  sub={`funding ${r.funding_pct.toFixed(4)}%`}
                  value={compact(r.open_interest_usd)}
                  tone={sign(r.change_pct_24h)}
                />
              ))}
            </div>
            <div>
              <h4 className="ih4">En çok hareket edenler</h4>
              {(s.movers || []).slice(0, 6).map((r) => (
                <Row
                  key={r.symbol}
                  label={r.symbol}
                  sub={compact(r.volume_usd) + ' hacim'}
                  value={pct(r.change_pct_24h)}
                  tone={sign(r.change_pct_24h)}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </Widget>
  )
}

/** Cüzdan kümesinin (kazananlar / izleme listesi) net LONG-SHORT dağılımı. */
function WalletAggregate({ agg }: { agg?: HlWalletAggregate }): JSX.Element | null {
  if (!agg?.ok) return null
  return (
    <>
      <div className="istats">
        <Stat label="Net yön" value={agg.bias || '—'} tone={sign(agg.score)} />
        <Stat label="Net pozisyon" value={compact(agg.net_usd)} tone={sign(agg.net_usd)} />
        <Stat label="Taranan cüzdan" value={String(agg.wallets_scanned ?? 0)} />
      </div>
      <div className="ilist">
        {agg.rows.slice(0, 8).map((r) => (
          <div key={r.symbol} className="ilong">
            <span className="ilong-s">{r.symbol}</span>
            <span className="ilong-bar" title={`%${r.long_pct} LONG`}>
              <span className="ilong-l" style={{ width: `${r.long_pct}%` }} />
              <span className="ilong-r" style={{ width: `${100 - r.long_pct}%` }} />
            </span>
            <span className={`ilong-v ${sign(r.net_usd)}`}>{compact(r.net_usd)}</span>
            <span className="ilong-w muted">{r.wallets} cüzdan</span>
          </div>
        ))}
      </div>
    </>
  )
}

/** Kazanan cüzdanlar (opsiyonel) + kendi izleme listen. */
export function HlWalletsWidget({ data }: { data?: IntelHyperliquid }): JSX.Element {
  const winners = data?.winners
  const watch = data?.watchlist
  const showWinners = winners?.ok
  const showWatch = watch?.ok
  const shown = showWinners ? winners : showWatch ? watch : winners
  return (
    <Widget
      title="Hyperliquid Cüzdan Konumlanması"
      hint="Büyük cüzdanların net LONG/SHORT dağılımı. Kendi listeni .env HL_WATCH_WALLETS ile tanımlarsın."
      data={showWinners || showWatch ? { ok: true } : shown}
      right={shown?.label ? <span className="pill">{shown.label}</span> : null}
    >
      {showWinners && <WalletAggregate agg={winners} />}
      {showWatch && (
        <>
          {showWinners && <h4 className="ih4">İzleme listen</h4>}
          <WalletAggregate agg={watch} />
        </>
      )}
      {!showWinners && !showWatch && (
        <p className="ifoot muted">
          Kendi takip ettiğin cüzdanları görmek için <code>.env</code> dosyasına
          <code> HL_WATCH_WALLETS=0x...,0x...</code> ekle. Genel PnL sıralaması ~35 MB
          indirdiği için varsayılan kapalıdır (<code>HL_LEADERBOARD=1</code> ile açılır).
        </p>
      )}
    </Widget>
  )
}

/** Smart-money radarı: birikim mi dağıtım mı? */
export function SmartMoneyWidget({ data }: { data?: IntelSmartMoney }): JSX.Element {
  return (
    <Widget
      title="Smart Money Radarı"
      hint="Taker alım/satım dengesizliği + büyük işlem baskısı. Nansen anahtarı varsa zincir-üstü gerçek akış kullanılır."
      data={data}
      right={data?.ok ? <span className={`pill ${sign(data.score)}`}>{data.score.toFixed(2)}</span> : null}
    >
      {data?.ok && (
        <>
          <div className="ilist">
            {data.rows.map((r) => (
              <div key={r.symbol} className="icorr">
                <span className="icorr-s">{r.symbol}</span>
                <BiasBar score={r.score} />
                <span className={`icorr-v ${sign(r.score)}`}>{r.label}</span>
              </div>
            ))}
          </div>
          {data.note && <p className="ifoot muted">{data.note}</p>}
        </>
      )}
    </Widget>
  )
}

/** Borsa rezervleri — düşen rezerv birikim, artan rezerv satış baskısıdır. */
export function ReservesWidget({ data }: { data?: IntelReserves }): JSX.Element {
  return (
    <Widget
      title="Borsa Rezervleri"
      hint="Borsalardaki coin bakiyesi. Rezerv düşerse coin soğuk cüzdana çekiliyor (birikim)."
      data={data}
    >
      {data?.ok && (
        <>
          <div className="istats">
            <Stat label={`${data.symbol} toplam`} value={compact(data.total, '')} />
            <Stat label="7g değişim" value={compact(data.change_7d, '')} tone={sign(data.change_7d, true)} />
          </div>
          <div className="ilist">
            {data.rows.slice(0, 8).map((r) => (
              <Row
                key={r.exchange}
                label={r.exchange}
                value={compact(r.balance, '')}
                tone={sign(r.change_7d, true)}
                sub={`7g ${compact(r.change_7d, '')}`}
              />
            ))}
          </div>
          <p className="ifoot">{data.note}</p>
        </>
      )}
    </Widget>
  )
}

/** Sinyal motoruna giren birleşik yapı skoru — "bot neden böyle düşünüyor". */
export function BiasWidget({ data }: { data?: IntelBias }): JSX.Element {
  return (
    <Widget
      title="Piyasa Yapısı Skoru"
      hint="Bu skor sinyal motoruna girer: karara ters ve güçlüyse güven tavanlanır, destekliyorsa küçük bonus verilir."
      data={data ? { ok: data.ok, reason: data.ok ? undefined : 'panel verisi henüz toplanmadı' } : undefined}
      wide
      right={data?.ok ? <span className={`pill ${sign(data.score)}`}>{data.label}</span> : null}
    >
      {data?.ok && (
        <>
          <div className="ibias-hero">
            <span className={`ibias-num ${sign(data.score)}`}>
              {data.score >= 0 ? '+' : ''}
              {data.score.toFixed(2)}
            </span>
            <BiasBar score={data.score} />
            <span className="muted small">{data.available} bileşen</span>
          </div>
          <div className="ilist">
            {data.components.map((c) => (
              <div key={c.name} className="icorr">
                <span className="icorr-s">{c.name}</span>
                <BiasBar score={c.score} />
                <span className={`icorr-v ${sign(c.score)}`}>
                  {c.score >= 0 ? '+' : ''}
                  {c.score.toFixed(2)}
                </span>
                <span className="icorr-d muted">{c.detail}</span>
              </div>
            ))}
          </div>
          <p className="ifoot muted">
            Ağırlıklar <code>engine/marketdata/intel/bias.py</code> içindeki WEIGHTS ile
            ayarlanır. Kapatmak için <code>INTEL_SIGNAL=0</code>.
          </p>
        </>
      )}
    </Widget>
  )
}
