// Standmodus: Vollbild ohne Menü, für Tablet, Laptop und Handy am Schießstand.
// Angemeldet über /stand/<einheit>/<wettbewerb> oder ohne Konto über einen Standzugang
// (/stand/zugang/<schlüssel>). Der Bildschirm bleibt an, und die Seite lässt sich auch ohne
// Netz neu laden (Offline-Speicher im Browser, public/sw-stand.js).
import { useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  orgStandApi,
  tokenStandApi,
  type CompetitionDetail,
  type StandApi,
} from '../../api/competitions.ts'
import { useLoad } from '../../components/forms.ts'
import { LoadError } from '../../components/ui.tsx'
import { BirdStand } from './BirdStand.tsx'
import { StandPanel } from './StandPanel.tsx'

export function StandPage() {
  const params = useParams()
  const org = Number(params.org)
  const id = Number(params.id)
  const api = useMemo(() => orgStandApi(org, id), [org, id])
  return <StandShell api={api} exit={<Link to={`/wettbewerbe/${id}`}>Beenden</Link>} />
}

export function StandTokenPage() {
  const token = useParams().token ?? ''
  const api = useMemo(() => tokenStandApi(token), [token])
  return <StandShell api={api} exit={null} />
}

function StandShell({ api, exit }: { api: StandApi; exit: ReactNode }) {
  const { data, error, reload } = useLoad(async () => {
    const key = `hubiplan.stand.detail.${api.key}`
    try {
      const detail = await api.get()
      try {
        localStorage.setItem(key, JSON.stringify(detail))
      } catch {
        // ohne Speicher geht es online weiter
      }
      return detail
    } catch (err) {
      // Ohne Empfang: zuletzt geladene Einrichtung vom Gerät
      const cached = localStorage.getItem(key)
      if (cached) return JSON.parse(cached) as CompetitionDetail
      throw err
    }
  }, [api.key])
  useWakeLock()
  useOfflineReload()
  return (
    <main className="stand-page">
      <header className="stand-head">
        <strong>{data?.title ?? 'Standmodus'}</strong>
        {data?.stand_access && (
          <span className="muted small">
            Standzugang{data.stand_access.label ? ` ${data.stand_access.label}` : ''} bis{' '}
            {new Date(data.stand_access.expires_at).toLocaleTimeString('de-DE', {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        )}
        {exit && <span className="push-right">{exit}</span>}
      </header>
      {error && <LoadError message={error} onRetry={reload} />}
      {data &&
        (!data.own ? (
          <p className="alert alert-info">
            Bei fremden Wettbewerben gibt es keinen Standmodus. Plätze bitte unter „Erfassen“
            eintragen.
          </p>
        ) : data.form === 'vogel' ? (
          <BirdStand api={api} comp={data} fullscreen />
        ) : (
          <StandPanel api={api} comp={data} fullscreen />
        ))}
    </main>
  )
}

/** Bildschirm bleibt an, solange der Standmodus offen und sichtbar ist. */
function useWakeLock() {
  useEffect(() => {
    type Sentinel = { release: () => Promise<void> }
    const nav = navigator as Navigator & {
      wakeLock?: { request: (type: 'screen') => Promise<Sentinel> }
    }
    if (!nav.wakeLock) return
    let lock: Sentinel | null = null
    let stop = false
    const take = () => {
      if (document.visibilityState !== 'visible') return
      nav.wakeLock
        ?.request('screen')
        .then((l) => {
          if (stop) void l.release()
          else lock = l
        })
        .catch(() => undefined)
    }
    take()
    document.addEventListener('visibilitychange', take)
    return () => {
      stop = true
      document.removeEventListener('visibilitychange', take)
      void lock?.release().catch(() => undefined)
    }
  }, [])
}

/** Offline-Speicher: die Seite und ihre Dateien für das Neuladen ohne Netz vormerken. */
function useOfflineReload() {
  useEffect(() => {
    if (!('serviceWorker' in navigator) || !window.isSecureContext) return
    const assets = performance
      .getEntriesByType('resource')
      .map((e) => new URL(e.name).pathname)
      .filter((p) => p.startsWith('/assets/'))
    navigator.serviceWorker
      .register('/sw-stand.js', { scope: '/' })
      .then(() => navigator.serviceWorker.ready)
      .then((reg) =>
        reg.active?.postMessage({
          type: 'merken',
          page: window.location.pathname,
          assets: [...new Set(assets)],
        }),
      )
      .catch(() => undefined)
  }, [])
}
