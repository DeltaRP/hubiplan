// Bei der Nextcloud des Vereins mit dem HUBIplan-Konto anmelden (OpenID Connect).
// Die Nextcloud schickt den Browser hierher; ist man angemeldet und darf hinein, geht es
// ohne Rückfrage mit einem Einmal-Code zurück.
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ApiError } from '../api/client.ts'
import { oidcApi } from '../api/nextcloud.ts'
import type { NextcloudDenied } from '../api/nextcloud.ts'
import { leaveTo } from '../api/peering.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { errorMessage } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'
import { t } from '../i18n/index.ts'

export function NextcloudLoginPage() {
  const { search } = useLocation()
  const { user } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [back, setBack] = useState('')
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const params = Object.fromEntries(new URLSearchParams(search).entries())
    oidcApi
      .authorize(params)
      .then((res) => leaveTo.go(res.redirect))
      .catch((e: unknown) => {
        const body = e instanceof ApiError ? (e.body as NextcloudDenied | null) : null
        // Fehler im Aufruf selbst meldet die Nextcloud (eingetragene Rückleitung)
        if (body?.redirect) {
          leaveTo.go(body.redirect)
          return
        }
        setBack(body?.back ?? '')
        setError(errorMessage(e))
      })
  }, [search])

  return (
    <main className="login-page">
      <div className="card login-card">
        <div className="login-logo">
          <Logo />
        </div>
        <h1>{t('Bei der Nextcloud anmelden')}</h1>
        {error ? (
          <>
            <Alert kind="error">{error}</Alert>
            <p className="muted small">
              {t('Angemeldet bei HUBIplan als')} <strong>{user?.email}</strong>
            </p>
            {back && (
              <p>
                <a className="button" href={back}>
                  {t('Zurück zur Nextcloud')}
                </a>
              </p>
            )}
          </>
        ) : (
          <p aria-live="polite">{t('Einen Moment, du wirst angemeldet …')}</p>
        )}
      </div>
    </main>
  )
}
