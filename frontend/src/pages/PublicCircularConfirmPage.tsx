import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { publicConfirmApi } from '../api/circulars.ts'
import type { PublicConfirm } from '../api/circulars.ts'
import { ApiError } from '../api/client.ts'
import { MarkupPreview } from '../components/circulars/MarkupEditor.tsx'
import { errorMessage } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'
import { t } from '../i18n/index.ts'

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
        <h1>{t('Rundschreiben bestätigen')}</h1>
        {invalid && <Alert kind="error">{t('Dieser Link ist ungültig oder abgelaufen.')}</Alert>}
        {unavailable && (
          <>
            <Alert kind="error">
              {t('Die Seite kann gerade nicht geladen werden. Bitte später erneut versuchen.')}
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
                {t('Erneut versuchen')}
              </button>
            </div>
          </>
        )}
        {!info && !invalid && !unavailable && <p className="muted">{t('Lädt …')}</p>}
        {info && (
          <>
            <p>
              <strong>{info.subject}</strong>
              <br />
              <span className="muted small">
                {t('an den Verteiler {list} ({address})', {
                  list: info.list,
                  address: info.address,
                })}
              </span>
            </p>
            {counts && (
              <p>
                {t('Empfänger:')}{' '}
                {'app' in counts && counts.app ? t('{app} per App, ', { app: counts.app }) : ''}
                {counts.mail} {t('per E-Mail')}
                {counts.letter ? t(', {letter} per Brief', { letter: counts.letter }) : ''}
              </p>
            )}
            {info.body && (
              <div className="subcard">
                <MarkupPreview text={info.body} />
              </div>
            )}
            {info.attachments.length > 0 && (
              <p className="small">
                {t('Anhänge:')} {info.attachments.join(', ')}
              </p>
            )}
            {info.status === 'waiting' ? (
              <div className="button-row">
                <button
                  type="button"
                  className="button button-primary"
                  disabled={busy}
                  onClick={() => void act('send')}
                >
                  {t('Jetzt versenden')}
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={busy}
                  onClick={() => void act('discard')}
                >
                  {t('Verwerfen')}
                </button>
              </div>
            ) : (
              <Alert kind={info.status === 'sent' ? 'success' : 'info'}>
                {info.status === 'sent'
                  ? t(
                      'Das Rundschreiben wird versendet. Briefe für Mitglieder ohne E-Mail findest du in HUBIplan unter Rundschreiben.',
                    )
                  : t('Stand: {status_label}.', { status_label: info.status_label })}
              </Alert>
            )}
          </>
        )}
        {error && <Alert kind="error">{error}</Alert>}
      </div>
    </main>
  )
}
