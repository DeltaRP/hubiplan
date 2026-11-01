import { useState } from 'react'
import { photoApi } from '../../api/photos.ts'
import type { PhotoState, UploadLink } from '../../api/photos.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { PhotoEditor } from '../../components/PhotoEditor.tsx'
import { Alert } from '../../components/ui.tsx'
import { todayIso } from '../../api/members.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { Term, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

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
      <h2>{t('Foto')}</h2>
      <Why k="photo_consent" />
      <div className="photo-row">
        <div className="photo-frame">
          {photo ? (
            <img src={photo.url} alt={t('Foto des Mitglieds')} />
          ) : (
            <span className="muted small">{t('kein Foto')}</span>
          )}
        </div>
        <div className="photo-info">
          {photo && (
            <p className="small muted">
              {photo.source_label} · {formatDateTime(photo.uploaded_at)}
            </p>
          )}
          <p className="small">
            {t('Foto-')}
            <Term k="consent">{t('Einwilligung')}</Term>:{' '}
            {state.photo_consent_at
              ? t('{x} ({x2})', {
                  x: formatDate(state.photo_consent_at),
                  x2:
                    state.photo_consent_source === 'member'
                      ? 'vom Mitglied'
                      : state.photo_consent_source === 'app'
                        ? 'vom Mitglied in der App'
                        : 'durch den Vorstand erfasst',
                })
              : t('liegt nicht vor')}
          </p>
          {canManage && !editing && (
            <div className="button-row">
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setEditing(true)}
              >
                {photo ? t('Foto ersetzen') : t('Foto hochladen')}
              </button>
              {photo && (
                <>
                  <button
                    type="button"
                    className="button button-ghost"
                    disabled={busy}
                    aria-label={t('Foto nach links drehen')}
                    onClick={() => void run(() => photoApi.rotate(orgId, memberId, 'left'))}
                  >
                    ⟲
                  </button>
                  <button
                    type="button"
                    className="button button-ghost"
                    disabled={busy}
                    aria-label={t('Foto nach rechts drehen')}
                    onClick={() => void run(() => photoApi.rotate(orgId, memberId, 'right'))}
                  >
                    ⟳
                  </button>
                  <button
                    type="button"
                    className="button button-danger"
                    disabled={busy}
                    onClick={async () => {
                      if (
                        await confirmDialog({
                          title: t('Foto löschen?'),
                          confirmLabel: t('Löschen'),
                        })
                      )
                        void run(() => photoApi.remove(orgId, memberId))
                    }}
                  >
                    {t('Löschen')}
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
                        title: t('Einwilligung als widerrufen erfassen?'),
                        message: t('Vorhandene Fotos werden gelöscht.'),
                        confirmLabel: t('Widerruf erfassen'),
                      })
                    ) {
                      void run(() => photoApi.setConsent(orgId, memberId, null))
                    }
                  }}
                >
                  {t('Einwilligung widerrufen')}
                </button>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {canManage && pending && (
        <div className="subcard">
          <h3>{t('Vom Mitglied hochgeladen – wartet auf Freigabe')}</h3>
          <img src={pending.url} alt={t('Neues Foto des Mitglieds')} className="photo-pending" />
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void run(() => photoApi.decide(orgId, memberId, 'approve'))}
            >
              {t('Freigeben')}
            </button>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => void run(() => photoApi.decide(orgId, memberId, 'reject'))}
            >
              {t('Ablehnen')}
            </button>
          </div>
        </div>
      )}

      {editing && (
        <div className="subcard">
          <PhotoEditor
            busy={busy}
            submitLabel={t('Foto speichern')}
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
                  {t(
                    'Die Einwilligung des Mitglieds zur Verwendung des Fotos liegt vor (Datum: heute,  {x}).',
                    { x: formatDate(todayIso()) },
                  )}
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
      <h3>{t('Foto vom Mitglied anfordern')}</h3>
      <p className="muted small">
        {t(
          'Persönlicher Link ohne Anmeldung: 14 Tage gültig, einmal nutzbar. Das Mitglied gibt dort seine Einwilligung und schneidet das Bild selbst zu.',
        )}
      </p>
      <div className="button-row">
        <button
          type="button"
          className="button button-ghost"
          disabled={!hasEmail}
          onClick={() => void create(true)}
          title={hasEmail ? undefined : t('Keine E-Mail-Adresse hinterlegt')}
        >
          {t('Link per E-Mail senden')}
        </button>
        <button type="button" className="button button-ghost" onClick={() => void create(false)}>
          {t('Link erzeugen und kopieren')}
        </button>
      </div>
      {created?.url && (
        <Alert kind="info">
          {created.sent_to ? t('Gesendet an {sent_to}. ', { sent_to: created.sent_to }) : ''}
          {t('Link (nur jetzt sichtbar):')} <code>{created.url}</code>{' '}
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
              {l.sent_to && t(' · an {sent_to}', { sent_to: l.sent_to })} {t('· gültig bis')}{' '}
              {formatDate(l.expires_at)}
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
