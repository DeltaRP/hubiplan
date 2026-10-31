import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { cardApi } from '../api/cards.ts'
import type { PublicCard } from '../api/cards.ts'
import { formatDateTime } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'
import { usePublicImprint } from '../components/publicImprint.ts'
import { applyTheme } from '../theme/theme.ts'

/** Öffentliche Seite hinter dem QR-Code des Mitgliedsausweises (ohne Anmeldung). */
export function PublicCardPage() {
  const token = useParams().token ?? ''
  const [card, setCard] = useState<PublicCard | null>(null)
  // invalid: Ausweis unbekannt oder gesperrt; unavailable: Prüfung gerade nicht möglich
  const [state, setState] = useState<'loading' | 'ready' | 'invalid' | 'busy' | 'unavailable'>(
    'loading',
  )
  const [attempt, setAttempt] = useState(0)
  usePublicImprint(card?.imprint_key, card?.club)

  useEffect(() => {
    let alive = true
    cardApi
      .publicCard(token)
      .then(({ status, body }) => {
        if (!alive) return
        if (status === 200) {
          setCard(body)
          applyTheme(body.theme)
          setState('ready')
        } else if (status === 429) {
          setState('busy')
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

  function retry() {
    setState('loading')
    setAttempt((n) => n + 1)
  }

  const valid = card?.status === 'active'
  return (
    <main className="login-page">
      <div className="card public-card">
        <div className="login-logo">
          <Logo name={card?.club ?? 'HUBIplan'} logoUrl={card?.logo_url ?? null} />
        </div>
        {state === 'loading' && <p className="muted">Lädt …</p>}
        {state === 'busy' && (
          <Alert kind="error">Zu viele Aufrufe. Bitte später erneut versuchen.</Alert>
        )}
        {state === 'unavailable' && (
          <>
            <Alert kind="error">
              Die Mitgliedschaft kann gerade nicht geprüft werden. Bitte Verbindung prüfen und
              erneut versuchen.
            </Alert>
            <div className="button-row">
              <button type="button" className="button button-primary" onClick={retry}>
                Erneut prüfen
              </button>
            </div>
          </>
        )}
        {state === 'invalid' && (
          <Alert kind="error">
            Dieser Mitgliedsausweis ist nicht (mehr) gültig. Bitte wenden Sie sich an den Vorstand.
          </Alert>
        )}
        {card && state === 'ready' && (
          <>
            <p className="muted small public-card-kind">Mitgliedsausweis</p>
            <div className="public-card-body">
              {card.photo_url && <img src={card.photo_url} alt="" className="public-card-photo" />}
              <div>
                <h1 className="public-card-name">
                  {card.first_name} {card.last_name}
                </h1>
                <p
                  className={`public-card-status ${valid ? 'is-valid' : 'is-invalid'}`}
                  role="status"
                >
                  <span aria-hidden="true">{valid ? '✓' : '✕'}</span> {card.status_label}
                </p>
                <dl className="public-card-facts">
                  {card.member_type && (
                    <>
                      <dt>Mitgliedsart</dt>
                      <dd>{card.member_type}</dd>
                    </>
                  )}
                  <dt>{card.club_label || 'Mitglied in'}</dt>
                  <dd>{card.club}</dd>
                  {card.departments.length > 0 && (
                    <>
                      <dt>{card.department_label}</dt>
                      <dd>{card.departments.join(', ')}</dd>
                    </>
                  )}
                  {card.federation && (
                    <>
                      <dt>{card.federation_label || 'Verband'}</dt>
                      <dd>{card.federation}</dd>
                    </>
                  )}
                </dl>
              </div>
            </div>
            <p className="muted small">Stand: {formatDateTime(card.checked_at)}</p>
          </>
        )}
      </div>
    </main>
  )
}
