import { useState } from 'react'
import { photoApi } from '../../api/photos.ts'
import type { PhotoState, UploadLink } from '../../api/photos.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { PhotoEditor } from '../../components/PhotoEditor.tsx'
import { Alert } from '../../components/ui.tsx'
import { todayIso } from '../../api/members.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { Term, Why } from '../../learning/Aids.tsx'

const LINK_STATE: Record<UploadLink['state'], string> = {
  open: 'offen',
  used: 'genutzt',
  expired: 'abgelaufen',
  revoked: 'widerrufen',
}

/** Foto der Mitgliedsakte: ansehen, hochladen, drehen, löschen, freigeben, Upload-Links. */
export function PhotoSection({
  orgId,
  memberId,
  initial,
  canManage,
  hasEmail,
  onChange,
}: {
  orgId: number
  memberId: number
  initial: PhotoState
  canManage: boolean
  hasEmail: boolean
  onChange?: () => void
}) {
  const [state, setState] = useState<PhotoState>(initial)
  const [editing, setEditing] = useState(false)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const photo = state.photo.approved
  const pending = state.photo.pending

  async function run(action: () => Promise<PhotoState | { body: PhotoState }>) {
    setBusy(true)
    setError(null)
    try {
      const result = await action()
      setState('body' in result ? result.body : result)
      onChange?.()
      return true
    } catch (err) {
      setError(errorMessage(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide photo-section">
      <h2>Foto</h2>
      <Why k="photo_consent" />
      <div className="photo-row">
        <div className="photo-frame">
          {photo ? (
            <img src={photo.url} alt="Foto des Mitglieds" />
          ) : (
            <span className="muted small">kein Foto</span>
          )}
        </div>
        <div className="photo-info">
          {photo && (
            <p className="small muted">
              {photo.source_label} · {formatDateTime(photo.uploaded_at)}
            </p>
          )}
          <p className="small">
            Foto-<Term k="consent">Einwilligung</Term>:{' '}
            {state.photo_consent_at
              ? `${formatDate(state.photo_consent_at)} (${state.photo_consent_source === 'member' ? 'vom Mitglied' : state.photo_consent_source === 'app' ? 'vom Mitglied in der App' : 'durch den Vorstand erfasst'})`
              : 'liegt nicht vor'}
          </p>
          {canManage && !editing && (
            <div className="button-row">
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setEditing(true)}
              >
                {photo ? 'Foto ersetzen' : 'Foto hochladen'}
              </button>
              {photo && (
                <>
                  <button
                    type="button"
                    className="button button-ghost"
                    disabled={busy}
                    aria-label="Foto nach links drehen"
                    onClick={() => void run(() => photoApi.rotate(orgId, memberId, 'left'))}
                  >
                    ⟲
                  </button>
                  <button
                    type="button"
                    className="button button-ghost"
                    disabled={busy}
                    aria-label="Foto nach rechts drehen"
                    onClick={() => void run(() => photoApi.rotate(orgId, memberId, 'right'))}
                  >
                    ⟳
                  </button>
                  <button
                    type="button"
                    className="button button-danger"
                    disabled={busy}
                    onClick={async () => {
                      if (await confirmDialog({ title: 'Foto löschen?', confirmLabel: 'Löschen' }))
                        void run(() => photoApi.remove(orgId, memberId))
                    }}
                  >
                    Löschen
                  </button>
                </>
              )}
              {state.photo_consent_at ? (
                <button
                  type="button"
                  className="link-button"
                  disabled={busy}
                  onClick={async () => {
                    if (
                      await confirmDialog({
                        title: 'Einwilligung als widerrufen erfassen?',
                        message: 'Vorhandene Fotos werden gelöscht.',
                        confirmLabel: 'Widerruf erfassen',
                      })
                    ) {
                      void run(() => photoApi.setConsent(orgId, memberId, null))
                    }
                  }}
                >
                  Einwilligung widerrufen
                </button>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {canManage && pending && (
        <div className="subcard">
          <h3>Vom Mitglied hochgeladen – wartet auf Freigabe</h3>
          <img src={pending.url} alt="Neues Foto des Mitglieds" className="photo-pending" />
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void run(() => photoApi.decide(orgId, memberId, 'approve'))}
            >
              Freigeben
            </button>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => void run(() => photoApi.decide(orgId, memberId, 'reject'))}
            >
              Ablehnen
            </button>
          </div>
        </div>
      )}

      {editing && (
        <div className="subcard">
          <PhotoEditor
            busy={busy}
            submitLabel="Foto speichern"
            onCancel={() => setEditing(false)}
            onDone={async (blob) => {
              const ok = await run(() => photoApi.upload(orgId, memberId, blob, consent))
              if (ok) setEditing(false)
            }}
          >
            {!state.photo_consent_at && (
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                <span>
                  Die Einwilligung des Mitglieds zur Verwendung des Fotos liegt vor (Datum: heute,{' '}
                  {formatDate(todayIso())}).
                </span>
              </label>
            )}
          </PhotoEditor>
        </div>
      )}

      {canManage && <UploadLinks orgId={orgId} memberId={memberId} hasEmail={hasEmail} />}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

function UploadLinks({
  orgId,
  memberId,
  hasEmail,
}: {
  orgId: number
  memberId: number
  hasEmail: boolean
}) {
  const { data, reload } = useLoad(() => photoApi.links(orgId, memberId), [orgId, memberId])
  const [created, setCreated] = useState<UploadLink | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function create(sendEmail: boolean) {
    setError(null)
    setCopied(false)
    try {
      setCreated(await photoApi.createLink(orgId, memberId, sendEmail))
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="upload-links">
      <h3>Foto vom Mitglied anfordern</h3>
      <p className="muted small">
        Persönlicher Link ohne Anmeldung: 14 Tage gültig, einmal nutzbar. Das Mitglied gibt dort
        seine Einwilligung und schneidet das Bild selbst zu.
      </p>
      <div className="button-row">
        <button
          type="button"
          className="button button-ghost"
          disabled={!hasEmail}
          onClick={() => void create(true)}
          title={hasEmail ? undefined : 'Keine E-Mail-Adresse hinterlegt'}
        >
          Link per E-Mail senden
        </button>
        <button type="button" className="button button-ghost" onClick={() => void create(false)}>
          Link erzeugen und kopieren
        </button>
      </div>
      {created?.url && (
        <Alert kind="info">
          {created.sent_to ? `Gesendet an ${created.sent_to}. ` : ''}Link (nur jetzt sichtbar):{' '}
          <code>{created.url}</code>{' '}
          <button
            type="button"
            className="link-button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(created.url!)
                setCopied(true)
              } catch {
                setCopied(false)
              }
            }}
          >
            {copied ? 'kopiert' : 'kopieren'}
          </button>
        </Alert>
      )}
      {data && data.length > 0 && (
        <ul className="plain-list small">
          {data.map((l) => (
            <li key={l.id}>
              {formatDateTime(l.created_at)} · {LINK_STATE[l.state]}
              {l.sent_to && ` · an ${l.sent_to}`} · gültig bis {formatDate(l.expires_at)}
              {l.state === 'open' && (
                <button
                  type="button"
                  className="link-button spaced"
                  onClick={async () => {
                    await photoApi.revokeLink(orgId, memberId, l.id)
                    await reload()
                  }}
                >
                  widerrufen
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
