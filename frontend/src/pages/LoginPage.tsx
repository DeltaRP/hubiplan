import { LanguageSwitch } from '../i18n/LanguageControls.tsx'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import * as api from '../api/auth.ts'
import type { LoginResult } from '../api/auth.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { loginTarget, rememberedTarget } from '../auth/loginTarget.ts'
import { Logo } from '../components/Logo.tsx'
import { RemoteLoginChoices } from './VerbundLoginPages.tsx'
import { t } from '../i18n/index.ts'

type Step = 'password' | 'mfa'

export function LoginPage() {
  const { user, setUser } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  // Nach der Anmeldung zur ursprünglich aufgerufenen Seite (sonst Startseite)
  const target = loginTarget(location.state)

  const [step, setStep] = useState<Step>('password')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={target} replace />

  function handle(result: LoginResult) {
    if (result.kind === 'ok') {
      setUser(result.user)
      rememberedTarget(true)
      navigate(target, { replace: true })
    } else if (result.kind === 'mfa') {
      setStep('mfa')
      setError(null)
    } else {
      setError(result.message)
    }
  }

  async function submit(e: FormEvent, action: () => Promise<LoginResult>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      handle(await action())
    } catch {
      setError(t('Der Server ist nicht erreichbar.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <div className="card login-card">
        <div className="login-logo">
          <Logo />
        </div>

        {step === 'password' ? (
          <form onSubmit={(e) => submit(e, () => api.login(email.trim(), password))}>
            <h1>{t('Anmelden')}</h1>
            <label className="field">
              <span>{t('E-Mail-Adresse')}</span>
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field">
              <span>{t('Passwort')}</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p className="alert alert-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="button button-primary button-block" disabled={busy}>
              {busy ? t('Anmelden …') : t('Anmelden')}
            </button>
            <p className="small">
              <Link to="/passwort-vergessen" state={location.state}>
                {t('Passwort vergessen?')}
              </Link>{' '}
              ·{' '}
              <Link to="/anmelden/link" state={location.state}>
                {t('Ohne Passwort per Link anmelden')}
              </Link>
            </p>
            <RemoteLoginChoices target={target} />
          </form>
        ) : (
          <form onSubmit={(e) => submit(e, () => api.authenticateMfa(code.trim()))}>
            <h1>{t('Bestätigungscode')}</h1>
            <p className="muted">
              {t(
                'Gib den 6-stelligen Code aus deiner Authenticator-App ein – oder einen deiner Wiederherstellungscodes.',
              )}
            </p>
            <label className="field">
              <span>{t('Code')}</span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            {error && (
              <p className="alert alert-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="button button-primary button-block" disabled={busy}>
              {busy ? t('Prüfe …') : t('Bestätigen')}
            </button>
            <button
              type="button"
              className="button button-ghost button-block"
              onClick={() => {
                setStep('password')
                setCode('')
                setError(null)
              }}
            >
              {t('Zurück')}
            </button>
          </form>
        )}
      </div>
      <LanguageSwitch />
    </main>
  )
}
