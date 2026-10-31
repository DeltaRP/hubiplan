import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { niceTicks, foldSeries } from '../components/charts/chartData.ts'
import { presetQuery } from '../components/charts/range.ts'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

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

const bucket = (label: string, start: string, end: string) => ({ label, start, end })

const memberStats = {
  von: '2025-01-01',
  bis: '2025-03-31',
  raster: 'monat',
  earliest: '2001-01-01',
  buckets: [
    { ...bucket('Jan. 2025', '2025-01-01', '2025-01-31'), count: 100, entries: 2, exits: 0 },
    { ...bucket('Feb. 2025', '2025-02-01', '2025-02-28'), count: 103, entries: 3, exits: 0 },
    { ...bucket('März 2025', '2025-03-01', '2025-03-31'), count: 101, entries: 0, exits: 2 },
  ],
  summary: { start: 98, end: 101, entries: 5, exits: 2 },
  types: [
    { id: 1, name: 'aktiv', values: [60, 62, 61] },
    { id: 2, name: 'passiv', values: [40, 41, 40] },
  ],
  groups_title: 'Zug',
  groups: [
    { id: 5, name: 'Jägerzug', values: [20, 21, 21] },
    { id: null, name: 'ohne Zug', values: [80, 82, 80] },
  ],
  exit_reasons: [{ reason: 'exit', label: 'Austritt', count: 2 }],
  ages: {
    groups: ['unter 18', '18 bis 29'],
    start: [10, 88],
    end: [11, 90],
    start_summary: { count: 98, mean: 22.4, sd: 3.2 },
    end_summary: { count: 101, mean: 22.6, sd: null },
  },
}

const financeStats = {
  von: '2025-01-01',
  bis: '2025-02-28',
  raster: 'monat',
  earliest: '2024-01-01',
  previous: { von: '2024-01-01', bis: '2024-02-29' },
  buckets: [
    {
      ...bucket('Jan. 2025', '2025-01-01', '2025-01-31'),
      income: '300.00',
      expense: '0.00',
      result: '300.00',
      balance: '1500.00',
    },
    {
      ...bucket('Feb. 2025', '2025-02-01', '2025-02-28'),
      income: '0.00',
      expense: '120.00',
      result: '-120.00',
      balance: '1380.00',
    },
  ],
  accounts: [
    {
      id: 1,
      name: 'Girokonto',
      kind_label: 'Bankkonto',
      is_active: true,
      start: '1200.00',
      values: ['1500.00', '1380.00'],
    },
  ],
  categories: [
    {
      id: 3,
      name: 'Beiträge',
      income: '300.00',
      expense: '0.00',
      previous_income: '200.00',
      previous_expense: '0.00',
    },
  ],
  summary: {
    income: '300.00',
    expense: '120.00',
    result: '180.00',
    previous_income: '200.00',
    previous_expense: '0.00',
    previous_result: '200.00',
    balance_start: '1200.00',
    balance_end: '1380.00',
  },
}

// Standard der Mitgliederentwicklung: letzte 5 Jahre nach Jahren
const FIVE_YEARS = `?von=${new Date().getFullYear() - 4}-01&raster=jahr`

