// Mitgliederakte: Einwilligungen und Widersprüche zur Veröffentlichung auf der
// Webseite. Name mit Funktion und Würden erscheinen aus berechtigtem Interesse,
// solange kein Widerspruch vorliegt; alles andere nur mit Einwilligung.
import { useState } from 'react'
import { websiteApi } from '../../api/website.ts'
import type { ConsentCategory } from '../../api/website.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'

export function PublicationSection({
  orgId,
  memberId,
  canEdit,
}: {
  orgId: number
  memberId: number
  canEdit: boolean
}) {
  const { data, error, reload, setData } = useLoad(
    () => websiteApi.consents(orgId, memberId),
    [orgId, memberId],
  )
  const [source, setSource] = useState<'board' | 'paper'>('paper')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function toggle(c: ConsentCategory) {
    setBusy(true)
    setMessage(null)
    try {
      setData(
        await websiteApi.setConsent(orgId, memberId, {
          category: c.category,
          active: !c.active,
          source,
        }),
      )
    } catch (err) {
      setMessage(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>Veröffentlichung auf der Webseite</h2>
      <p className="muted small">
        Name mit Funktion sowie Würden und Chronik erscheinen ohne Einwilligung, solange das
        Mitglied nicht widerspricht. Foto, E-Mail, Telefon und Jubiläen erscheinen nur mit
        Einwilligung. Für das Foto braucht es zusätzlich die Foto-Einwilligung. „Freigegeben“ heißt
        nur, dass die Angabe erscheinen darf: Ob sie sichtbar ist, hängt außerdem davon ab, ob es
        sie gibt (z. B. ein Foto oder eine Funktion) und wie die Webseite eingestellt ist.
      </p>
      {error && <LoadError message={error} onRetry={() => void reload()} />}
      {!data && !error && <p className="muted">Lädt …</p>}
      {data && (
        <>
          {canEdit && (
            <label className="field">
              <span>Neue Einträge erfasst durch</span>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as 'board' | 'paper')}
              >
                <option value="paper">Papierformular (unterschrieben)</option>
                <option value="board">Vorstand (z. B. mündlich)</option>
              </select>
            </label>
          )}
          <table className="table">
            <thead>
              <tr>
                <th>Angabe</th>
                <th>Stand</th>
                <th>Zur Veröffentlichung freigegeben</th>
                {canEdit && <th aria-label="Ändern" />}
              </tr>
            </thead>
            <tbody>
              {data.categories.map((c) => (
                <tr key={c.category}>
                  <td>{c.label}</td>
                  <td>
                    {c.kind === 'objection'
                      ? c.active
                        ? `Widerspruch seit ${formatDate(c.since)}`
                        : 'kein Widerspruch'
                      : c.active
                        ? `Einwilligung seit ${formatDate(c.since)}`
                        : 'keine Einwilligung'}
                    {c.history.some((h) => h.ended_at) && (
                      <small className="muted">
                        {' '}
                        (früher:{' '}
                        {c.history
                          .filter((h) => h.ended_at)
                          .map((h) => `${formatDate(h.since)} bis ${formatDate(h.ended_at)}`)
                          .join(', ')}
                        )
                      </small>
                    )}
                  </td>
                  <td>{c.published ? 'ja' : 'nein'}</td>
                  {canEdit && (
                    <td>
                      <button
                        type="button"
                        className="button button-ghost"
                        disabled={busy}
                        onClick={() => void toggle(c)}
                      >
                        {c.kind === 'objection'
                          ? c.active
                            ? 'Widerspruch aufheben'
                            : 'Widerspruch erfassen'
                          : c.active
                            ? 'Einwilligung widerrufen'
                            : 'Einwilligung erfassen'}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {message && <Alert kind="error">{message}</Alert>}
        </>
      )}
    </div>
  )
}
