import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { applyTheme } from '../theme/theme.ts'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const LOGIN = 'POST /_allauth/browser/v1/auth/login'
const MFA = 'POST /_allauth/browser/v1/auth/2fa/authenticate'
const loggedOut = () => ({ status: 401, body: { status: 401, data: { flows: [] } } })
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function fillLogin(password = 'geheim') {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('E-Mail-Adresse'), testUser.email)
  await user.type(screen.getByLabelText('Passwort'), password)
  await user.click(screen.getByRole('button', { name: 'Anmelden' }))
  return user
}

describe('Anmeldung', () => {
  it('leitet ohne Anmeldung auf die Login-Seite', async () => {
    fakeApi({ [SESSION]: loggedOut })
    renderApp('/mitglieder')
    expect(await screen.findByRole('heading', { name: 'Anmelden' })).toBeInTheDocument()
  })

  it('führt nach der Anmeldung zur aufgerufenen Seite zurück', async () => {
    fakeApi({ [SESSION]: loggedOut, [LOGIN]: loggedIn })
    renderApp('/gibt-es-nicht')
    await fillLogin()
    expect(await screen.findByRole('heading', { name: 'Seite nicht gefunden' })).toBeInTheDocument()
  })

  it('landet ohne aufgerufene Seite auf der Startseite', async () => {
    fakeApi({ [SESSION]: loggedOut, [LOGIN]: loggedIn })
    renderApp('/')
    await fillLogin()
    expect(await screen.findByRole('heading', { name: 'Willkommen' })).toBeInTheDocument()
  })

  it('meldet mit E-Mail und Passwort an', async () => {
    const calls = fakeApi({ [SESSION]: loggedOut, [LOGIN]: loggedIn })
    renderApp()
    await fillLogin()
    expect(await screen.findByRole('heading', { name: 'Willkommen' })).toBeInTheDocument()

    const login = calls.find((c) => c.key === LOGIN)!
    expect(JSON.parse(String(login.init?.body))).toEqual({
      email: testUser.email,
      password: 'geheim',
    })
    expect((login.init!.headers as Record<string, string>)['X-CSRFToken']).toBe('test-token')
  })

  it('zeigt Fehler bei falschem Passwort', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      [LOGIN]: () => ({
        status: 400,
        body: { status: 400, errors: [{ message: 'E-Mail oder Passwort falsch.' }] },
      }),
    })
    renderApp()
    await fillLogin('falsch')
    expect(await screen.findByRole('alert')).toHaveTextContent('E-Mail oder Passwort falsch.')
  })

  it('fragt bei aktiver 2FA den Code ab', async () => {
    const calls = fakeApi({
      [SESSION]: loggedOut,
      [LOGIN]: () => ({
        status: 401,
        body: { status: 401, data: { flows: [{ id: 'mfa_authenticate', is_pending: true }] } },
      }),
      [MFA]: loggedIn,
    })
    renderApp()
    const user = await fillLogin()

    expect(await screen.findByRole('heading', { name: 'Bestätigungscode' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Bestätigen' }))

    expect(await screen.findByRole('heading', { name: 'Willkommen' })).toBeInTheDocument()
    const mfa = calls.find((c) => c.key === MFA)!
    expect(JSON.parse(String(mfa.init?.body))).toEqual({ code: '123456' })
  })
})

describe('Layout', () => {
  it('zeigt Module je nach Organisation und Rechten', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'TV Beispielhausen' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Module' })
    expect(nav).toHaveTextContent('Mitglieder')
    expect(nav).toHaveTextContent('Einstellungen')
    expect(nav).not.toHaveTextContent('Plattform')
  })

  it('führt „Mein Konto“ oben beim Benutzer statt in den Vereinseinstellungen', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/me/account/': () => ({
        status: 200,
        body: {
          email: 'a@example.org',
          first_name: '',
          last_name: '',
          has_password: true,
          pending_email: null,
        },
      }),
      'GET /_allauth/browser/v1/account/authenticators/totp': () => ({
        status: 404,
        body: { status: 404, meta: { secret: 'ABC', totp_url: 'otpauth://totp/x' } },
      }),
    })
    renderApp('/einstellungen/organisation')
    expect(await screen.findByRole('heading', { name: 'Einstellungen' })).toBeInTheDocument()
    const tabs = screen.getByRole('heading', { name: 'Einstellungen' }).closest('section')!
    expect(tabs).not.toHaveTextContent('Mein Konto')
    const user = userEvent.setup()
    // Oben rechts ein Aufklappmenü mit den Unterseiten, nichts in der Seitenleiste
    const nav = screen.getByRole('navigation', { name: 'Module' })
    expect(nav).not.toHaveTextContent('Mein Konto')
    const button = screen.getByRole('button', { name: /Mein Konto/ })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.click(button)
    const menu = screen.getByRole('navigation', { name: 'Mein Konto' })
    for (const label of [
      'Profil',
      'Anmeldung & Sicherheit',
      'App & andere Instanzen',
      'Briefvorlage & Unterschrift',
    ]) {
      expect(within(menu).getByRole('link', { name: label })).toBeInTheDocument()
    }
    await user.click(within(menu).getByRole('link', { name: 'Profil' }))
    expect(await screen.findByRole('heading', { name: 'Profil' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Mein Konto' })).not.toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Module' })).not.toHaveTextContent('Mein Konto')
    expect(screen.queryByRole('heading', { name: 'Passwort ändern' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Mein Konto/ }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('navigation', { name: 'Mein Konto' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Mein Konto/ }))
    await user.click(screen.getByRole('link', { name: 'Anmeldung & Sicherheit' }))
    expect(
      await screen.findByRole('heading', { name: 'Anmeldung & Sicherheit' }),
    ).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Passwort ändern' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Zwei-Faktor-Anmeldung' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Name' })).not.toBeInTheDocument()
  })

  it('blendet Mitglieder ohne Recht aus', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ permissions: ['org.edit'] })],
      }),
    })
    renderApp()
    await screen.findByRole('heading', { name: 'TV Beispielhausen' })
    const nav = screen.getByRole('navigation', { name: 'Module' })
    expect(nav).not.toHaveTextContent('Mitglieder')
  })

  it('wechselt die Organisation', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg(), testOrg({ id: 8, name: 'Schachfreunde Testdorf', parent_name: null })],
      }),
    })
    renderApp()
    const user = userEvent.setup()
    const select = await screen.findByRole('combobox', { name: 'Organisation wechseln' })
    await user.selectOptions(select, '8')
    expect(
      await screen.findByRole('heading', { name: 'Schachfreunde Testdorf' }),
    ).toBeInTheDocument()
  })

  it('zeigt über den Kacheln keine Angaben zu Verein und Dachverband', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ parent_name: 'Testbund von 1855 e.V.', parent_display_name: 'Testbund' })],
      }),
    })
    renderApp()
    // Die Überschrift bleibt für Screenreader, sichtbar steht der Name nur im Kopf.
    expect(await screen.findByRole('heading', { name: 'TV Beispielhausen' })).toHaveClass('sr-only')
    expect(screen.queryByText(/Mitglied im/)).not.toBeInTheDocument()
  })

  it('zeigt im Kopf den vollen Namen, in der Auswahl den Kurznamen', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [
          testOrg({ display_name: 'TVB', short_name: 'TVB' }),
          testOrg({ id: 8, name: 'Schachfreunde Testdorf', parent_name: null }),
        ],
      }),
    })
    renderApp()
    const select = await screen.findByRole('combobox', { name: 'Organisation wechseln' })
    await userEvent.setup().selectOptions(select, '7')
    expect(await screen.findByRole('heading', { name: 'TV Beispielhausen' })).toBeInTheDocument()
    expect(screen.getByRole('banner')).toHaveTextContent('TV Beispielhausen')
    expect(screen.getByRole('banner')).not.toHaveTextContent(/TVB(?! \()/)
    expect(within(select).getByRole('option', { name: 'TVB (Verein)' })).toBeInTheDocument()
    expect(
      within(select).getByRole('option', { name: 'Schachfreunde Testdorf (Verein)' }),
    ).toBeInTheDocument()
  })

  it('ohne Organisation ein Hinweis', async () => {
    fakeApi({ [SESSION]: loggedIn })
    renderApp()
    expect(await screen.findByText(/noch keine Organisation zugeordnet/)).toBeInTheDocument()
  })
})

