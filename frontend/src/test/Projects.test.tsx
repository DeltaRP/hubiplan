import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const F = '/api/orgs/7/finance'

const org = testOrg({
  modules: ['members', 'finance'],
  permissions: ['finance.view', 'finance.edit'],
})

const project = {
  id: 5,
  name: 'Schützenfest 2025',
  starts_on: '2025-08-23',
  ends_on: '2025-08-25',
  description: '',
  status: 'done',
  status_label: 'abgeschlossen',
  department: null,
  department_name: null,
  series: 2,
  series_name: 'Schützenfest',
  income: '2000.50',
  expense: '2400.00',
  result: '-399.50',
  booking_count: 4,
  event_count: 0,
}

const evaluation = {
  ...project,
  tax_areas_enabled: false,
  categories: [
    {
      id: 1,
      name: 'Getränke',
      tax_area: '',
      income: '1200.50',
      expense: '900.00',
      result: '300.50',
    },
    { id: 2, name: 'Musik', tax_area: '', income: '0.00', expense: '1500.00', result: '-1500.00' },
  ],
  tax_areas: [],
  totals: { income: '2000.50', expense: '2400.00', result: '-399.50' },
  bookings: [],
  events: [],
  open_invoices: { count: 0, outstanding: '0.00' },
}

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

describe('Veranstaltungen', () => {
  it('listet Veranstaltungen mit Ergebnis unter Finanzen', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${F}/projects/?`]: () => ({ status: 200, body: [project] }),
      [`GET ${F}/series/`]: () => ({
        status: 200,
        body: [{ id: 2, name: 'Schützenfest', project_count: 1 }],
      }),
    })
    renderApp('/finanzen/veranstaltungen')
    const link = await screen.findByRole('link', { name: 'Schützenfest 2025' })
    expect(link).toHaveAttribute('href', '/finanzen/veranstaltungen/5')
    expect(screen.getByText('-399,50 €')).toBeInTheDocument()
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(nav.getByRole('link', { name: 'Veranstaltungen' })).toBeInTheDocument()
  })

  it('zeigt die Auswertung und ordnet Buchungen zu', async () => {
    const booking = {
      id: 31,
      year: 2025,
      number: 12,
      display_number: '2025-0012',
      date: '2025-08-24',
      kind: 'income',
      kind_label: 'Einnahme',
      amount: '55.00',
      account: 1,
      account_name: 'Barkasse',
      to_account: null,
      to_account_name: null,
      category: 1,
      category_name: 'Getränke',
      tax_area: '',
      text: 'Theke Sonntag',
      reference: '',
      membership: null,
      member_name: null,
      department: null,
      department_name: null,
      project: null,
      project_name: null,
      receipts: [],
      created_at: '2025-08-24T10:00:00Z',
    }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${F}/projects/5/evaluation/`]: () => ({ status: 200, body: evaluation }),
      [`GET ${F}/projects/?`]: () => ({ status: 200, body: [project] }),
      [`GET ${F}/series/`]: () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?veranstaltung=-&von=2025-07-24&bis=2025-09-24&page_size=200`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [booking] },
      }),
      [`POST ${F}/projects/5/assign/`]: () => ({ status: 200, body: { changed: 1 } }),
    })
    renderApp('/finanzen/veranstaltungen/5')
    expect(await screen.findByRole('heading', { name: 'Fehlbetrag' })).toBeInTheDocument()
    expect(screen.getAllByText('-399,50 €').length).toBeGreaterThan(0)
    expect(screen.getByText('Getränke')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Excel' })).toHaveAttribute(
      'href',
      `${F}/projects/5/report/?als=xlsx`,
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Vorhandene Buchungen zuordnen' }))
    await user.click(await screen.findByRole('checkbox', { name: 'Buchung 2025-0012 zuordnen' }))
    await user.click(screen.getByRole('button', { name: '1 Buchung zuordnen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${F}/projects/5/assign/`)).toBe(true),
    )
    const post = calls.find((c) => c.key === `POST ${F}/projects/5/assign/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({ bookings: [31] })
  })
})
