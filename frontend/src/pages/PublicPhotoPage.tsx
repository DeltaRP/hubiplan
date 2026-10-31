import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { photoApi } from '../api/photos.ts'
import type { PublicLinkInfo } from '../api/photos.ts'
import { formatDate } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { PhotoEditor } from '../components/PhotoEditor.tsx'
import { Alert } from '../components/ui.tsx'
import { usePublicImprint } from '../components/publicImprint.ts'
import { applyTheme } from '../theme/theme.ts'

/** Öffentliche Seite des persönlichen Upload-Links (ohne Anmeldung). */
export function PublicPhotoPage() {
  const token = useParams().token ?? ''
  const [info, setInfo] = useState<PublicLinkInfo | null>(null)
  const [state, setState] = useState<
    'loading' | 'ready' | 'invalid' | 'unavailable' | 'done' | 'pending'
  >('loading')
  const [attempt, setAttempt] = useState(0)
  usePublicImprint(info?.imprint_key, info?.organization)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    photoApi
      .publicInfo(token)
      .then(({ status, body }) => {
        if (!alive) return
        if (status === 200) {
          setInfo(body)
          applyTheme(body.theme)
          setState('ready')
        } else if (status === 429) {
          setError('Zu viele Aufrufe. Bitte später erneut versuchen.')
          setState('invalid')
        } else if (status === 404 || status === 410) {
          setState('invalid')
        } else {
          setState('unavailable')
        }
      })
      .catch(() => alive && setState('unavailable'))
    return () => {
      alive = false
    }
  }, [token, attempt])

  async function upload(blob: Blob) {
    if (!consent) {
      setError('Bitte bestätigen Sie Ihre Einwilligung.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const { status, body } = await photoApi.publicUpload(token, blob)
      if (status === 201) setState(body.status === 'pending' ? 'pending' : 'done')
      else if (status === 404) setState('invalid')
      else if (status === 429) setError('Zu viele Versuche. Bitte später erneut versuchen.')
      else setError(Object.values(body).flat().join(' ') || 'Das hat nicht geklappt.')
    } catch {
      setError('Der Server ist nicht erreichbar.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <div className="card public-photo">
        <div className="login-logo">
          <Logo name={info?.organization ?? 'HUBIplan'} logoUrl={info?.logo_url ?? null} />
        </div>
        {state === 'loading' && <p className="muted">Lädt …</p>}
        {state === 'invalid' && (
          <Alert kind="error">
            {error ?? 'Dieser Link ist nicht (mehr) gültig. Bitte wenden Sie sich an den Vorstand.'}
          </Alert>
        )}
        {state === 'unavailable' && (
          <>
            <Alert kind="error">
              Die Seite kann gerade nicht geladen werden. Bitte Verbindung prüfen und erneut
              versuchen.
            </Alert>
            <div className="button-row">
              <button
                type="button"
                className="button button-primary"
                onClick={() => {
                  setState('loading')
                  setAttempt((n) => n + 1)
                }}
              >
                Erneut versuchen
              </button>
            </div>
          </>
        )}
        {state === 'done' && <Alert kind="success">Danke! Ihr Foto ist gespeichert.</Alert>}
        {state === 'pending' && (
          <Alert kind="success">
            Danke! Ihr Foto ist eingegangen und wird vom Vorstand noch freigegeben.
          </Alert>
        )}
        {state === 'ready' && info && (
          <>
            <h1>Hallo {info.first_name}!</h1>
            <p>
              Hier können Sie ein Foto für {info.organization} hochladen. Sie können es drehen,
              spiegeln und den Ausschnitt wählen.
            </p>
            <p className="muted small">
              Der Link ist gültig bis {formatDate(info.expires_at)} und nur einmal nutzbar.
            </p>
            <PhotoEditor busy={busy} submitLabel="Foto hochladen" onDone={upload}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                <span>
                  Ich willige ein, dass {info.organization} dieses Foto für die Mitgliederverwaltung
                  und für meinen digitalen Mitgliedsausweis verwendet. Wer den QR-Code oder Link
                  meines Ausweises öffnet, sieht dort auch das Foto. Ich kann die Einwilligung
                  jederzeit beim Vorstand widerrufen; das Foto wird dann gelöscht.
                </span>
              </label>
            </PhotoEditor>
            {error && <Alert kind="error">{error}</Alert>}
          </>
        )}
      </div>
    </main>
  )
}
