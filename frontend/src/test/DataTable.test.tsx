import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { DataTable } from '../components/DataTable.tsx'
import type { Column } from '../components/DataTable.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { buildTerms } from '../org/terms.ts'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

interface Row {
  id: number
  name: string
  year: number
  status: string
}

const rows: Row[] = Array.from({ length: 25 }, (_, i) => ({
  id: i + 1,
  name: `Eintrag ${i + 1}`,
  year: 2000 - i,
  status: i % 5 === 0 ? 'inaktiv' : 'aktiv',
}))

const columns: Column<Row>[] = [
  { key: 'name', label: 'Name', value: (r) => r.name },
  { key: 'year', label: 'Jahr', value: (r) => r.year, numeric: true },
  { key: 'status', label: 'Status', value: (r) => r.status, filter: true },
]

const names = () =>
  screen
    .getAllByRole('row')
    .slice(1)
    .map((tr) => within(tr).getAllByRole('cell')[0].textContent)

function renderPage(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('DataTable', () => {
  it('blättert mit 10, 20 oder 50 Zeilen', async () => {
    const user = userEvent.setup()
    render(<DataTable label="Test" rows={rows} columns={columns} rowKey={(r) => r.id} />)
    expect(names()).toHaveLength(10)
    expect(screen.getByText(/1–10 von 25/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(names()[0]).toBe('Eintrag 11')
    await user.selectOptions(screen.getByLabelText('Zeilen pro Seite'), '20')
    expect(names()).toHaveLength(20)
    expect(names()[0]).toBe('Eintrag 1')
    await user.selectOptions(screen.getByLabelText('Zeilen pro Seite'), '50')
    expect(names()).toHaveLength(25)
  })

  it('sortiert jede Spalte auf- und absteigend, Zahlen natürlich', async () => {
    const user = userEvent.setup()
    render(<DataTable label="Test" rows={rows} columns={columns} rowKey={(r) => r.id} />)
    await user.click(screen.getByRole('button', { name: /^Name/ }))
    // „Eintrag 2“ vor „Eintrag 10“
    expect(names().slice(0, 3)).toEqual(['Eintrag 1', 'Eintrag 2', 'Eintrag 3'])
    expect(screen.getByRole('columnheader', { name: /Name/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
    await user.click(screen.getByRole('button', { name: /^Name/ }))
    expect(names()[0]).toBe('Eintrag 25')
    await user.click(screen.getByRole('button', { name: /^Jahr/ }))
    expect(names()[0]).toBe('Eintrag 25') // Jahr 1976
  })

  it('filtert und durchsucht', async () => {
    const user = userEvent.setup()
    render(<DataTable label="Test" rows={rows} columns={columns} rowKey={(r) => r.id} />)
    await user.selectOptions(screen.getByLabelText('Filter Status'), 'inaktiv')
    expect(names()).toEqual(['Eintrag 1', 'Eintrag 6', 'Eintrag 11', 'Eintrag 16', 'Eintrag 21'])
    expect(screen.getByText('5 von 25 Einträgen')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Test durchsuchen'), 'eintrag 21')
    expect(names()).toEqual(['Eintrag 21'])
    await user.clear(screen.getByLabelText('Test durchsuchen'))
    await user.type(screen.getByLabelText('Test durchsuchen'), 'gibtsnicht')
    expect(screen.getByText('Nichts gefunden.')).toBeInTheDocument()
  })
})

const dep = (id: number, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  founding_year: 1950 + id,
  sort_order: id,
  is_active: true,
  fiscal_start_month: 1,
  fiscal_start_day: 1,
  logo_url: null,
  roles: [],
  member_count: id * 3,
  ...extra,
})

describe('Züge als Tabelle', () => {
  function setup(deleteStatus = 204) {
    let deps = [dep(1, '1. Zug'), dep(2, 'Herolde', { is_active: false }), dep(3, 'Jäger')]
    const terms = buildTerms('Zug', 'Züge', 'm')
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [
          testOrg({
            department_label: 'Zug',
            department_label_plural: 'Züge',
            department_terms: terms,
          }),
        ],
      }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: deps }),
      'GET /api/permissions/?org_type=department&org=7': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/statutes/?department=3': () => ({
        status: 200,
        body: { versions: [], publication: { is_public: false }, can_manage: true },
      }),
      'DELETE /api/orgs/7/departments/3/': () => {
        if (deleteStatus !== 204)
          return { status: deleteStatus, body: ['Dieser Zug hat noch Mitglieder.'] }
        deps = deps.filter((d) => d.id !== 3)
        return { status: 204 }
      },
    })
    renderPage('/einstellungen/untereinheiten')
    return calls
  }

  it('zeigt die Züge mit Mitgliederzahl und filtert nach Status', async () => {
    setup()
    const user = userEvent.setup()
    const table = await screen.findByRole('table', { name: 'Züge' })
    expect(within(table).getAllByRole('row')).toHaveLength(4)
    expect(within(table).getByText('9')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Filter Status'), 'inaktiv')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(within(table).getByText('Herolde')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/Abteilung/)
  })

  it('löscht nach Rückfrage im App-Dialog', async () => {
    const calls = setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jäger löschen' }))
    const dialog = await screen.findByRole('alertdialog', { name: '„Jäger“ löschen?' })
    expect(dialog).toHaveTextContent('diesem Zug')
    await user.click(within(dialog).getByRole('button', { name: 'Löschen' }))
    await waitFor(() => expect(screen.queryByText('Jäger')).not.toBeInTheDocument())
    expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/departments/3/')).toBe(true)
  })

  it('zeigt einen Fehler beim Löschen im Dialog', async () => {
    setup(400)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jäger löschen' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Löschen' }),
    )
    const error = await screen.findByRole('alertdialog', { name: 'Zug nicht gelöscht' })
    expect(error).toHaveTextContent('Dieser Zug hat noch Mitglieder.')
  })

  it('öffnet die Bearbeitung über das Stift-Icon', async () => {
    setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jäger bearbeiten' }))
    expect(await screen.findByText('Rollen in diesem Zug')).toBeInTheDocument()
    // Name im Bearbeiten-Formular; beim Anlegen ist „Gehört zu“ auf diesen Zug gesetzt
    const fields = screen.getAllByDisplayValue('Jäger')
    expect(fields.map((f) => f.tagName)).toEqual(['INPUT', 'SELECT'])
  })
})

