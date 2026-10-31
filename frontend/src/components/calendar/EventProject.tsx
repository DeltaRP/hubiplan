// Termin und Veranstaltungsfinanzen verbinden: zugeordnete Veranstaltung zeigen,
// neue anlegen oder eine vorhandene zuordnen (nur Vereins-/Verbandstermine mit Kassenrecht).
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { eventApi } from '../../api/events.ts'
import type { CalendarBase, EventDetail } from '../../api/events.ts'
import { financeApi } from '../../api/finance.ts'
import { errorMessage, useLoad } from '../forms.ts'
import { Alert } from '../ui.tsx'

export function EventProjectPanel({
  base,
  event,
  onChanged,
}: {
  base: CalendarBase
  event: EventDetail
  onChanged: (e: EventDetail) => void
}) {
  const [choosing, setChoosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Nur Kalender einer Organisation (/api/orgs/<id>/) haben Veranstaltungsfinanzen
  const orgId = Number(/\/api\/orgs\/(\d+)\//.exec(base)?.[1] ?? 0)
  const projects = useLoad(
    () => (choosing && orgId ? financeApi.projects(orgId) : Promise.resolve(null)),
    [choosing, orgId],
  )
  if (event.project === undefined) return null

  async function run(data: { project?: number | null; create?: true }) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await eventApi.setProject(base, event.id, data))
      setChoosing(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack-sm">
      <strong>Veranstaltungsfinanzen</strong>
      {event.project ? (
        <p className="small">
          Einnahmen und Ausgaben stehen bei{' '}
          <Link to={`/finanzen/veranstaltungen/${event.project.id}`}>{event.project.name}</Link>.
          {event.can_link_project && (
            <>
              {' '}
              <button
                type="button"
                className="link-button"
                disabled={busy}
                onClick={() => void run({ project: null })}
              >
                lösen
              </button>
            </>
          )}
        </p>
      ) : (
        <p className="muted small">
          Keine Veranstaltung zugeordnet. Mehrere Termine (z. B. die Tage eines Festes) können zu
          einer Veranstaltung mit gemeinsamer Abrechnung gehören.
        </p>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {event.can_link_project && !event.project && !choosing && (
        <div className="button-row">
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() => void run({ create: true })}
          >
            Abrechnung für diesen Termin anlegen
          </button>
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() => setChoosing(true)}
          >
            Vorhandener Veranstaltung zuordnen
          </button>
        </div>
      )}
      {choosing && (
        <div className="button-row">
          {!projects.data ? (
            <span className="muted small">Lädt …</span>
          ) : projects.data.length === 0 ? (
            <span className="muted small">Es gibt noch keine Veranstaltung.</span>
          ) : (
            <label className="field">
              <span>Veranstaltung</span>
              <select
                defaultValue=""
                disabled={busy}
                onChange={(e) => e.target.value && void run({ project: Number(e.target.value) })}
              >
                <option value="" disabled>
                  bitte wählen …
                </option>
                {projects.data.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="button" className="button button-ghost" onClick={() => setChoosing(false)}>
            Abbrechen
          </button>
        </div>
      )}
    </div>
  )
}
