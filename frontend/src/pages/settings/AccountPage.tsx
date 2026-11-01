import { Link } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import * as api from '../../api/auth.ts'
import type { ChangeResult, TotpState } from '../../api/auth.ts'
import { LoginSections, NameSection } from './ProfileCards.tsx'
import { LearningCard } from '../../learning/LearningCard.tsx'
import { LanguageCard } from '../../i18n/LanguageControls.tsx'
import { AppDevicesCard } from './AppDevicesCard.tsx'
import { RemoteLoginCard } from './RemoteLoginCard.tsx'
import { SignatureCard } from './SignatureCard.tsx'
import { t } from '../../i18n/index.ts'

// Mein Konto: persönliche Einstellungen, unabhängig von der gewählten Organisation.
// Aufgeteilt in Unterpunkte (accountNav.ts), die in der Seitenleiste stehen.

/** Mein Konto › Profil */
export function AccountPage() {
  return (
    <section>
      <h1>{t('Profil')}</h1>
      <div className="stack">
        <NameSection />
        <LanguageCard />
        <LearningCard />
      </div>
    </section>
  )
}

/** Mein Konto › Anmeldung & Sicherheit */
export function AccountLoginPage() {
  return (
    <section>
      <h1>{t('Anmeldung & Sicherheit')}</h1>
      <div className="stack">
        <LoginSections />
        <TwoFactorCard />
      </div>
    </section>
  )
}

/** Mein Konto › App & andere Instanzen */
export function AccountAppPage() {
  return (
    <section>
      <h1>{t('App & andere Instanzen')}</h1>
      <div className="stack">
        <AppDevicesCard />
        <RemoteLoginCard />
      </div>
    </section>
  )
}

/** Mein Konto › Briefvorlage & Unterschrift */
export function AccountTemplatesPage() {
  return (
    <section>
      <h1>{t('Briefvorlage & Unterschrift')}</h1>
      <div className="stack">
        <div className="card">
          <h2>{t('Briefvorlage')}</h2>
          <p className="muted small">
            {t(
              'Als Vorstandsmitglied oder mit einer Rolle in einer Untereinheit erstellst du dir eine Word-Vorlage mit dem Briefbogen deiner Einheit, deiner Funktion und deinem Kontaktweg.',
            )}
          </p>
          <p>
            <Link to="/briefvorlage">{t('Briefvorlage erstellen')}</Link>
          </p>
        </div>
        <SignatureCard />
      </div>
    </section>
  )
}

