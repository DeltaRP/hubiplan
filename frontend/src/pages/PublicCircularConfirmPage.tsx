import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { publicConfirmApi } from '../api/circulars.ts'
import type { PublicConfirm } from '../api/circulars.ts'
import { ApiError } from '../api/client.ts'
import { MarkupPreview } from '../components/circulars/MarkupEditor.tsx'
import { errorMessage } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'

/** Bestätigungslink aus der Mail an den Absender eines Verteilers (ohne Anmeldung).
 *  Erst der Knopf versendet: Virenscanner öffnen Links in Mails oft vorab. */
export function PublicCircularConfirmPage() {
  const token = useParams().token ?? ''
  const [info, setInfo] = useState<PublicConfirm | null>(null)
  const [invalid, setInvalid] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    publicConfirmApi
      .get(token)
      .then((d) => alive && setInfo(d))
      .catch((err) => {
        if (!alive) return
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) setInvalid(true)
        else setUnavailable(true)
      })
    return () => {
      alive = false
    }
  }, [token, attempt])

  async function act(action: 'send' | 'discard') {
    setBusy(true)
    setError(null)
    try {
      setInfo(await publicConfirmApi.act(token, action))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const counts = info?.counts
  return (
    <main className="login-page">
      <div className="card public-photo">
        <div className="login-logo">
          <Logo name={info?.organization || 'HUBIplan'} logoUrl={null} />
        </div>
        <h1>Rundschreiben bestätigen</h1>
        {invalid && <Alert kind="error">Dieser Link ist ungültig oder abgelaufen.</Alert>}
        {unavailable && (
          <>
            <Alert kind="error">
              Die Seite kann gerade nicht geladen werden. Bitte später erneut versuchen.
            </Alert>
            <div className="button-row">
              <button
                type="button"
                className="button button-primary"
                onClick={() => {
                  setUnavailable(false)
                  setAttempt((n) => n + 1)
                }}
              >
                Erneut versuchen
              </button>
            </div>
          </>
        )}
        {!info && !invalid && !unavailable && <p className="muted">Lädt …</p>}
        {info && (
          <>
            <p>
              <strong>{info.subject}</strong>
              <br />
              <span className="muted small">
                an den Verteiler {info.list} ({info.address})
              </span>
            </p>
            {counts && (
              <p>
                Empfänger: {'app' in counts && counts.app ? `${counts.app} per App, ` : ''}
                {counts.mail} per E-Mail
                {counts.letter ? `, ${counts.letter} per Brief` : ''}
              </p>
            )}
            {info.body && (
              <div className="subcard">
                <MarkupPreview text={info.body} />
              </div>
            )}
            {info.attachments.length > 0 && (
              <p className="small">Anhänge: {info.attachments.join(', ')}</p>
            )}
            {info.status === 'waiting' ? (
              <div className="button-row">
                <button
                  type="button"
                  className="button button-primary"
                  disabled={busy}
                  onClick={() => void act('send')}
                >
                  Jetzt versenden
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={busy}
                  onClick={() => void act('discard')}
                >
                  Verwerfen
                </button>
              </div>
            ) : (
              <Alert kind={info.status === 'sent' ? 'success' : 'info'}>
                {info.status === 'sent'
                  ? 'Das Rundschreiben wird versendet. Briefe für Mitglieder ohne E-Mail findest du in HUBIplan unter Rundschreiben.'
                  : `Stand: ${info.status_label}.`}
              </Alert>
            )}
          </>
        )}
        {error && <Alert kind="error">{error}</Alert>}
      </div>
    </main>
  )
}