describe('Untereinheiten im Baum', () => {
  it('zeigt Gruppen eingerückt unter ihrem Zug und legt eine Gruppe darunter an', async () => {
    const zugTerms = buildTerms('Zug', 'Züge', 'm')
    const deps = [
      dep(1, 'Jäger', {
        depth: 0,
        parent_unit: null,
        path: 'Jäger',
        label: 'Zug',
        child_terms: buildTerms('Gruppe', 'Gruppen', 'f'),
      }),
      dep(2, 'Gruppe 1', {
        depth: 1,
        parent_unit: 1,
        path: 'Jäger › Gruppe 1',
        label: 'Gruppe',
        label_plural: 'Gruppen',
        label_gender: 'f',
      }),
    ]
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ department_label: 'Zug', department_terms: zugTerms })],
      }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: deps }),
      'GET /api/permissions/?org_type=department&org=7': () => ({ status: 200, body: [] }),
      'POST /api/orgs/7/departments/': () => ({ status: 201, body: dep(3, 'Gruppe 2') }),
    })
    renderPage('/einstellungen/untereinheiten')
    const user = userEvent.setup()
    const table = await screen.findByRole('table', { name: 'Züge' })
    const cells = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((tr) => within(tr).getAllByRole('cell')[0])
    expect(cells.map((c) => c.textContent)).toEqual(['Jäger', '↳Gruppe 1Gruppe'])
    expect(cells[1].querySelector('[data-depth="1"]')).not.toBeNull()

    await user.selectOptions(await screen.findByLabelText(/Gehört zu/), '1')
    expect(screen.getByRole('heading', { name: 'Gruppe anlegen' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/Vollständiger Name/), 'Gruppe 2')
    await user.type(screen.getByLabelText(/Gründungsjahr/), '1999')
    await user.click(screen.getByRole('button', { name: 'Anlegen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'POST /api/orgs/7/departments/')).toBe(true),
    )
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/departments/')!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({ name: 'Gruppe 2', parent_unit: 1 })
  })
})

