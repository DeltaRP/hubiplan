import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedOut = () => ({ status: 401, body: { status: 401, data: { flows: [] } } })
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const theme = testOrg().theme

function renderApp(path: string) {
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

const portalEntry = {
  id: 5,
  club_id: 7,
  club_name: 'TV Beispielhausen',
  first_name: 'Erika',
  last_name: 'Muster',
  theme,
}

const portalDetail = {
  id: 11,
  last_name: 'Muster',
  first_name: 'Erika',
  birth_date: '1980-05-17',
  club_number: '42',
  member_type: 'aktiv',
  entry_date: '2015-01-01',
  departments: ['1. Zug'],
  contact: {
    email: 'erika@example.org',
    phone: '',
    street: 'Lindenweg 4',
    postal_code: '12345',
    city: 'Musterstadt',
    country: 'Deutschland',
  },
  status: 'active',
  contact_changes_need_approval: false,
  club: {
    name: 'TV Beispielhausen',
    street: 'Hauptstraße 1',
    postal_code: '12345',
    city: 'Musterstadt',
    email: 'vorstand@example.org',
    phone: '',
    website: '',
  },
  change_requests: [],
}

describe('Anmeldelink', () => {
  it('fordert einen Link an', async () => {
    const calls = fakeApi({
      [SESSION]: loggedOut,
      'POST /api/public/login-link/': () => ({
        status: 200,
        body: { detail: 'Wenn ein Zugang besteht, ist ein Anmeldelink unterwegs.' },
      }),
    })
    renderApp('/anmelden/link')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('E-Mail-Adresse'), 'erika@example.org')
    await user.click(screen.getByRole('button', { name: 'Link senden' }))
    expect(await screen.findByText(/Anmeldelink unterwegs/)).toBeInTheDocument()
    const call = calls.find((c) => c.key === 'POST /api/public/login-link/')!
    expect(JSON.parse(String(call.init?.body))).toEqual({ email: 'erika@example.org' })
  })

  it('löst den Link erst nach Klick ein und zeigt den Mitgliederbereich', async () => {
    const calls = fakeApi({
      [SESSION]: loggedOut,
      'POST /api/public/login-link/abc/': () => ({ status: 200, body: testUser }),
      'GET /api/me/contexts/': () => ({
        status: 200,
        body: { departments: [], portal: [portalEntry] },
      }),
    })
    renderApp('/anmelden/link/abc')
    const button = await screen.findByRole('button', { name: 'Jetzt anmelden' })
    expect(calls.some((c) => c.key === 'POST /api/public/login-link/abc/')).toBe(false)
    await userEvent.setup().click(button)
    expect(await screen.findByRole('heading', { name: 'Hallo Erika' })).toBeInTheDocument()
  })

  it('meldet einen ungültigen Link', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      'POST /api/public/login-link/alt/': () => ({
        status: 404,
        body: { detail: 'Der Link ist ungültig oder abgelaufen.' },
      }),
    })
    renderApp('/anmelden/link/alt')
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Jetzt anmelden' }))
    expect(await screen.findByText('Der Link ist ungültig oder abgelaufen.')).toBeInTheDocument()
  })
})

describe('Mitgliederbereich', () => {
  it('zeigt Daten und speichert nur geänderte Felder', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/contexts/': () => ({
        status: 200,
        body: { departments: [], portal: [portalEntry] },
      }),
      'GET /api/portal/5/': () => ({ status: 200, body: portalDetail }),
      'POST /api/portal/5/change-requests/': () => ({
        status: 200,
        body: { applied: { street: 'Am Markt 2' }, request: null },
      }),
    })
    renderApp('/mein-bereich/daten')
    expect(await screen.findByText('Lindenweg 4')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Daten ändern' }))
    const street = screen.getByLabelText('Straße und Hausnummer')
    await user.clear(street)
    await user.type(street, 'Am Markt 2')
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    expect(await screen.findByText('Gespeichert.')).toBeInTheDocument()
    const call = calls.find((c) => c.key === 'POST /api/portal/5/change-requests/')!
    expect(JSON.parse(String(call.init?.body))).toEqual({ street: 'Am Markt 2', message: '' })
  })
})

describe('Mitgliederbereich nach Aufgaben', () => {
  it('führt von der Übersicht mit einem Klick zum Ausweis', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/contexts/': () => ({
        status: 200,
        body: { departments: [], portal: [portalEntry] },
      }),
      'GET /api/portal/5/': () => ({ status: 200, body: portalDetail }),
      'GET /api/portal/5/card/': () => ({ status: 200, body: { state: 'none' } }),
    })
    renderApp('/mein-bereich')
    const user = userEvent.setup()
    expect(await screen.findByRole('heading', { name: 'Mein Bereich' })).toBeInTheDocument()
    for (const name of ['Rechnungen', 'Rundschreiben', 'Meine Daten']) {
      expect(screen.getAllByRole('link', { name: new RegExp(name) }).length).toBeGreaterThan(0)
    }
    await user.click(screen.getByRole('link', { name: /Ausweis zeigen/ }))
    expect(await screen.findByRole('heading', { name: 'Mein Ausweis' })).toBeInTheDocument()
    expect(await screen.findByText(/keinen Mitgliedsausweis/)).toBeInTheDocument()
  })
})