function TwoFactorCard() {
  const [totp, setTotp] = useState<TotpState | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Aktion, die nach erneuter Passwortbestätigung wiederholt wird
  const [pending, setPending] = useState<(() => Promise<ChangeResult>) | null>(null)

  const load = useCallback(async () => {
    setTotp(await api.getTotp())
  }, [])

  // Ladefehler ist kein „nicht eingerichtet“ (Audit 29.10. FE-F01)
  const [loadFailed, setLoadFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    api
      .getTotp()
      .then((state) => {
        if (!active) return
        setLoadFailed(false)
        setTotp(state)
      })
      .catch(() => active && setLoadFailed(true))
    return () => {
      active = false
    }
  }, [attempt])

  const [busy, setBusy] = useState(false)
  const [codesFailed, setCodesFailed] = useState(false)

  // Netzfehler sichtbar machen und danach den tatsächlichen Stand neu laden: Die Änderung
  // kann auf dem Server schon durch sein (Gesamtaudit 30.10., WEB-F01).
  async function run(action: () => Promise<ChangeResult>, onSuccess: () => Promise<void>) {
    setError(null)
    setMessage(null)
    setBusy(true)
    try {
      const result = await action()
      if (result.kind === 'reauthenticate') {
        setPending(() => action)
      } else if (result.kind === 'error') {
        setError(result.message)
      } else {
        await onSuccess()
      }
    } catch {
      setError(
        t('Keine Verbindung zum Server. Ob die Änderung angekommen ist, zeigt der Stand unten; ') +
          t('bitte prüfen und ggf. wiederholen.'),
      )
      setAttempt((n) => n + 1)
    } finally {
      setBusy(false)
    }
  }

  async function loadRecoveryCodes() {
    try {
      setRecoveryCodes(await api.getRecoveryCodes())
      setCodesFailed(false)
    } catch {
      setCodesFailed(true)
    }
  }

  const afterActivate = async () => {
    setCode('')
    setPassword('')
    setMessage(t('Zwei-Faktor-Anmeldung ist aktiv.'))
    await loadRecoveryCodes()
    await load()
  }
  const afterDeactivate = async () => {
    setRecoveryCodes([])
    setCodesFailed(false)
    setMessage(t('Zwei-Faktor-Anmeldung wurde ausgeschaltet.'))
    await load()
  }

  // Passwort und Code werden zusammen abgefragt: allauth verlangt für die
  // Aktivierung eine frische Passwortbestätigung, und ein einmal geprüfter
  // TOTP-Code lässt sich nicht noch einmal verwenden.
  function activate(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      const reauth = await api.reauthenticate(password)
      if (reauth.kind !== 'ok') return reauth
      return api.activateTotp(code.trim())
    }, afterActivate)
  }

  if (pending) {
    return (
      <ReauthCard
        onCancel={() => setPending(null)}
        onConfirmed={async () => {
          const action = pending
          setPending(null)
          await run(action, totp?.active ? afterDeactivate : afterActivate)
        }}
      />
    )
  }

  return (
    <div className="card">
      <h2>{t('Zwei-Faktor-Anmeldung')}</h2>
      {message && <p className="alert alert-success">{message}</p>}
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}

      {totp === null && !loadFailed && <p className="muted">{t('Lädt …')}</p>}
      {totp === null && loadFailed && (
        <div className="alert alert-error" role="alert">
          {t('Der Stand der Zwei-Faktor-Anmeldung konnte nicht geladen werden.')}{' '}
          <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>
            {t('Erneut laden')}
          </button>
        </div>
      )}

      {totp?.active && (
        <>
          <p>
            {t(
              'Bei der Anmeldung wird zusätzlich ein Code aus deiner Authenticator-App abgefragt.',
            )}
          </p>
          {codesFailed && (
            <div className="alert alert-error" role="alert">
              {t('Die Wiederherstellungscodes konnten nicht geladen werden.')}{' '}
              <button type="button" className="button" onClick={() => void loadRecoveryCodes()}>
                {t('Codes erneut laden')}
              </button>
            </div>
          )}
          {recoveryCodes.length > 0 && (
            <div className="recovery-codes">
              <p>
                <strong>{t('Wiederherstellungscodes')}</strong>{' '}
                {t(
                  '– sicher aufbewahren. Jeder Code funktioniert einmal, falls du dein Handy nicht zur Hand hast.',
                )}
              </p>
              <ul>
                {recoveryCodes.map((c) => (
                  <li key={c}>
                    <code>{c}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() => void run(api.deactivateTotp, afterDeactivate)}
          >
            {t('Ausschalten')}
          </button>
        </>
      )}

      {totp && !totp.active && (
        <form onSubmit={activate}>
          <p>
            {t(
              'Schütze dein Konto mit einem zweiten Faktor. Scanne den QR-Code mit einer Authenticator-App (z. B. FreeOTP, Aegis, Google Authenticator) und gib den angezeigten Code ein.',
            )}
          </p>
          <div className="totp-setup">
            <QRCodeSVG value={totp.totpUrl} size={168} marginSize={2} />
            <p className="muted">
              {t('Manuell:')} <code>{totp.secret}</code>
            </p>
          </div>
          <label className="field">
            <span>{t('Code aus der App')}</span>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          <label className="field">
            <span>{t('Dein Passwort zur Bestätigung')}</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button type="submit" className="button button-primary" disabled={busy}>
            {t('Aktivieren')}
          </button>
        </form>
      )}
    </div>
  )
}

function ReauthCard({
  onConfirmed,
  onCancel,
}: {
  onConfirmed: () => Promise<void>
  onCancel: () => void
}) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result = await api.reauthenticate(password)
      if (result.kind === 'ok') await onConfirmed()
      else if (result.kind === 'error') setError(result.message)
    } catch {
      setError(t('Keine Verbindung zum Server. Bitte erneut versuchen.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>{t('Passwort bestätigen')}</h2>
      <p className="muted">{t('Für diese Änderung brauchen wir noch einmal dein Passwort.')}</p>
      <label className="field">
        <span>{t('Passwort')}</span>
        <input
          type="password"
          autoComplete="current-password"
          autoFocus
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
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={busy}>
          {t('Bestätigen')}
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          {t('Abbrechen')}
        </button>
      </div>
    </form>
  )
}
