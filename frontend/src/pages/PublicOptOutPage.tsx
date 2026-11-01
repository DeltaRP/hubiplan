import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { publicOptOutApi } from '../api/circulars.ts'
import type { PublicOptOut } from '../api/circulars.ts'
import { ApiError } from '../api/client.ts'
import { errorMessage } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'
import { usePublicImprint } from '../components/publicImprint.ts'
import { t } from '../i18n/index.ts'

/** Abmeldelink aus einem Rundschreiben (ohne Anmeldung). */
export function PublicOptOutPage() {
  const token = useParams().token ?? ''
  const [info, setInfo] = useState<PublicOptOut | null>(null)
  const [invalid, setInvalid] = useState(false)
  // Netz- oder Serverfehler: Link nicht für ungültig erklären, sondern erneut versuchen lassen
  const [unavailable, setUnavailable] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  usePublicImprint(info?.imprint_key, info?.club)

  useEffect(() => {
    let alive = true
    publicOptOutApi
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

  async function change(value: boolean) {
    setBusy(true)
    setError(null)
    try {
      setInfo(await publicOptOutApi.set(token, value))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <div className="card public-photo">
        <div className="login-logo">
          <Logo name={info?.club ?? 'HUBIplan'} logoUrl={null} />
        </div>
        <h1>{t('Informationen per E-Mail')}</h1>
        {invalid && <Alert kind="error">{t('Dieser Link ist ungültig.')}</Alert>}
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
              {t('Hallo {first_name},', { first_name: info.first_name })}{' '}
              {info.info_opt_out
                ? t('du bekommst keine Informationen von {club} mehr per E-Mail.', {
                    club: info.club,
                  })
                : t('hier kannst du Informationen von {club} per E-Mail abbestellen.', {
                    club: info.club,
                  })}
            </p>
            <p className="muted small">
              {t(
                'Offizielle Mitteilungen wie Einladungen zur Mitgliederversammlung bekommst du weiterhin.',
              )}
            </p>
            <button
              type="button"
              className={`button ${info.info_opt_out ? 'button-ghost' : 'button-primary'}`}
              disabled={busy}
              onClick={() => void change(!info.info_opt_out)}
            >
              {info.info_opt_out ? t('Doch wieder erhalten') : t('Informationen abbestellen')}
            </button>
          </>
        )}
        {error && <Alert kind="error">{error}</Alert>}
      </div>
    </main>
  )
}
