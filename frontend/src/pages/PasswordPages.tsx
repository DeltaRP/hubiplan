import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { rememberedTarget, rememberTarget } from '../auth/loginTarget.ts'
import { request } from '../api/client.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert, Field } from '../components/ui.tsx'

const BASE = '/_allauth/browser/v1/auth/password'

function messages(body: unknown): string {
  const errors = (body as { errors?: { message: string }[] }).errors
  return errors?.map((e) => e.message).join(' ') || 'Das hat nicht geklappt.'
}

/** „Passwort vergessen“: Link per E-Mail anfordern. */
export function PasswordRequestPage() {
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      // Nach dem neuen Passwort zur ursprünglich aufgerufenen Seite (UI-Audit NMF-09)
      rememberTarget(location.state)
      const { status, body } = await request('POST', `${BASE}/request`, { email: email.trim() })
      if (status === 200) setSent(true)
      else setError(status === 429 ? 'Zu viele Versuche. Bitte später erneut.' : messages(body))
    } catch {
      setError('Der Server ist nicht erreichbar.')
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
        <h1>Passwort vergessen</h1>
        {sent ? (
          <Alert kind="success">
            Falls ein Konto mit dieser E-Mail-Adresse besteht, haben wir einen Link zum Zurücksetzen
            geschickt.
          </Alert>
        ) : (
          <form onSubmit={submit}>
            <p className="muted small">
              Wir schicken dir einen Link, mit dem du ein neues Passwort festlegst.
            </p>
            <Field
              label="E-Mail-Adresse"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {error && <Alert kind="error">{error}</Alert>}
            <button type="submit" className="button button-primary button-block" disabled={busy}>
              Link anfordern
            </button>
          </form>
        )}
        <p className="small">
          <Link to="/anmelden" state={location.state}>
            Zur Anmeldung
          </Link>
        </p>
      </div>
    </main>
  )
}

/** Neues Passwort setzen (Link aus „Passwort vergessen“ oder der Einladung). */
export function PasswordResetPage() {
  const key = useParams().key ?? ''
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (password !== repeat) {
      setError('Die Passwörter stimmen nicht überein.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const { status, body } = await request('POST', `${BASE}/reset`, { key, password })
      // 200 = angemeldet, 401 = Passwort gesetzt, Anmeldung (ggf. mit 2FA) folgt
      if (status === 200 || status === 401) setDone(true)
      else setError(messages(body))
    } catch {
      setError('Der Server ist nicht erreichbar.')
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
        <h1>Neues Passwort</h1>
        {done ? (
          <>
            <Alert kind="success">Dein Passwort ist gesetzt.</Alert>
            <Link
              to="/anmelden"
              state={{ from: rememberedTarget() }}
              className="button button-primary button-block"
            >
              Zur Anmeldung
            </Link>
          </>
        ) : (
          <form onSubmit={submit}>
            <Field
              label="Neues Passwort"
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Field
              label="Passwort wiederholen"
              type="password"
              required
              autoComplete="new-password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
            {error && <Alert kind="error">{error}</Alert>}
            <button type="submit" className="button button-primary button-block" disabled={busy}>
              Passwort speichern
            </button>
          </form>
        )}
      </div>
    </main>
  )
}