describe('Mitgliederentwicklung', () => {
  it('zeigt Bestand, Ein- und Austritte und lässt den Zeitraum wählen', async () => {
    const org = testOrg({ modules: ['members'], permissions: ['members.view'] })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET /api/orgs/7/members/statistics/${FIVE_YEARS}`]: () => ({
        status: 200,
        body: { ...memberStats, raster: 'jahr' },
      }),
      'GET /api/orgs/7/members/statistics/': () => ({ status: 200, body: memberStats }),
    })
    renderApp('/mitglieder/entwicklung')
    expect(await screen.findByRole('heading', { name: 'Mitglieder am 31.3.2025' })).toBeVisible()
    expect(screen.getByText('+3 seit 1.1.2025 (98)')).toBeInTheDocument()
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(nav.getByRole('link', { name: 'Entwicklung' })).toHaveAttribute(
      'href',
      '/mitglieder/entwicklung',
    )
    expect(nav.getByRole('link', { name: 'Mitgliederliste' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Nach Mitgliedsart' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Nach Zug' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Austrittsgründe' })).toBeInTheDocument()
    // Durchschnittsalter mit Standardabweichung
    const ages = screen.getByRole('heading', { name: 'Altersstruktur' }).closest('.card')!
    expect(ages).toHaveTextContent('Durchschnittsalter am 1.1.202522,4 Jahre (SD 3,2), 98 Personen')
    expect(ages).toHaveTextContent('Durchschnittsalter am 31.3.202522,6 Jahre')

    // Züge lassen sich in der Legende aus- und wieder einblenden
    const zug = screen.getByRole('heading', { name: 'Nach Zug' }).closest('.card') as HTMLElement
    const jaeger = within(zug).getByRole('button', { name: 'Jägerzug' })
    expect(jaeger).toHaveAttribute('aria-pressed', 'true')
    expect(zug.querySelectorAll('svg path[stroke]')).toHaveLength(2)
    await userEvent.click(jaeger)
    expect(jaeger).toHaveAttribute('aria-pressed', 'false')
    expect(zug.querySelectorAll('svg path[stroke]')).toHaveLength(1)
    await userEvent.click(within(zug).getByRole('button', { name: 'Alle zeigen' }))
    expect(zug.querySelectorAll('svg path[stroke]')).toHaveLength(2)

    // Werte stehen auch als Tabelle bereit
    const card = screen.getByRole('heading', { name: 'Mitgliederbestand' }).closest('.card')!
    const table = within(card as HTMLElement).getByRole('table', { hidden: true })
    expect(within(table).getByRole('rowheader', { name: 'Feb. 2025', hidden: true })).toBeTruthy()
    expect(within(table).getByText('103')).toBeInTheDocument()

    // Pfeiltasten zeigen den Wert eines Monats
    const plot = within(card as HTMLElement).getByRole('group', { name: /Mitgliederbestand/ })
    fireEvent.keyDown(plot, { key: 'ArrowRight' })
    expect(within(plot).getByRole('status')).toHaveTextContent('Jan. 2025Mitglieder: 100')

    // Standard sind die letzten 5 Jahre nach Jahren
    expect(screen.getByLabelText('Zeitraum')).toHaveValue('5j')
    expect(calls.map((c) => c.key)).toContain(`GET /api/orgs/7/members/statistics/${FIVE_YEARS}`)
    expect(screen.getByRole('heading', { name: 'Eintritte und Austritte je Jahr' })).toBeVisible()

    await userEvent.selectOptions(screen.getByLabelText('Zeitraum'), '12m')
    expect(
      await screen.findByRole('heading', { name: 'Eintritte und Austritte je Monat' }),
    ).toBeVisible()
    expect(calls.map((c) => c.key)).toContain('GET /api/orgs/7/members/statistics/')
  })

  it('Dachverband sieht die Entwicklung über alle Vereine', async () => {
    const org = testOrg({
      type: 'federation',
      permissions: ['members.view'],
      federation_member_access: 'read',
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET /api/orgs/7/federation/statistics/${FIVE_YEARS}`]: () => ({
        status: 200,
        body: { ...memberStats, groups_title: 'Verein' },
      }),
    })
    renderApp('/mitglieder/entwicklung')
    expect(await screen.findByText(/gemeldeten Mitgliedsart/)).toBeInTheDocument()
    await screen.findByRole('heading', { name: 'Mitgliederbestand' })
    expect(screen.getByRole('heading', { name: 'Nach Verein' })).toBeInTheDocument()
  })
})

describe('Entwicklung bei eigenen Mitgliedern der obersten Einheit', () => {
  it('eigene Entwicklung ohne Freigabe für die Einheiten darunter (kein 403)', async () => {
    const org = testOrg({
      type: 'federation',
      modules: ['members'],
      permissions: ['members.view'],
      federation_member_access: 'none',
      direct_members: true,
    })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET /api/orgs/7/members/statistics/${FIVE_YEARS}`]: () => ({
        status: 200,
        body: memberStats,
      }),
    })
    renderApp('/mitglieder/entwicklung')
    await screen.findByRole('heading', { name: 'Mitgliederbestand' })
    expect(calls.some((c) => c.key.includes('/federation/statistics/'))).toBe(false)
  })

  it('mit Freigabe: Entwicklung aller unter /mitglieder/verbund/entwicklung', async () => {
    const org = testOrg({
      type: 'federation',
      modules: ['members'],
      permissions: ['members.view'],
      federation_member_access: 'read',
      direct_members: true,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET /api/orgs/7/federation/statistics/${FIVE_YEARS}`]: () => ({
        status: 200,
        body: memberStats,
      }),
    })
    renderApp('/mitglieder/verbund/entwicklung')
    expect(await screen.findByText(/gemeldeten Mitgliedsart/)).toBeInTheDocument()
  })
})

