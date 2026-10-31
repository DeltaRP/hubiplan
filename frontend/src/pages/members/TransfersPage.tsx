import { useState } from 'react'
import { memberApi } from '../../api/members.ts'
import type { Transfer } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'

/** Wechselanfragen: eingegangene beantworten, gestellte verfolgen. */
export function TransfersPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const terms = useTerms()
  const { data, error, reload } = useLoad(() => memberApi.transfers(org.id), [org.id])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  const incoming = data.filter((t) => t.direction === 'incoming')
  const outgoing = data.filter((t) => t.direction === 'outgoing')

  return (
    <>
      <p className="muted">
        Will {terms.e_ein_anderer} {terms.dv_im} ein Mitglied aktiv aufnehmen, das bei euch noch
        aktiv ist, bestätigt ihr hier den Austritt oder den Wechsel zu einer nicht aktiven Art.
      </p>
      <div className="stack">
        <div className="card card-wide">
          <h2>Eingegangen</h2>
          {incoming.length === 0 ? (
            <p className="muted">Keine Anfragen.</p>
          ) : (
            incoming.map((t) => (
              <IncomingItem
                key={t.id}
                orgId={org.id}
                transfer={t}
                canEdit={canEdit}
                onDone={reload}
              />
            ))
          )}
        </div>
        <div className="card card-wide">
          <h2>Gestellt</h2>
          {outgoing.length === 0 ? (
            <p className="muted">Keine Anfragen.</p>
          ) : (
            outgoing.map((t) => (
              <OutgoingItem
                key={t.id}
                orgId={org.id}
                transfer={t}
                canEdit={canEdit}
                onDone={reload}
              />
            ))
          )}
        </div>
      </div>
    </>
  )
}

function Summary({ t }: { t: Transfer }) {
  return (
    <>
      <div>
        <strong>{t.person_name}</strong> · geb. {formatDate(t.birth_date)}
      </div>
      <div className="small">
        {t.from_org_name} → {t.to_org_name} als „{t.member_type_name}“ ab {formatDate(t.entry_date)}
      </div>
      {t.message && <div className="small muted">„{t.message}“</div>}
      <div className="small muted">
        gestellt {formatDateTime(t.created_at)} · {t.status_label}
        {t.decision_label && ` · ${t.decision_label}`}
        {t.response && ` · Antwort: „${t.response}“`}
      </div>
    </>
  )
}

function IncomingItem({
  orgId,
  transfer,
  canEdit,
  onDone,
}: {
  orgId: number
  transfer: Transfer
  canEdit: boolean
  onDone: () => Promise<void>
}) {
  const types = useLoad(() => memberApi.types(orgId), [orgId])
  const [newType, setNewType] = useState('')
  const [response, setResponse] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function decide(decision: string) {
    setBusy(true)
    setError(null)
    try {
      await memberApi.decideTransfer(orgId, transfer.id, {
        decision,
        member_type: decision === 'change_type' ? Number(newType) : undefined,
        response,
      })
      await onDone()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const passive = types.data?.filter((t) => !t.active && !t.is_archived) ?? []

  return (
    <div className="transfer-item">
      <Summary t={transfer} />
      {transfer.status === 'pending' && canEdit && (
        <div className="transfer-actions">
          <input
            aria-label="Antwort (optional)"
            placeholder="Antwort (optional)"
            value={response}
            onChange={(e) => setResponse(e.target.value)}
          />
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void decide('exit')}
            >
              Austritt bestätigen
            </button>
            <select
              aria-label="nicht aktive Art"
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
            >
              <option value="">Wechsel zu nicht aktiver Art …</option>
              {passive.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy || !newType}
              onClick={() => void decide('change_type')}
            >
              Art wechseln und bestätigen
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={() => void decide('reject')}
            >
              Ablehnen
            </button>
          </div>
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

function OutgoingItem({
  orgId,
  transfer,
  canEdit,
  onDone,
}: {
  orgId: number
  transfer: Transfer
  canEdit: boolean
  onDone: () => Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="transfer-item">
      <Summary t={transfer} />
      {transfer.status === 'pending' && canEdit && (
        <button
          type="button"
          className="link-button"
          onClick={async () => {
            try {
              await memberApi.cancelTransfer(orgId, transfer.id)
              await onDone()
            } catch (err) {
              setError(errorMessage(err))
            }
          }}
        >
          Anfrage zurückziehen
        </button>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