describe('Einstellungen', () => {
  it('aktiviert 2FA mit Code und Passwort', async () => {
    const TOTP = '/_allauth/browser/v1/account/authenticators/totp'
    let active = false
    const calls = fakeApi({
      [SESSION]: loggedIn,
      [`GET ${TOTP}`]: () =>
        active
          ? { status: 200, body: { status: 200, data: { type: 'totp' } } }
          : {
              status: 404,
              body: { status: 404, meta: { secret: 'ABC', totp_url: 'otpauth://totp/x' } },
            },
      'POST /_allauth/browser/v1/auth/reauthenticate': loggedIn,
      [`POST ${TOTP}`]: () => {
        active = true
        return { status: 200, body: { status: 200 } }
      },
      'GET /_allauth/browser/v1/account/authenticators/recovery-codes': () => ({
        status: 200,
        body: { status: 200, data: { unused_codes: ['11112222'] } },
      }),
    })
    renderApp('/mein-konto/anmeldung')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Code aus der App'), '654321')
    await user.type(screen.getByLabelText('Dein Passwort zur Bestätigung'), 'geheim')
    await user.click(screen.getByRole('button', { name: 'Aktivieren' }))

    expect(await screen.findByText('Zwei-Faktor-Anmeldung ist aktiv.')).toBeInTheDocument()
    expect(screen.getByText('11112222')).toBeInTheDocument()
    const order = calls.map((c) => c.key).filter((k) => k.startsWith('POST'))
    expect(order).toEqual(['POST /_allauth/browser/v1/auth/reauthenticate', `POST ${TOTP}`])
  })
})

describe('Theme', () => {
  it('setzt Farben als CSS-Variablen', () => {
    applyTheme({
      primary: '#c00000',
      on_primary: '#ffffff',
      accent: '#e0a526',
      on_accent: '#1d2421',
    })
    const style = document.documentElement.style
    expect(style.getPropertyValue('--color-primary')).toBe('#c00000')
    expect(style.getPropertyValue('--sidebar-bg')).toBe('#560000')
    applyTheme(null)
    expect(style.getPropertyValue('--color-primary')).toBe('')
  })
})