describe('SEPA-Mandat im Mitgliederbereich', () => {
  it('erteilt ein Mandat erst nach Bestätigung', async () => {
    const mandate = {
      id: 1,
      reference: 'MITGL-11-1',
      membership: 11,
      club: null,
      payer_name: 'Muster, Erika',
      holder: 'Erika Muster',
      iban: 'DE02120300000000202051',
      iban_masked: 'DE02 **** 2051',
      bic: '',
      signed_on: '2025-03-01',
      source: 'online',
      source_label: 'im Mitgliederbereich',
      status: 'active',
      status_label: 'gültig',
      revoked_on: null,
      last_used_on: null,
      expired: false,
      created_at: '2025-03-01T10:00:00Z',
    }
    const base = {
      available: true,
      club_name: 'TV Beispielhausen',
      creditor_id: 'DE98ZZZ09999999999',
      text: 'Ich ermächtige TV Beispielhausen, Zahlungen von meinem Konto mittels Lastschrift einzuziehen.',
    }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/contexts/': () => ({
        status: 200,
        body: { departments: [], portal: [portalEntry] },
      }),
      'GET /api/portal/5/': () => ({ status: 200, body: portalDetail }),
      'GET /api/portal/5/invoices/': () => ({
        status: 200,
        body: { invoices: [], collective: [] },
      }),
      'GET /api/portal/5/card/': () => ({ status: 404, body: { detail: 'kein Ausweis' } }),
      'GET /api/portal/5/mandate/': () => ({ status: 200, body: { ...base, mandate: null } }),
      'POST /api/portal/5/mandate/': () => ({ status: 201, body: { ...base, mandate } }),
    })
    renderApp('/mein-bereich/rechnungen')
    const user = userEvent.setup()
    expect(await screen.findByText(/Ich ermächtige TV Beispielhausen/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Mandat erteilen' })
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText('Kontoinhaber'), 'Erika Muster')
    await user.type(screen.getByLabelText('IBAN'), 'DE02120300000000202051')
    await user.click(screen.getByLabelText('Ich erteile dieses SEPA-Lastschriftmandat.'))
    await user.click(submit)
    expect(await screen.findByText('MITGL-11-1')).toBeInTheDocument()
    const post = calls.find((c) => c.key === 'POST /api/portal/5/mandate/')!
    expect(JSON.parse(String(post.init?.body))).toEqual({
      holder: 'Erika Muster',
      iban: 'DE02120300000000202051',
      bic: '',
      consent: true,
    })
  })
})

describe('Abteilungsbereich', () => {
  it('listet die Mitglieder der Abteilung', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/contexts/': () => ({
        status: 200,
        body: {
          departments: [
            {
              id: 3,
              name: '1. Zug',
              club_id: 7,
              club_name: 'TV Beispielhausen',
              label: 'Zug',
              permissions: ['dept.members.view'],
              theme,
            },
          ],
          portal: [],
        },
      }),
      'GET /api/depts/3/members/?page=1': () => ({
        status: 200,
        body: {
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 11,
              last_name: 'Muster',
              first_name: 'Erika',
              birth_date: '1980-05-17',
              member_type: 'aktiv',
              email: 'erika@example.org',
              phone: '',
            },
          ],
        },
      }),
    })
    renderApp('/abteilung')
    expect(await screen.findByRole('link', { name: 'Muster, Erika' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Rollen und Rechte' })).not.toBeInTheDocument()
  })
})

describe('Mein Konto', () => {
  it('ändert das Passwort und fordert eine neue Anmelde-E-Mail an', async () => {
    const account = {
      email: 'kassenwart@example.org',
      first_name: 'Karla',
      last_name: 'Kasse',
      has_password: true,
      pending_email: null,
    }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/account/': () => ({ status: 200, body: account }),
      'GET /_allauth/browser/v1/account/authenticators/totp': () => ({
        status: 404,
        body: { status: 404, meta: { secret: 'ABC', totp_url: 'otpauth://totp/x' } },
      }),
      'POST /api/me/password/': () => ({ status: 200, body: account }),
      'POST /api/me/email/': () => ({
        status: 201,
        body: { ...account, pending_email: 'neu@example.org' },
      }),
    })
    renderApp('/mein-konto/anmeldung')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Bisheriges Passwort'), 'alt')
    await user.type(screen.getByLabelText(/^Neues Passwort(?! wiederholen)/), 'Ganz-Neu-123')
    await user.type(screen.getByLabelText('Neues Passwort wiederholen'), 'Ganz-Neu-123')
    await user.click(screen.getByRole('button', { name: 'Passwort ändern' }))
    expect(await screen.findByText('Passwort geändert.')).toBeInTheDocument()
    const pw = calls.find((c) => c.key === 'POST /api/me/password/')!
    expect(JSON.parse(String(pw.init?.body))).toEqual({
      current_password: 'alt',
      new_password: 'Ganz-Neu-123',
    })

    await user.click(screen.getByRole('button', { name: 'Anmelde-E-Mail ändern' }))
    const emailForm = screen.getByLabelText('Neue E-Mail-Adresse').closest('form')!
    await user.type(within(emailForm).getByLabelText('Neue E-Mail-Adresse'), 'neu@example.org')
    await user.type(
      within(emailForm).getByLabelText('Dein Passwort zur Bestätigung'),
      'Ganz-Neu-123',
    )
    await user.click(screen.getByRole('button', { name: 'Bestätigungslink senden' }))
    expect(await screen.findByText(/wartet auf Bestätigung/)).toBeInTheDocument()
  })
})
