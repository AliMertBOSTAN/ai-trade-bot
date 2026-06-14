import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { NewsItem } from '@shared/types'

function ago(ts: number): string {
  if (!ts) return ''
  const s = Math.max(0, (Date.now() - ts) / 1000)
  if (s < 60) return `${s | 0}sn`
  if (s < 3600) return `${(s / 60) | 0}dk`
  if (s < 86400) return `${(s / 3600) | 0}sa`
  return `${(s / 86400) | 0}g`
}

export default function NewsPanel(): JSX.Element {
  const [items, setItems] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems(await api.news(25))
      setErr(false)
    } catch {
      setErr(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000) // haber 60 sn'de bir
    return () => clearInterval(t)
  }, [load])

  if (loading) return <div className="muted">haberler yükleniyor…</div>
  if (err && !items.length) return <div className="muted">haber akışına ulaşılamadı</div>

  return (
    <div className="news">
      {items.map((n, i) => (
        <a className="news-item" key={i} href={n.link || undefined} target="_blank" rel="noreferrer">
          <div className="news-top">
            <span className="news-src">{n.source}</span>
            <span className="muted small">{ago(n.ts)}</span>
          </div>
          <div className="news-title">{n.title}</div>
          {n.summary && <div className="muted small news-sum">{n.summary}</div>}
        </a>
      ))}
      {!items.length && <div className="muted">başlık yok</div>}
    </div>
  )
}
