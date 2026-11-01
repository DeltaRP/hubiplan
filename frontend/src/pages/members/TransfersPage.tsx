import { useState } from 'react'
import { memberApi } from '../../api/members.ts'
import type { Transfer } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

/** Wechselanfragen: eingegangene beantworten, gestellte verfolgen. */
export function TransfersPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const terms = useTerms()
  const { data, error, reload } = useLoad(() => memberApi.transfers(org.id), [org.id])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const incoming = data.filter((tm) => tm.direction === 'incoming')
  const outgoing = data.filter((tm) => tm.direction === 'outgoing')

  return (
    <>
      <p className="muted">
        {t(
          'Will {e_ein_anderer} {dv_im} ein Mitglied aktiv aufnehmen, das bei euch noch aktiv ist, bestätigt ihr hier den Austritt oder den Wechsel zu einer nicht aktiven Art.',
          { e_ein_anderer: terms.e_ein_anderer, dv_im: terms.dv_im },
        )}
      </p>
      <div className="stack">
        <div className="card card-wide">
          <h2>{t('Eingegangen')}</h2>
          {incoming.length === 0 ? (
            <p className="muted">{t('Keine Anfragen.')}</p>
          ) : (
            incoming.map((tm) => (
              <IncomingItem
                key={tm.id}
                orgId={org.id}
                transfer={tm}
                canEdit={canEdit}
                onDone={reload}
              />
            ))
          )}
        </div>
        <div className="card card-wide">
          <h2>{t('Gestellt')}</h2>
          {outgoing.length === 0 ? (
            <p className="muted">{t('Keine Anfragen.')}</p>
          ) : (
            outgoing.map((tm) => (
              <OutgoingItem
                key={tm.id}
                orgId={org.id}
                transfer={tm}
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

function Summary({ t: tm }: { t: Transfer }) {
  return (
    <>
      <div>
        <strong>{tm.person_name}</strong> {t('· geb.')} {formatDate(tm.birth_date)}
      </div>
      <div className="small">
        {tm.from_org_name}{' '}
        {t('→ {to_org_name} als „{member_type_name}“ ab', {
          to_org_name: tm.to_org_name,
          member_type_name: tm.member_type_name,
        })}{' '}
        {formatDate(tm.entry_date)}
      </div>
      {tm.message && <div className="small muted">„{tm.message}“</div>}
      <div className="small muted">
        gestellt {formatDateTime(tm.created_at)} · {tm.status_label}
        {tm.decision_label && t(' · {decision_label}', { decision_label: tm.decision_label })}
        {tm.response && t(' · Antwort: „{response}“', { response: tm.response })}
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

  const passive = types.data?.filter((tm) => !tm.active && !tm.is_archived) ?? []

  return (
    <div className="transfer-item">
      <Summary t={transfer} />
      {transfer.status === 'pending' && canEdit && (
        <div className="transfer-actions">
          <input
            aria-label={t('Antwort (optional)')}
            placeholder={t('Antwort (optional)')}
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
              {t('Austritt bestätigen')}
            </button>
            <select
              aria-label={t('nicht aktive Art')}
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
            >
              <option value="">{t('Wechsel zu nicht aktiver Art …')}</option>
              {passive.map((tm) => (
                <option key={tm.id} value={tm.id}>
                  {tm.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy || !newType}
              onClick={() => void decide('change_type')}
            >
              {t('Art wechseln und bestätigen')}
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={() => void decide('reject')}
            >
              {t('Ablehnen')}
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
          {t('Anfrage zurückziehen')}
        </button>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
