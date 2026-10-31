// Änderungsmeldungen von Mitgliedern prüfen und übernehmen.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PERM } from '../../api/orgs.ts'
import { ApiError } from '../../api/client.ts'
import { portalApi } from '../../api/portal.ts'
import type { ChangeRequest } from '../../api/portal.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { ChangeTable } from '../portal/PortalPage.tsx'

export function ChangeRequestsPage() {
  const org = useActiveOrg()
  const [status, setStatus] = useState('pending')
  // Ergebnisse gehören zum gewählten Status; beim Wechsel nie die alten zeigen (UX-Audit 31.10. W02)
  const loaded = useLoad(
    () => portalApi.changeRequests(org.id, status).then((items) => ({ status, items })),
    [org.id, status],
  )
  const data = loaded.data?.status === status ? loaded.data.items : null
  const { error, reload } = loaded
  const canEdit = org.permissions.includes(PERM.membersEdit)

  return (
    <>
      <div className="card card-wide filters">
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">offen</option>
          <option value="accepted">übernommen</option>
          <option value="rejected">abgelehnt</option>
          <option value="alle">alle</option>
        </select>
      </div>
      {error && (
        <LoadError
          message={`Die Änderungsmeldungen konnten nicht geladen werden (${error}).`}
          onRetry={() => void reload()}
        />
      )}
      {!data ? (
        !error && (
          <p className="muted" role="status">
            Lädt …
          </p>
        )
      ) : data.length === 0 ? (
        <div className="card empty-state">
          <p>Keine Meldungen.</p>
        </div>
      ) : (
        <div className="stack">
          {data.map((c) => (
            <RequestCard key={c.id} orgId={org.id} request={c} canEdit={canEdit} onDone={reload} />
          ))}
        </div>
      )}
    </>
  )
}

function RequestCard({
  orgId,
  request: c,
  canEdit,
  onDone,
}: {
  orgId: number
  request: ChangeRequest
  canEdit: boolean
  onDone: () => void
}) {
  const [response, setResponse] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decide(accept: boolean) {
    setBusy(true)
    setError(null)
    try {
      try {
        await portalApi.decide(orgId, c.id, accept, response)
      } catch (err) {
        // Inzwischen im Verein geänderte Felder: erst nachfragen
        if (!(err instanceof ApiError) || err.status !== 409) throw err
        const ok = await confirmDialog({
          title: 'Neuere Angaben überschreiben?',
          message: err.message,
          confirmLabel: 'Trotzdem annehmen',
        })
        if (!ok) return
        await portalApi.decide(orgId, c.id, accept, response, true)
      }
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>
          <Link to={`/mitglieder/${c.member_id}`}>{c.member_name}</Link>
        </h2>
        <span className="muted small push-right">
          {c.status_label} · gemeldet {formatDateTime(c.created_at)}
        </span>
      </div>
      <ChangeTable request={c} />
      {c.message && <p className="small">Nachricht: {c.message}</p>}
      {c.response && <p className="small">Antwort: {c.response}</p>}
      {c.status === 'pending' && canEdit && (
        <>
          <label className="field">
            <span>Antwort an das Mitglied (optional)</span>
            <input value={response} maxLength={500} onChange={(e) => setResponse(e.target.value)} />
          </label>
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void decide(true)}
            >
              Übernehmen
            </button>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => void decide(false)}
            >
              Ablehnen
            </button>
          </div>
        </>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
