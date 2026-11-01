// Standmodus: Vollbild ohne Menü, für Tablet, Laptop und Handy am Schießstand.
import { Link, useParams } from 'react-router-dom'
import { competitionsApi } from '../../api/competitions.ts'
import { useLoad } from '../../components/forms.ts'
import { LoadError } from '../../components/ui.tsx'
import { StandPanel } from './StandPanel.tsx'

export function StandPage() {
  const params = useParams()
  const org = Number(params.org)
  const id = Number(params.id)
  const { data, error, reload } = useLoad(async () => {
    const key = `hubiplan.stand.detail.${org}.${id}`
    try {
      const detail = await competitionsApi.get(org, id)
      try {
        localStorage.setItem(key, JSON.stringify(detail))
      } catch {
        // ohne Speicher geht es online weiter
      }
      return detail
    } catch (err) {
      // Ohne Empfang: zuletzt geladene Einrichtung vom Gerät
      const cached = localStorage.getItem(key)
      if (cached) return JSON.parse(cached)
      throw err
    }
  }, [org, id])
  return (
    <main className="stand-page">
      <header className="stand-head">
        <strong>{data?.title ?? 'Standmodus'}</strong>
        <Link className="push-right" to={`/wettbewerbe/${id}`}>
          Beenden
        </Link>
      </header>
      {error && <LoadError message={error} onRetry={reload} />}
      {data && <StandPanel org={org} comp={data} fullscreen />}
    </main>
  )
}
