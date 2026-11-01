import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { portalApi } from '../api/portal.ts'
import type { AccessInfo } from '../api/portal.ts'
import { errorMessage, formatDateTime, useLoad } from './forms.ts'
import { Alert } from './ui.tsx'
import { confirmDialog } from './dialog.ts'
import { useTerms } from '../org/terms.ts'

export function AccessPanel({
  access,
  hasEmail,
  contactEmail,
  canManage,
  disabledHint,
  onSend,
  onRemove,
}: {
  access: AccessInfo | null
  hasEmail: boolean
  /** Aktuelle Kontakt-Adresse: weicht sie vom Zugang ab, gibt es „übertragen“ */
  contactEmail?: string
  canManage: boolean
  disabledHint?: ReactNode
  onSend: (transfer?: boolean) => Promise<{ sent: 'link' | 'password' }>
  onRemove: () => Promise<unknown>
}) {
  const tm = useTerms()
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setMessage(null)
    try {
      setMessage({ kind: 'success', text: await action() })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  const moved =
    !!access && !!contactEmail && contactEmail.toLowerCase() !== access.email.toLowerCase()

  async function transfer() {
    if (!access) return
    const ok = await confirmDialog({
      title: 'Zugang auf neue Adresse übertragen?',
      message:
        `Der Zugang hängt bisher an ${access.email}. Danach meldet sich das Mitglied mit ` +
        `${contactEmail ?? 'der neuen Adresse'} an; die bisherige Adresse bekommt eine ` +
        'Mitteilung. Nur übertragen, wenn sicher ist, dass die neue Adresse dem Mitglied gehört.',
      confirmLabel: 'Übertragen',
    })
    if (!ok) return
    void run(async () => {
      await onSend(true)
      return 'Zugang übertragen; Link an die neue Adresse gesendet.'
    })
  }

  return (
    <div className="card card-wide">
      <h2>Zugang</h2>
      {access ? (
        <p>
          Zugang mit <strong>{access.email}</strong> seit {formatDateTime(access.created_at)}
          <br />
          <span className="muted small">
            {access.last_login
              ? `zuletzt angemeldet ${formatDateTime(access.last_login)}`
              : 'noch nicht angemeldet'}{' '}
            · Anmeldung {access.login === 'link' ? 'per Anmeldelink oder Passwort' : 'mit Passwort'}
          </span>
        </p>
      ) : (
        <p className="muted">
          Noch kein Zugang. Mit einem Zugang sieht das Mitglied seine Daten und kann Änderungen
          melden; Inhaber von Rollen {tm.im} arbeiten damit in {tm.ihrem}.
        </p>
      )}
      {disabledHint && <Alert kind="info">{disabledHint}</Alert>}
      {moved && canManage && (
        <Alert kind="info">
          Die Kontakt-Adresse ist jetzt {contactEmail}. Der Zugang bleibt bei {access?.email}, bis
          ihr ihn ausdrücklich überträgt.
        </Alert>
      )}
      {canManage && !disabledHint && (
        <div className="button-row">
          <button
            type="button"
            className="button button-primary"
            disabled={busy || !hasEmail}
            onClick={() =>
              void run(async () => {
                const r = await onSend(false)
                return r.sent === 'link'
                  ? 'Anmeldelink per E-Mail gesendet.'
                  : 'Link zum Festlegen des Passworts gesendet (Konto mit Rollenrechten).'
              })
            }
          >
            {access
              ? `Neuen Link senden${moved ? ` an ${access.email}` : ''}`
              : 'Zugang einrichten und Link senden'}
          </button>
          {moved && (
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void transfer()}
            >
              Zugang auf neue Adresse übertragen
            </button>
          )}
          {access && (
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={async () => {
                if (
                  await confirmDialog({
                    title: 'Zugang entfernen?',
                    message: 'Die Person kann sich danach nicht mehr mit diesem Zugang anmelden.',
                    confirmLabel: 'Entfernen',
                  })
                ) {
                  void run(async () => {
                    await onRemove()
                    return 'Zugang entfernt.'
                  })
                }
              }}
            >
              Zugang entfernen
            </button>
          )}
        </div>
      )}
      {!hasEmail && canManage && (
        <p className="muted small">Für einen Zugang braucht das Mitglied eine E-Mail-Adresse.</p>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </div>
  )
}

/** Zugang in der Mitgliedsakte des Vereins (lädt den Status selbst). */
export function MemberAccessSection({
  orgId,
  memberId,
  hasEmail,
  contactEmail,
  canManage,
}: {
  orgId: number
  memberId: number
  hasEmail: boolean
  contactEmail?: string
  canManage: boolean
}) {
  const tm = useTerms()
  const { data, error, setData } = useLoad(
    () => portalApi.memberAccess(orgId, memberId),
    [orgId, memberId],
  )
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return null
  const enabled = data.portal_enabled || data.department_access_enabled
  return (
    <AccessPanel
      access={data.access}
      hasEmail={hasEmail}
      contactEmail={contactEmail}
      canManage={canManage}
      disabledHint={
        enabled || data.access ? undefined : (
          <>
            Zugänge sind ausgeschaltet. Den Mitgliederbereich schaltet ihr unter{' '}
            <Link to="/mitglieder/einrichtung/mitgliederbereich">
              Mitglieder → Einrichtung → Mitgliederbereich & Fotos
            </Link>{' '}
            ein, den Zugang für {tm.pl} unter{' '}
            <Link to="/einstellungen/organisation">Einstellungen → Organisation</Link>.
          </>
        )
      }
      onSend={async (transfer) => {
        const r = await portalApi.sendMemberAccess(orgId, memberId, transfer)
        setData({ ...data, access: r.access })
        return r
      }}
      onRemove={async () => {
        await portalApi.removeMemberAccess(orgId, memberId)
        setData({ ...data, access: null })
      }}
    />
  )
}
