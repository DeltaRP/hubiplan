// Anmeldung ohne Passwort: Link anfordern und einlösen.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { confirmEmail } from '../api/account.ts'
import { redeemLoginLink, requestLoginLink } from '../api/portal.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { rememberedTarget, rememberTarget } from '../auth/loginTarget.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert, Field } from '../components/ui.tsx'
import { t } from '../i18n/index.ts'

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="login-page">
      <div className="card login-card">
        <div className="login-logo">
          <Logo />
        </div>
        <h1>{title}</h1>
        {children}
      </div>
    </main>
  )
}

/** Mitglieder fordern einen Anmeldelink per E-Mail an. */
export function LoginLinkRequestPage() {
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      // Nach dem Einlösen zur ursprünglich aufgerufenen Seite (UI-Audit NMF-09)
      rememberTarget(location.state)
      setDone(await requestLoginLink(email.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Der Server ist nicht erreichbar.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Frame title={t('Anmeldelink anfordern')}>
      {done ? (
        <Alert kind="success">{done}</Alert>
      ) : (
        <form onSubmit={submit}>
          <p className="muted small">
            {t(
              'Für Mitglieder mit Zugang: Wir schicken dir einen Link, mit dem du dich ohne Passwort anmeldest. Der Link gilt 7 Tage und nur einmal.',
            )}
          </p>
          <Field
            label={t('E-Mail-Adresse')}
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          {error && <Alert kind="error">{error}</Alert>}
          <button type="submit" className="button button-primary button-block" disabled={busy}>
            {t('Link senden')}
          </button>
        </form>
      )}
      <p className="small">
        <Link to="/anmelden" state={location.state}>
          {t('Zur Anmeldung mit Passwort')}
        </Link>
      </p>
    </Frame>
  )
}

/** Link aus der E-Mail: erst nach Klick einlösen (Mailprogramme öffnen Links vorab). */
export function LoginLinkRedeemPage() {
  const { token = '' } = useParams()
  const { setUser } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function redeem() {
    setBusy(true)
    setError(null)
    try {
      const result = await redeemLoginLink(token)
      if (result.ok) {
        setUser(result.user)
        navigate(rememberedTarget(true), { replace: true })
      } else {
        setError(result.message)
      }
    } catch {
      setError(t('Der Server ist nicht erreichbar.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Frame title={t('Anmelden')}>
      <p className="muted small">{t('Mit diesem Link meldest du dich ohne Passwort an.')}</p>
      {error && <Alert kind="error">{error}</Alert>}
      <button
        type="button"
        className="button button-primary button-block"
        disabled={busy}
        onClick={() => void redeem()}
      >
        {busy ? t('Anmelden …') : t('Jetzt anmelden')}
      </button>
      <p className="small">
        <Link to="/anmelden/link">{t('Neuen Link anfordern')}</Link> ·{' '}
        <Link to="/anmelden">{t('Mit Passwort anmelden')}</Link>
      </p>
    </Frame>
  )
}

/** Link aus der Mail „neue Anmelde-E-Mail bestätigen“. */
export function EmailConfirmPage() {
  const { token = '' } = useParams()
  const { user, setUser } = useAuth()
  const [result, setResult] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function confirm() {
    setBusy(true)
    try {
      const r = await confirmEmail(token)
      if (r.ok) {
        setResult({
          kind: 'success',
          text: t('Bestätigt. Du meldest dich jetzt mit {email} an.', { email: r.email }),
        })
        if (user) setUser({ ...user, email: r.email })
      } else {
        setResult({ kind: 'error', text: r.message })
      }
    } catch {
      setResult({ kind: 'error', text: t('Der Server ist nicht erreichbar.') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Frame title={t('Neue E-Mail-Adresse')}>
      {result ? (
        <Alert kind={result.kind}>{result.text}</Alert>
      ) : (
        <>
          <p className="muted small">
            {t('Bitte bestätige, dass dies deine neue Anmelde-E-Mail ist.')}
          </p>
          <button
            type="button"
            className="button button-primary button-block"
            disabled={busy}
            onClick={() => void confirm()}
          >
            {t('Bestätigen')}
          </button>
        </>
      )}
      <p className="small">
        <Link to="/">{t('Zur Startseite')}</Link>
      </p>
    </Frame>
  )
}
