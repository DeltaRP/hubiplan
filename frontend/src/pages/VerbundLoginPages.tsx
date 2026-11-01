// Anmelden über eine gekoppelte HUBIplan-Instanz (Verbund Schritt 7).
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client.ts'
import { leaveTo, ssoApi } from '../api/peering.ts'
import type { SsoFinished, SsoInstance } from '../api/peering.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { errorMessage, useLoad } from '../components/forms.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'
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

/** Auf der Anmeldeseite: Anmelden mit dem Zugang einer gekoppelten Instanz. */
export function RemoteLoginChoices({ target }: { target: string }) {
  const [choices, setChoices] = useState<SsoInstance[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    ssoApi
      .choices()
      .then(setChoices)
      .catch(() => setChoices([]))
  }, [])
  if (choices.length === 0) return null
  async function go(idp: string) {
    setError(null)
    try {
      leaveTo.go((await ssoApi.start(idp, 'login', target)).url)
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  return (
    <div className="remote-login">
      <p className="muted small">{t('Oder mit deinem Zugang einer gekoppelten Instanz:')}</p>
      {choices.map((c) => (
        <button
          key={c.instance_id}
          type="button"
          className="button button-block"
          onClick={() => void go(c.instance_id)}
        >
          {t('Anmelden mit')} {c.base_url.replace(/^https:\/\//, '')}
        </button>
      ))}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

/** /verbund/start?idp=…: Wechsel von der Heimat-Instanz hierher (aus der Einheitenauswahl). */
export function VerbundStartPage() {
  const { search } = useLocation()
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    const idp = new URLSearchParams(search).get('idp') ?? ''
    ssoApi
      .start(idp, 'login', '/')
      .then((r) => leaveTo.go(r.url))
      .catch((e) => setError(errorMessage(e)))
  }, [search])
  return (
    <Frame title={t('Anmelden')}>
      {error ? (
        <>
          <Alert kind="error">{error}</Alert>
          <p className="small">
            <Link to="/anmelden">{t('Mit Passwort anmelden')}</Link>
          </p>
        </>
      ) : (
        <p className="muted">{t('Weiter zur Anmeldung …')}</p>
      )}
    </Frame>
  )
}

/** /verbund/anmelden?rp=…&state=…: Heimat-Instanz bestätigt die Anmeldung bei der anderen. */
export function VerbundConfirmPage() {
  const { search } = useLocation()
  const { user } = useAuth()
  const params = new URLSearchParams(search)
  const rp = params.get('rp') ?? ''
  const state = params.get('state') ?? ''
  const purpose = params.get('purpose') === 'link' ? 'link' : 'login'
  const { data, error } = useLoad(() => ssoApi.describe(rp), [rp])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Anmeldung hier zu alt: Passwort (und Code) bestätigen, bevor es weitergeht
  const [reauth, setReauth] = useState<{ needsCode: boolean } | null>(null)
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const auto = useRef(false)

  async function confirm() {
    setErr(null)
    setBusy(true)
    try {
      const extra = reauth ? { password, ...(reauth.needsCode ? { code } : {}) } : undefined
      leaveTo.go((await ssoApi.issue(rp, state, purpose, extra)).url)
    } catch (e) {
      const body =
        e instanceof ApiError ? (e.body as { reauth?: boolean; needs_code?: boolean }) : null
      if (e instanceof ApiError && e.status === 409 && body?.reauth) {
        setReauth({ needsCode: Boolean(body.needs_code) })
      } else {
        setErr(errorMessage(e))
      }
      setBusy(false)
    }
  }

  // Schon verknüpft (Wechsel aus der Einheitenauswahl): ohne weitere Rückfrage
  useEffect(() => {
    if (data?.linked && purpose === 'login' && !auto.current) {
      auto.current = true
      void confirm()
    }
  })

  const host = data?.base_url.replace(/^https:\/\//, '') ?? ''
  return (
    <Frame title={purpose === 'link' ? t('Zugang verknüpfen') : t('Anmelden')}>
      {error && <Alert kind="error">{error}</Alert>}
      {data && (
        <>
          <p>
            {purpose === 'link' ? (
              <>
                <strong>{host}</strong> {t('möchte deinen Zugang')} <strong>{user?.email}</strong>{' '}
                {t(
                  'mit deinem Konto dort verknüpfen. Danach kannst du dich dort mit diesem Zugang anmelden.',
                )}
              </>
            ) : (
              <>
                {t('Bei')} <strong>{host}</strong> als <strong>{user?.email}</strong> anmelden?
              </>
            )}
          </p>
          <p className="muted small">
            {t(
              'Es geht nur die Bestätigung deiner Anmeldung dorthin (Name, E-Mail-Adresse, wie und wann du dich angemeldet hast), verschlüsselt und unterschrieben. Rechte vergibt {host}  selbst. Fingerabdruck {host2}:',
              { host, host2: host },
            )}{' '}
            <code>{data.fingerprint}</code>
          </p>
          {reauth && (
            <>
              <Alert kind="info">
                {t('Zur Sicherheit bitte hier dein Passwort')}
                {reauth.needsCode && t(' und den Code aus deiner Authenticator-App')}{' '}
                {t('bestätigen.')}
              </Alert>
              <label className="field">
                <span>{t('Passwort')}</span>
                <input
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              {reauth.needsCode && (
                <label className="field">
                  <span>{t('Code')}</span>
                  <input
                    value={code}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    onChange={(e) => setCode(e.target.value)}
                  />
                </label>
              )}
            </>
          )}
          {err && <Alert kind="error">{err}</Alert>}
          <button
            type="button"
            className="button button-primary button-block"
            disabled={busy || (reauth !== null && (!password || (reauth.needsCode && !code)))}
            onClick={() => void confirm()}
          >
            {purpose === 'link' ? t('Verknüpfen') : t('Bei {host} anmelden', { host })}
          </button>
          <p className="small">
            <Link to="/">{t('Abbrechen')}</Link>
          </p>
        </>
      )}
    </Frame>
  )
}

/** /verbund/angemeldet#…: Bestätigung von der Heimat-Instanz einlösen. */
export function VerbundFinishPage() {
  const { setUser } = useAuth()
  const navigate = useNavigate()
  const { hash } = useLocation()
  const [error, setError] = useState<string | null>(null)
  const [needsCode, setNeedsCode] = useState(false)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const done = useRef(false)

  function finished(r: SsoFinished) {
    if (r.mfa_required) {
      setNeedsCode(true)
      return
    }
    if (r.user) setUser(r.user)
    navigate(r.next || '/', {
      replace: true,
      state: r.purpose === 'link' ? { linked: true } : undefined,
    })
  }

  useEffect(() => {
    if (done.current) return
    done.current = true
    const token = hash.replace(/^#/, '')
    // Bestätigung nicht im Verlauf stehen lassen
    window.history.replaceState(null, '', window.location.pathname)
    ssoApi
      .finish(token)
      .then(finished)
      .catch((e) => setError(errorMessage(e)))
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [hash])

  async function sendCode() {
    setBusy(true)
    setError(null)
    try {
      finished(await ssoApi.finishCode(code))
    } catch (e) {
      setNeedsCode(false)
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Frame title={t('Anmelden')}>
      {error ? (
        <>
          <Alert kind="error">{error}</Alert>
          <p className="small">
            <Link to="/anmelden">{t('Zur Anmeldung')}</Link>
          </p>
        </>
      ) : needsCode ? (
        <>
          <p>
            {t(
              'Dein Konto hat hier Vorstands-, Kassen- oder Prüferrechte. Bitte zusätzlich den Code aus deiner Authenticator-App für diese Instanz eingeben.',
            )}
          </p>
          <label className="field">
            <span>{t('Code')}</span>
            <input
              value={code}
              inputMode="numeric"
              autoComplete="one-time-code"
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="button button-primary button-block"
            disabled={busy || !code.trim()}
            onClick={() => void sendCode()}
          >
            {t('Anmelden')}
          </button>
        </>
      ) : (
        <p className="muted">{t('Anmeldung wird geprüft …')}</p>
      )}
    </Frame>
  )
}
