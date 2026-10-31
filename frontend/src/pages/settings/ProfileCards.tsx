// Mein Konto: Name, Passwort und Anmelde-E-Mail selbst ändern.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { accountApi } from '../../api/account.ts'
import type { AccountData } from '../../api/account.ts'
import { useAuth } from '../../auth/AuthContext.tsx'
import { useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Field, SaveStatus } from '../../components/ui.tsx'

/** Mein Konto › Profil: Name */
export function NameSection() {
  const { data, error, setData } = useLoad(() => accountApi.get(), [])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return <NameCard data={data} onSaved={setData} />
}

/** Mein Konto › Anmeldung & Sicherheit: Anmelde-E-Mail und Passwort */
export function LoginSections() {
  const { data, error, setData } = useLoad(() => accountApi.get(), [])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return (
    <>
      <EmailCard data={data} onSaved={setData} />
      <PasswordCard key={`p-${data.has_password}`} data={data} onSaved={setData} />
    </>
  )
}

function NameCard({ data, onSaved }: { data: AccountData; onSaved: (d: AccountData) => void }) {
  const { user, setUser } = useAuth()
  const form = useForm({ first_name: data.first_name, last_name: data.last_name })
  // Der Name speichert automatisch
  const auto = useAutoSave(
    form,
    (changes) => accountApi.updateName({ ...form.values, ...changes }),
    {
      onSaved: (result) => {
        const saved = result as AccountData
        onSaved(saved)
        if (user) setUser({ ...user, display: `${saved.first_name} ${saved.last_name}`.trim() })
      },
    },
  )
  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      <h2>Name</h2>
      <SaveStatus auto={auto} />
      <div className="grid-2">
        <Field
          label="Vorname"
          autoComplete="given-name"
          value={form.values.first_name}
          error={form.errors.first_name}
          onChange={(e) => form.set('first_name', e.target.value)}
        />
        <Field
          label="Nachname"
          autoComplete="family-name"
          value={form.values.last_name}
          error={form.errors.last_name}
          onChange={(e) => form.set('last_name', e.target.value)}
        />
      </div>
    </form>
  )
}

function EmailCard({ data, onSaved }: { data: AccountData; onSaved: (d: AccountData) => void }) {
  const form = useForm({ email: '', password: '' })
  const [open, setOpen] = useState(false)

  async function save(e: FormEvent) {
    e.preventDefault()
    const saved = (await form.submit(
      () =>
        accountApi.changeEmail({
          email: form.values.email.trim(),
          ...(data.has_password ? { password: form.values.password } : {}),
        }),
      'Wir haben einen Bestätigungslink an die neue Adresse geschickt.',
    )) as AccountData | undefined
    if (saved) {
      onSaved(saved)
      form.setValues({ email: '', password: '' })
      setOpen(false)
    }
  }

  async function cancel() {
    await accountApi.cancelEmail()
    onSaved({ ...data, pending_email: null })
  }

  return (
    <div className="card card-wide">
      <h2>Anmelde-E-Mail</h2>
      <p>
        Du meldest dich an mit <strong>{data.email}</strong>.
      </p>
      {data.pending_email && (
        <Alert kind="info">
          Neue Adresse {data.pending_email} wartet auf Bestätigung. Bitte den Link in der Mail an
          diese Adresse öffnen.{' '}
          <button type="button" className="link-button" onClick={() => void cancel()}>
            Verwerfen
          </button>
        </Alert>
      )}
      {form.message?.kind === 'success' && <Alert kind="success">{form.message.text}</Alert>}
      {open ? (
        <form onSubmit={save}>
          <div className="grid-2">
            <Field
              label="Neue E-Mail-Adresse"
              type="email"
              required
              autoComplete="email"
              value={form.values.email}
              error={form.errors.email}
              onChange={(e) => form.set('email', e.target.value)}
            />
            {data.has_password && (
              <Field
                label="Dein Passwort zur Bestätigung"
                type="password"
                required
                autoComplete="current-password"
                value={form.values.password}
                error={form.errors.password}
                onChange={(e) => form.set('password', e.target.value)}
              />
            )}
          </div>
          {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
          <div className="button-row">
            <button type="submit" className="button button-primary" disabled={form.busy}>
              Bestätigungslink senden
            </button>
            <button type="button" className="button button-ghost" onClick={() => setOpen(false)}>
              Abbrechen
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="button button-ghost" onClick={() => setOpen(true)}>
          Anmelde-E-Mail ändern
        </button>
      )}
      <p className="muted small">
        Die Kontaktdaten, die dein Verein über dich führt, änderst du unter „Meine Daten“.
      </p>
    </div>
  )
}

function PasswordCard({ data, onSaved }: { data: AccountData; onSaved: (d: AccountData) => void }) {
  const { user, setUser } = useAuth()
  const form = useForm({ current_password: '', new_password: '', repeat: '' })
  async function save(e: FormEvent) {
    e.preventDefault()
    if (form.values.new_password !== form.values.repeat) {
      form.setMessage({ kind: 'error', text: 'Die beiden neuen Passwörter sind verschieden.' })
      return
    }
    const saved = (await form.submit(
      () =>
        accountApi.changePassword({
          ...(data.has_password ? { current_password: form.values.current_password } : {}),
          new_password: form.values.new_password,
        }),
      data.has_password ? 'Passwort geändert.' : 'Passwort festgelegt.',
    )) as AccountData | undefined
    if (saved) {
      form.setValues({ current_password: '', new_password: '', repeat: '' })
      onSaved(saved)
      if (user?.must_change_password) setUser({ ...user, must_change_password: false })
    }
  }
  return (
    <form className="card card-wide" onSubmit={save}>
      <h2>{data.has_password ? 'Passwort ändern' : 'Passwort festlegen'}</h2>
      {user?.must_change_password && (
        <Alert kind="info">
          Du bist mit einem Startpasswort angemeldet. Bitte lege zuerst ein eigenes Passwort fest;
          das Startpasswort gilt nur wenige Tage.
        </Alert>
      )}
      {!data.has_password && (
        <p className="muted small">
          Du meldest dich bisher per Anmeldelink an. Mit einem Passwort geht es auch ohne Link.
        </p>
      )}
      <div className="grid-3">
        {data.has_password && (
          <Field
            label="Bisheriges Passwort"
            type="password"
            required
            autoComplete="current-password"
            value={form.values.current_password}
            error={form.errors.current_password}
            onChange={(e) => form.set('current_password', e.target.value)}
          />
        )}
        <Field
          label="Neues Passwort"
          type="password"
          required
          autoComplete="new-password"
          value={form.values.new_password}
          error={form.errors.new_password}
          hint="mindestens 8 Zeichen, nicht zu einfach"
          onChange={(e) => form.set('new_password', e.target.value)}
        />
        <Field
          label="Neues Passwort wiederholen"
          type="password"
          required
          autoComplete="new-password"
          value={form.values.repeat}
          onChange={(e) => form.set('repeat', e.target.value)}
        />
      </div>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      <button type="submit" className="button button-primary" disabled={form.busy}>
        {data.has_password ? 'Passwort ändern' : 'Passwort festlegen'}
      </button>
    </form>
  )
}