describe('Finanzentwicklung', () => {
  it('zeigt Kontostände, Einnahmen und Ausgaben mit Vorjahresvergleich', async () => {
    const org = testOrg({
      modules: ['finance'],
      permissions: ['finance.view'],
      parent_name: null,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/finance/statistics/': () => ({ status: 200, body: financeStats }),
    })
    renderApp('/finanzen/entwicklung')
    expect(await screen.findByRole('heading', { name: 'Kontostand gesamt' })).toBeVisible()
    expect(screen.getByText('+50 % zum Vorjahreszeitraum (200,00 €)')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Einnahmen und Ausgaben je Monat' })).toBeVisible()
    // nur ein Konto: kein eigenes Diagramm je Konto
    expect(screen.queryByRole('heading', { name: 'Kontostände je Konto' })).toBeNull()
    expect(screen.getAllByText('Vorjahreszeitraum (1.1.2024 bis 29.2.2024)')).toHaveLength(2)
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(nav.getByRole('link', { name: 'Entwicklung' })).toHaveAttribute(
      'href',
      '/finanzen/entwicklung',
    )
  })

  it('ohne Kassenrecht gibt es keine Entwicklung', async () => {
    const org = testOrg({
      modules: ['billing'],
      permissions: ['billing.view'],
      parent_name: null,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/billing/overview/': () => ({
        status: 200,
        body: {
          sepa_enabled: false,
          drafts: { count: 0, amount: '0.00' },
          open: { count: 0, amount: '0.00' },
          overdue: { count: 0, amount: '0.00' },
          dunnings_due: 0,
          debits_ready: 0,
          debits_pending: [],
          last_run: null,
          can_edit: false,
        },
      }),
    })
    renderApp('/finanzen')
    expect(await screen.findByRole('heading', { name: 'Offene Rechnungen' })).toBeVisible()
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(nav.queryByRole('link', { name: 'Entwicklung' })).toBeNull()
  })
})

describe('Hilfen der Diagramme', () => {
  it('rechnet Voreinstellungen in Zeiträume um', () => {
    const today = new Date(2026, 9, 24)
    expect(presetQuery('12m', {}, today)).toEqual({})
    expect(presetQuery('24m', {}, today)).toEqual({ von: '2024-11' })
    expect(presetQuery('vorjahr', {}, today)).toEqual({
      von: '2025-01',
      bis: '2025-12',
      raster: 'monat',
    })
    expect(presetQuery('alles', {}, today)).toEqual({ von: 'alles', raster: 'jahr' })
    expect(presetQuery('eigen', { von: '2020-03', bis: '2021-02' }, today)).toEqual({
      von: '2020-03',
      bis: '2021-02',
    })
  })

  it('findet runde Achsenschritte', () => {
    expect(niceTicks(0, 95)).toEqual([0, 25, 50, 75, 100])
    expect(niceTicks(-120, 300)).toEqual([-200, 0, 200, 400])
    const zoomed = niceTicks(172, 176, 4, false)
    expect(zoomed[0]).toBeGreaterThan(0)
    expect(zoomed[zoomed.length - 1]).toBeGreaterThanOrEqual(176)
  })

  it('fasst viele Reihen zusammen und lässt „ohne“ stehen', () => {
    const items = Array.from({ length: 10 }, (_, i) => ({
      key: String(i),
      name: `Zug ${i}`,
      values: [i],
    }))
    const folded = foldSeries(
      [...items, { key: 'ohne', name: 'ohne Zug', values: [50] }],
      7,
      'ohne',
    )
    expect(folded.map((s) => s.name)).toEqual([
      'Zug 5',
      'Zug 6',
      'Zug 7',
      'Zug 8',
      'Zug 9',
      'Weitere (5)',
      'ohne Zug',
    ])
    expect(folded[5].values).toEqual([0 + 1 + 2 + 3 + 4])
  })
})
