import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedOut = () => ({ status: 401, body: { status: 401, data: { flows: [] } } })
const loggedIn = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})

function renderAt(path: string) {
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

const details = {
  name: 'Hubertus-Schützenverein',
  legal_form: 'eingetragener Verein',
  address: { street: 'Hauptstraße 1', postal_code: '41468', city: 'Neuss', country: 'Deutschland' },
  representatives: [{ name: 'Vera Vorsitz', role: '1. Vorsitzende' }],
  representatives_text: '',
  email: 'info@verein.example',
  phone: '02131 123',
  website: '',
  registered: true,
  register_court: 'Amtsgericht Neuss',
  register_number: 'VR 1234',
  vat_id: '',
  responsible: '',
  data_protection_officer: '',
  extra_text: '',
}

const platformImprint = {
  unit: 'HUBIplan',
  owner: 'Plattformbetrieb Muster',
  owner_label: 'Plattform',
  is_platform: true,
  inherited: false,
  mode: 'own',
  external_url: '',
  details: {
    ...details,
    name: 'Plattformbetrieb Muster',
    representatives: [],
    register_number: 'HRB 99',
  },
  privacy: { mode: 'text', text: 'Datenschutzerklärung der Plattform.', url: '' },
  updated_at: '2026-10-25T20:00:00Z',
}

const publicImprint = {
  unit: 'Jägerzug',
  owner: 'Hubertus-Schützenverein',
  owner_label: 'Verein',
  is_platform: false,
  inherited: true,
  mode: 'own',
  external_url: '',
  details,
  privacy: { mode: 'text', text: 'Wir schützen Ihre Daten.', url: '' },
  updated_at: '2026-10-25T20:00:00Z',
}

describe('Impressum öffentlich', () => {
  it('zeigt auf einer Seite zuerst den Verein, dann den Betreiber', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      'GET /api/public/imprint/abc12345/': () => ({ status: 200, body: publicImprint }),
      'GET /api/public/imprint/': () => ({ status: 200, body: platformImprint }),
    })
    renderAt('/impressum/abc12345')
    expect(await screen.findByText('Für Jägerzug gilt das Impressum von Hubertus-Schützenverein.'))
    expect(screen.getByText('Vera Vorsitz (1. Vorsitzende)')).toBeInTheDocument()
    expect(screen.getByText(/VR 1234/)).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings.indexOf('Hubertus-Schützenverein')).toBeLessThan(
      headings.indexOf('Betreiber der Plattform HUBIplan'),
    )
    expect(await screen.findByText('Plattformbetrieb Muster')).toBeInTheDocument()
    // Fußzeile: je ein Link, der zur Seite der Einheit führt
    // (die Einheit kommt erst nach dem Laden in die Fußzeile, daher warten)
    const footer = screen.getByRole('navigation', { name: 'Rechtliches' })
    await waitFor(() =>
      expect(within(footer).getByRole('link', { name: 'Impressum' })).toHaveAttribute(
        'href',
        '/impressum/abc12345',
      ),
    )
    expect(within(footer).getByRole('link', { name: 'Datenschutz' })).toHaveAttribute(
      'href',
      '/datenschutz/abc12345',
    )
  })

  it('zeigt die Datenschutzhinweise des Vereins und der Plattform', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      'GET /api/public/imprint/abc12345/': () => ({ status: 200, body: publicImprint }),
      'GET /api/public/imprint/': () => ({ status: 200, body: platformImprint }),
    })
    renderAt('/datenschutz/abc12345')
    expect(await screen.findByText('Wir schützen Ihre Daten.')).toBeInTheDocument()
    expect(await screen.findByText('Datenschutzerklärung der Plattform.')).toBeInTheDocument()
  })

  it('meldet unbekannte Seiten', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      'GET /api/public/imprint/weg/': () => ({ status: 404, body: { detail: 'Nicht gefunden.' } }),
    })
    renderAt('/impressum/weg')
    expect(await screen.findByText('Diese Seite gibt es nicht.')).toBeInTheDocument()
  })

  it('verlinkt Impressum und Datenschutz auf der Anmeldeseite', async () => {
    fakeApi({ [SESSION]: loggedOut })
    renderAt('/anmelden')
    const footer = await screen.findByRole('navigation', { name: 'Rechtliches' })
    expect(footer).toHaveTextContent('Impressum')
    expect(footer).toHaveTextContent('Datenschutz')
  })
})

describe('Impressum pflegen', () => {
  const state = (overrides: Record<string, unknown> = {}) => ({
    organization: { id: 7, name: 'TV Beispielhausen', type: 'club' },
    imprint: {
      public_key: 'key7',
      mode: 'own',
      external_url: '',
      name: '',
      legal_form: '',
      street: '',
      postal_code: '',
      city: '',
      representatives: '',
      email: '',
      phone: '',
      registered: false,
      register_court: '',
      register_number: '',
      vat_id: '',
      responsible: '',
      data_protection_officer: '',
      extra_text: '',
      privacy_mode: 'text',
      privacy_text: '',
      privacy_url: '',
      updated_at: '2026-10-25T20:00:00Z',
    },
    owner: { id: 7, name: 'TV Beispielhausen', is_self: true },
    preview: { ...details, representatives: [], email: '', phone: '' },
    representatives: [],
    missing: ['Vertretungsberechtigte', 'E-Mail', 'Telefon (zweiter Kontaktweg)'],
    urls: { imprint: 'https://x/impressum/key7', privacy: 'https://x/datenschutz/key7' },
    template: 'Datenschutzhinweise für Mitglieder\n[Name der Einheit]',
    ...overrides,
  })

  it('zeigt fehlende Angaben auf der Startseite', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ imprint_key: 'key7' })],
      }),
      'GET /api/orgs/7/imprint/': () => ({ status: 200, body: state() }),
    })
    renderAt('/')
    expect(await screen.findByText(/Im Impressum fehlen noch Angaben/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Impressum ergänzen' })).toBeInTheDocument()
    expect(
      within(screen.getByRole('navigation', { name: 'Rechtliches' })).getByRole('link', {
        name: 'Impressum',
      }),
    ).toHaveAttribute('href', '/impressum/key7')
  })

  it('erzeugt den Text und speichert automatisch', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/imprint/': () => ({ status: 200, body: state() }),
      'PATCH /api/orgs/7/imprint/': (init) => ({
        status: 200,
        body: state({
          imprint: { ...state().imprint, ...JSON.parse(String(init?.body)) },
          missing: [],
        }),
      }),
    })
    renderAt('/einstellungen/datenschutz')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Textentwurf erzeugen' }))
    expect(await screen.findByText('✓ Gespeichert', {}, { timeout: 3000 })).toBeInTheDocument()
    const patch = calls.find((c) => c.key === 'PATCH /api/orgs/7/imprint/')
    expect(JSON.parse(String(patch?.init?.body)).privacy_text).toContain('[Name der Einheit]')
  })
  it('fragt Registerangaben nur bei eingetragenen Einheiten', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/imprint/': () => ({ status: 200, body: state() }),
      'PATCH /api/orgs/7/imprint/': (init) => ({
        status: 200,
        body: state({ imprint: { ...state().imprint, ...JSON.parse(String(init?.body)) } }),
      }),
    })
    renderAt('/einstellungen/impressum')
    const user = userEvent.setup()
    const box = await screen.findByRole('checkbox', { name: /Eingetragener Verein/ })
    expect(screen.queryByLabelText(/Registernummer/)).not.toBeInTheDocument()
    await user.click(box)
    expect(await screen.findByLabelText(/Registernummer/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Registergericht/)).toBeInTheDocument()
  })
})
