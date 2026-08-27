import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { CalendarEvent, CalendarResponse, ResearchNote, ResearchResponse } from '@shared/types'

/** Olaya kalan/geçen süreyi insan diline çevirir. */
function inWords(hours: number): string {
  const abs = Math.abs(hours)
  const txt = abs < 1 ? `${Math.round(abs * 60)} dk` : abs < 48 ? `${abs.toFixed(1)} sa` : `${(abs / 24).toFixed(1)} gün`
  return hours >= 0 ? `${txt} sonra` : `${txt} önce`
}

/** Önem -> rozet metni + sınıf. */
function impactBadge(importance: number): { label: string; cls: string } {
  if (importance >= 0.8) return { label: 'YÜKSEK', cls: 'bad' }
  if (importance >= 0.5) return { label: 'ORTA', cls: 'warn' }
  return { label: 'DÜŞÜK', cls: 'muted' }
}

function EventRow({ ev }: { ev: CalendarEvent }): JSX.Element {
  const b = impactBadge(ev.importance)
  const when = new Date(ev.ts).toLocaleString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
  return (
    <div className="news-item">
      <div className="news-top">
        <span className={`news-src ${b.cls}`}>{b.label}</span>
        <span className="muted small">
          {when} · {inWords(ev.inHours)}
        </span>
      </div>
      <div className="news-title">
        {ev.title}
        {ev.symbols.length > 0 && <span className="muted small"> · {ev.symbols.join(', ')}</span>}
      </div>
      <div className="muted small">
        {ev.category === 'macro' ? 'makro' : ev.category === 'crypto' ? 'kripto' : 'diğer'} ·
        kaynak: {ev.source}
      </div>
    </div>
  )
}

function NoteCard({ n }: { n: ResearchNote }): JSX.Element {
  return (
    <div className="card">
      <div className="news-top">
        <span className={`news-src ${n.phase === 'pre' ? 'warn' : 'ok'}`}>
          {n.phase === 'pre' ? 'HAZIRLIK' : 'SONUÇ'}
        </span>
        <span className="muted small">
          {n.title} · {inWords(n.hoursToEvent)} · {n.author === 'llm' ? 'AI' : 'sayısal'}
        </span>
      </div>
      <p>{n.summary}</p>
      {n.expectation && (
        <div className="muted small">
          <b>Beklenti:</b> {n.expectation}
        </div>
      )}
      {n.surprise && (
        <div className="muted small">
          <b>Sürpriz:</b> {n.surprise}
        </div>
      )}
      {n.scenarios.length > 0 && (
        <ul className="small">
          {n.scenarios.map((s, i) => (
            <li key={i}>
              <b>{s.kosul}</b> → {s.etki}
            </li>
          ))}
        </ul>
      )}
      {n.watch.length > 0 && (
        <div className="muted small">
          <b>İzlenecek:</b> {n.watch.join(' · ')}
        </div>
      )}
      {n.risk && (
        <div className="muted small">
          <b>Risk:</b> {n.risk}
        </div>
      )}
      <div className="muted small">
        Eğilim (bias): {n.bias >= 0 ? '+' : ''}
        {n.bias.toFixed(2)}
      </div>
      {n.headlines.length > 0 && (
        <details>
          <summary className="muted small">Kaynak başlıklar ({n.headlines.length})</summary>
          <ul className="small">
            {n.headlines.map((h, i) => (
              <li key={i}>
                <a href={h.link || undefined} target="_blank" rel="noreferrer">
                  [{h.source}] {h.title}
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

/**
 * Takvim & Araştırma paneli.
 * Bot bu verileri kullanıcı istemeden, arka planda kendi toplar; panel yalnızca
 * sonucu gösterir. "Şimdi araştır" butonu bir turu elle tetikler.
 */
export default function CalendarPanel(): JSX.Element {
  const [cal, setCal] = useState<CalendarResponse | null>(null)
  const [res, setRes] = useState<ResearchResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([api.calendar(336, 0.4), api.research(20)])
      setCal(c)
      setRes(r)
      setErr('')
    } catch {
      setErr('takvim/araştırma verisine ulaşılamadı (engine çalışıyor mu?)')
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 120000) // 2 dk
    return () => clearInterval(t)
  }, [load])

  const runNow = async (): Promise<void> => {
    setBusy(true)
    try {
      await api.researchRun()
      await load()
    } catch {
      setErr('araştırma turu başlatılamadı')
    } finally {
      setBusy(false)
    }
  }

  if (err && !cal) return <div className="muted">{err}</div>
  if (!cal || !res) return <div className="muted">takvim yükleniyor…</div>

  const active = cal.status.activeWindow
  const next = cal.status.nextHighImpact

  return (
    <>
      <div className="card">
        <div className="card-head">
          <h3>Veri takvimi</h3>
          <button className="btn" onClick={runNow} disabled={busy}>
            {busy ? 'araştırılıyor…' : 'Şimdi araştır'}
          </button>
        </div>
        {active.length > 0 ? (
          <div className="alert warn">
            ⚠️ Veri penceresi açık: {active.map((e) => e.title).join(', ')} — yeni alım
            durduruldu / boyut küçültüldü.
          </div>
        ) : next ? (
          <div className="muted">
            Sıradaki yüksek etkili veri: <b>{next.title}</b> · {inWords(next.inHours)} (
            {new Date(next.ts).toLocaleString('tr-TR')})
          </div>
        ) : (
          <div className="muted">Yaklaşan yüksek etkili veri yok.</div>
        )}
        <div className="muted small">
          {cal.status.eventCount} olay · fren {cal.status.guardEnabled ? 'açık' : 'kapalı'} (
          {cal.status.preWindowMin}dk önce / {cal.status.postWindowMin}dk sonra) · araştırmacı{' '}
          {res.status.running ? 'çalışıyor' : 'durdu'} · {res.status.cycles} tur
          {cal.status.lastError ? ` · akış hatası: ${cal.status.lastError}` : ''}
        </div>
      </div>

      <div className="card">
        <h3>Yaklaşan olaylar</h3>
        <div className="news">
          {cal.upcoming.length === 0 && <div className="muted">kayıt yok</div>}
          {cal.upcoming.slice(0, 25).map((e) => (
            <EventRow key={e.id} ev={e} />
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Araştırma notları</h3>
        {res.notes.length === 0 && (
          <div className="muted">
            Henüz not yok — araştırmacı yaklaşan olaylar için otomatik üretir.
          </div>
        )}
        {res.notes.map((n) => (
          <NoteCard key={`${n.event_id}-${n.phase}`} n={n} />
        ))}
      </div>
    </>
  )
}
