import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const B = '/api/orgs/7/billing'

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="where">{pathname + search}</output>
}

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
          <Where />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const overview = {
  sepa_enabled: true,
  drafts: { count: 2, amount: '120.00' },
  open: { count: 3, amount: '180.00' },
  overdue: { count: 1, amount: '60.00' },
  dunnings_due: 1,
  debits_ready: 2,
  debits_pending: [],
  last_run: { id: 1, label: '2025', created_at: '2025-02-01T10:00:00Z' },
  can_edit: true,
}

function subnav() {
  const nav = screen.getByRole('navigation', { name: 'Module' })
  return within(nav)
}

describe('Finanzen', () => {
  it('fasst Kasse und Beiträge unter einem Menüpunkt zusammen', async () => {
    const org = testOrg({
      modules: ['members', 'finance', 'billing'],
      permissions: ['billing.view', 'billing.edit', 'finance.view', 'finance.edit'],
      parent_name: null,
      sepa_enabled: true,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${B}/overview/`]: () => ({ status: 200, body: overview }),
    })
    renderApp('/finanzen')
    expect(await screen.findByRole('heading', { name: 'Offene Rechnungen' })).toBeInTheDocument()
    const nav = subnav()
    expect(nav.getByRole('link', { name: 'Finanzen' })).toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Kasse' })).not.toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Beiträge' })).not.toBeInTheDocument()
    for (const name of [
      'Übersicht',
      'Rechnungen',
      'Lastschriften',
      'Kassenbuch',
      'Abschluss & Berichte',
      'Einrichtung',
    ])
      expect(nav.getByRole('link', { name })).toBeInTheDocument()
    expect(screen.getByText('180,00 €')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '1 Rechnung ist zu mahnen' })).toHaveAttribute(
      'href',
      '/finanzen/rechnungen/mahnungen',
    )
    expect(
      screen.getByRole('link', { name: /2 Rechnungen können per Lastschrift/ }),
    ).toBeInTheDocument()
  })

  it('blendet Lastschriften aus, wenn sie ausgeschaltet sind', async () => {
    const org = testOrg({
      modules: ['members', 'billing'],
      permissions: ['billing.view', 'billing.edit'],
      parent_name: null,
      sepa_enabled: false,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${B}/overview/`]: () => ({
        status: 200,
        body: { ...overview, sepa_enabled: false, debits_ready: 0 },
      }),
    })
    renderApp('/finanzen/lastschrift/mandate')
    expect(await screen.findByRole('heading', { name: 'Offene Rechnungen' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/finanzen$/))
    const nav = subnav()
    expect(nav.queryByRole('link', { name: 'Lastschriften' })).not.toBeInTheDocument()
    // ohne Kassenrechte keine Kassen-Unterpunkte
    expect(nav.queryByRole('link', { name: 'Kassenbuch' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Lastschrift/)).not.toBeInTheDocument()
  })

  it('zeigt Kassenprüfern nur lesend die Kasse', async () => {
    const org = testOrg({
      modules: ['members', 'finance', 'billing'],
      permissions: ['finance.view'],
      parent_name: null,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/finance/settings/': () => ({
        status: 200,
        body: { current_year: 2025, years: [], tax_areas: [], tax_areas_enabled: false },
      }),
      'GET /api/orgs/7/finance/overview/?jahr=2025': () => ({
        status: 200,
        body: {
          year: 2025,
          label: '2025',
          start_date: '2025-01-01',
          end_date: '2025-12-31',
          years: [{ year: 2025, label: '2025' }],
          tax_areas_enabled: false,
          accounts: [],
          categories: [],
          tax_areas: [],
          totals: { income: '0', expense: '0', result: '0', start: '0', end: '0' },
          booking_count: 0,
        },
      }),
    })
    renderApp('/finanzen/einstellungen')
    expect(await screen.findByText('nur lesen')).toBeInTheDocument()
    const nav = subnav()
    expect(nav.queryByRole('link', { name: 'Rechnungen' })).not.toBeInTheDocument()
    expect(nav.getByRole('link', { name: 'Kassenbuch' })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/finanzen/einstellungen/konten'),
    )
    const user = userEvent.setup()
    await user.click(nav.getByRole('link', { name: 'Übersicht' }))
    expect(await screen.findByText('Noch keine Konten angelegt.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Erstes Konto anlegen' })).not.toBeInTheDocument()
  })

  it('leitet alte Adressen samt Filter um', async () => {
    const org = testOrg({
      modules: ['members', 'finance', 'billing'],
      permissions: ['billing.view', 'finance.view'],
      parent_name: null,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    })
    renderApp('/beitraege/laeufe?x=1')
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        '/finanzen/rechnungen/beitragslaeufe?x=1',
      ),
    )
  })
})

describe('Arbeitsbereich einer Untereinheit', () => {
  it('zeigt nur Kasse und Rollen, keine Mitglieder', async () => {
    const org = testOrg({
      id: 9,
      name: 'Jägerzug',
      type: 'unit',
      type_label: 'Zug',
      modules: ['finance'],
      permissions: ['finance.view', 'roles.manage'],
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/9/roles/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/9/assignments/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/9/assignments/?aktiv=1': () => ({ status: 200, body: [] }),
    })
    renderApp('/einstellungen')
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/einstellungen/rollen'),
    )
    const nav = subnav()
    expect(nav.getByRole('link', { name: 'Finanzen' })).toBeInTheDocument()
    expect(nav.getByRole('link', { name: 'Einstellungen' })).toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Mitglieder' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Organisation' })).not.toBeInTheDocument()
  })
})