describe('Untereinheit umhängen', () => {
  it('bietet weder sich selbst noch eigene Untereinheiten an und speichert die neue Stelle', async () => {
    const deps = [
      dep(1, 'Jäger', { depth: 0, parent_unit: null, path: 'Jäger' }),
      dep(2, 'Gruppe 1', { depth: 1, parent_unit: 1, path: 'Jäger › Gruppe 1', label: 'Gruppe' }),
      dep(4, 'Schützen', { depth: 0, parent_unit: null, path: 'Schützen' }),
    ]
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [
          testOrg({ department_label: 'Zug', department_terms: buildTerms('Zug', 'Züge', 'm') }),
        ],
      }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: deps }),
      'GET /api/permissions/?org_type=department&org=7': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/statutes/?department=1': () => ({
        status: 200,
        body: { versions: [], publication: { is_public: false }, can_manage: true },
      }),
      'PATCH /api/orgs/7/departments/1/': () => ({ status: 200, body: deps[0] }),
    })
    renderPage('/einstellungen/untereinheiten')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jäger bearbeiten' }))
    const select = (await screen.findAllByLabelText(/Gehört zu/))[0] as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      'direkt zum Verein',
      'Schützen',
    ])
    await user.selectOptions(select, '4')
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'PATCH /api/orgs/7/departments/1/')).toBe(true),
    )
    const patch = calls.filter((c) => c.key === 'PATCH /api/orgs/7/departments/1/').at(-1)!
    expect(JSON.parse(String(patch.init?.body))).toMatchObject({ parent_unit: 4 })
  })
})

describe('Vereine im Dachverband', () => {
  const club = (id: number, name: string, city: string, is_active = true) => ({
    id,
    name,
    short_name: '',
    display_name: name,
    founding_year: 1900 + id,
    street: 'Weg 1',
    postal_code: '41468',
    city,
    country: 'Deutschland',
    contact_email: '',
    contact_phone: '',
    website: '',
    is_active,
    logo_url: null,
  })

  it('listet Vereine, blendet inaktive aus und löscht per Deaktivieren', async () => {
    let clubs = [
      {
        ...club(1, 'Hubertus', 'Neuss'),
        department_label_plural: 'Züge',
        units: [
          { id: 11, name: 'Jägerzug', depth: 0 },
          { id: 12, name: 'Jägerzug › Gruppe 1', depth: 1 },
        ],
      },
      club(2, 'Jäger', 'Kaarst'),
      club(3, 'Alt', 'Neuss', false),
    ]
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [
          testOrg({
            type: 'federation',
            type_label: 'Dachverband',
            permissions: ['clubs.manage'],
          }),
        ],
      }),
      'GET /api/orgs/7/clubs/': () => ({ status: 200, body: clubs }),
      'PATCH /api/orgs/7/clubs/2/': (init) => {
        const body = JSON.parse(String(init?.body))
        clubs = clubs.map((c) => (c.id === 2 ? { ...c, ...body } : c))
        return { status: 200, body: clubs[1] }
      },
    })
    const user = userEvent.setup()
    renderPage('/einstellungen/untereinheiten')
    const table = await screen.findByRole('table', { name: 'Vereine' })
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).queryByText('Alt')).not.toBeInTheDocument()
    // Baum darunter: Untereinheiten der Einheiten, nur zum Ansehen
    expect(within(table).getByText('2 Züge')).toBeInTheDocument()
    expect(within(table).getByText('Jägerzug › Gruppe 1')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Filter Ort'), 'Kaarst')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Jäger löschen' }))
    const dialog = await screen.findByRole('alertdialog', { name: '„Jäger“ löschen?' })
    expect(dialog).toHaveTextContent('Daten bleiben')
    await user.click(within(dialog).getByRole('button', { name: 'Löschen' }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Jäger löschen' })).not.toBeInTheDocument(),
    )
    const patch = calls.find((c) => c.key === 'PATCH /api/orgs/7/clubs/2/')
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ is_active: false })
  })
})
