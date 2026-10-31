import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const ORG = testOrg({ permissions: ['members.view', 'members.edit'] })
const base = '/api/orgs/7'

const row = {
  id: 11,
  last_name: 'Muster',
  first_name: 'Erika',
  birth_date: '1980-05-17',
  club_number: '1001',
  member_number: 5,
  member_type: 'aktiv',
  status: 'active',
  entry_date: '2015-03-01',
  exit_date: null,
  departments: ['Turnen'],
  email: 'erika@beispiel.test',
  phone: '',
  street: '',
  postal_code: '',
  city: '',
}

function common() {
  return {
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
    [`GET ${base}/member-types/`]: () => ({
      status: 200,
      body: [
        {
          id: 3,
          name: 'aktiv',
          reported: true,
          active: true,
          counts_for_duration: true,
          is_archived: false,
          sort_order: 0,
          in_use: true,
        },
      ],
    }),
    [`GET ${base}/departments/`]: () => ({ status: 200, body: [] }),
  }
}

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

describe('Mitgliederliste', () => {
  it('zeigt Mitglieder mit Spalten', async () => {
    fakeApi({
      ...common(),
      [`GET ${base}/members/?status=aktiv&sortierung=name&page=1&page_size=50`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [row] },
      }),
    })
    renderAt('/mitglieder')
    expect(await screen.findByText('Muster, Erika')).toBeInTheDocument()
    expect(screen.getByText('1 Mitglied')).toBeInTheDocument()
    expect(screen.getByText('Turnen')).toBeInTheDocument()
  })
})

describe('Aufnahme', () => {
  it('schlägt Dublette vor und verknüpft', async () => {
    const calls = fakeApi({
      ...common(),
      [`GET ${base}/members/duplicates/?name=Muster&vorname=Erika&geburtsdatum=1980-05-17`]:
        () => ({
          status: 200,
          body: [
            {
              id: 42,
              last_name: 'Muster',
              first_name: 'Erika',
              birth_date: '1980-05-17',
              member_number: 5,
              clubs: null,
              already_member_here: false,
            },
          ],
        }),
      [`POST ${base}/members/admit/`]: () => ({ status: 201, body: { id: 99 } }),
      [`GET ${base}/members/99/`]: () => ({ status: 404, body: { detail: 'Nicht gefunden.' } }),
    })
    renderAt('/mitglieder/neu')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Name'), 'Muster')
    await user.type(screen.getByLabelText('Vorname'), 'Erika')
    await user.type(screen.getByLabelText('Geburtsdatum'), '1980-05-17')
    await user.click(screen.getByRole('button', { name: 'Weiter' }))

    expect(await screen.findByText('Mögliche Treffer')).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /Verbandsnr\. 5/ }))
    await user.selectOptions(screen.getByLabelText('Mitgliedsart'), '3')
    await user.type(screen.getByLabelText(/E-Mail-Adresse \(optional\)/), 'erika@beispiel.test')
    expect(
      screen.getByText(/Ohne E-Mail erhält das Mitglied Schreiben per Brief/),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText('Straße und Hausnummer'), 'Weg 1')
    await user.type(screen.getByLabelText('PLZ'), '12345')
    await user.type(screen.getByLabelText('Ort'), 'Musterstadt')
    await user.click(screen.getByRole('button', { name: 'Aufnehmen' }))

    await screen.findByText(/Nicht gefunden|Lädt/)
    const admit = calls.find((c) => c.key === `POST ${base}/members/admit/`)!
    const body = JSON.parse(String(admit.init?.body))
    expect(body.person).toBe(42)
    expect(body.member_type).toBe(3)
    expect(body.last_name).toBeUndefined()
  })
})

const detail = {
  id: 11,
  person_id: 42,
  last_name: 'Muster',
  first_name: 'Erika',
  birth_date: '1980-05-17',
  club_number: '',
  contact: {
    email: 'e@beispiel.test',
    phone: '',
    street: 'Weg 1',
    postal_code: '1',
    city: 'x',
    country: 'Deutschland',
  },
  contact_shared: true,
  status: 'active',
  current_type: {
    id: 1,
    member_type: 3,
    member_type_name: 'aktiv',
    active: true,
    reported: true,
    valid_from: '2015-03-01',
    valid_until: null,
  },
  periods: [
    {
      id: 5,
      entry_date: '2015-03-01',
      exit_date: null,
      exit_reason: '',
      exit_reason_label: '',
      note: '',
    },
  ],
  type_history: [],
  departments: [],
  department_roles: [],
  board_roles: [],
  federation: null,
  exit_reasons: [
    { value: 'exit', label: 'Austritt' },
    { value: 'death', label: 'Tod' },
  ],
  purged: false,
  purge_due: null,
  duration: { club: { days: 3000, years: 8, next: null }, federation: null },
  photo: { approved: null, pending: null },
  photo_consent_at: null,
  photo_consent_source: '',
  other_memberships: null,
}

describe('Mitgliedsakte', () => {
  it('fern geführt: Stammdaten gesperrt, Korrektur vorschlagen', async () => {
    const calls = fakeApi({
      ...common(),
      [`GET ${base}/members/11/`]: () => ({
        status: 200,
        body: { ...detail, managed_by: { id: 3, name: 'Jägerzug' } },
      }),
      [`POST ${base}/peering/members/11/suggest/`]: () => ({ status: 202, body: {} }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    expect(
      await screen.findByText(/pflegt Jägerzug auf einer eigenen HUBIplan-Instanz/),
    ).toBeInTheDocument()
    expect(screen.getAllByLabelText(/^Vorname/)[0]).toBeDisabled()
    const fields = screen.getAllByLabelText(/^Vorname/)
    await user.clear(fields[1])
    await user.type(fields[1], 'Erica')
    await user.click(screen.getByRole('button', { name: 'Korrektur vorschlagen' }))
    expect(await screen.findByText('Der Vorschlag ist an Jägerzug unterwegs.')).toBeInTheDocument()
    const post = calls.find((c) => c.key === `POST ${base}/peering/members/11/suggest/`)
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ first_name: 'Erica' })
  })

  it('erfasst einen Austritt', async () => {
    const calls = fakeApi({
      ...common(),
      [`GET ${base}/members/11/`]: () => ({ status: 200, body: detail }),
      [`POST ${base}/members/11/exit/`]: () => ({
        status: 200,
        body: { ...detail, status: 'former', purge_due: '2026-12-31' },
      }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('link', { name: 'Mitgliedschaft' }))
    await user.click(await screen.findByRole('button', { name: 'Austritt erfassen' }))
    await user.selectOptions(screen.getByLabelText('Grund'), 'death')
    await user.click(screen.getByRole('button', { name: 'Austritt speichern' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Austritt erfassen' }))
    expect(await screen.findByRole('button', { name: 'Wiedereintritt' })).toBeInTheDocument()
    expect(screen.getByText(/31\.12\.2026/)).toBeInTheDocument()
    const call = calls.find((c) => c.key === `POST ${base}/members/11/exit/`)!
    expect(JSON.parse(String(call.init?.body)).exit_reason).toBe('death')
  })

  it('nennt den Namen des Dachverbands nur einmal', async () => {
    fakeApi({
      ...common(),
      [`GET ${base}/members/11/`]: () => ({
        status: 200,
        body: {
          ...detail,
          federation: {
            name: 'Testbund von 1855 e.V.',
            is_member: true,
            member_number: 1,
            entry_date: '2007-01-01',
            entry_date_manual: false,
          },
        },
      }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('link', { name: 'Mitgliedschaft' }))
    expect(
      await screen.findByRole('heading', { name: 'Testbund von 1855 e.V.' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Mitglied')).toBeInTheDocument()
    // Die Verbandsnummer steht in der Akte nicht (weder im Kopf noch beim Dachverband).
    expect(screen.queryByText(/Verbandsnr\./)).not.toBeInTheDocument()
    expect(screen.getByText(/^Eintritt:/)).toHaveTextContent(/\(berechnet\)$/)
    expect(screen.queryByText(/Mitglied im|Eintritt in/)).not.toBeInTheDocument()
  })
})

describe('Export', () => {
  it('exportiert die gefilterte Liste mit gewählten Spalten', async () => {
    const org = testOrg({ permissions: ['members.view', 'export.run'] })
    const calls = fakeApi({
      ...common(),
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${base}/members/?status=aktiv&sortierung=name&page=1&page_size=50`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [row] },
      }),
      [`GET ${base}/export-columns/`]: () => ({
        status: 200,
        body: {
          members: [
            { key: 'last_name', label: 'Name' },
            { key: 'first_name', label: 'Vorname' },
            { key: 'email', label: 'E-Mail' },
          ],
          jubilees: [],
        },
      }),
      [`GET ${base}/export-templates/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}/exports/`]: () => ({ status: 201, body: { id: 5, status: 'pending' } }),
      [`GET ${base}/exports/5/`]: () => ({
        status: 200,
        body: { id: 5, status: 'done', row_count: 1, file_name: 'Mitgliederliste.xlsx' },
      }),
    })
    renderAt('/mitglieder')
    const user = userEvent.setup()
    await screen.findByText('Muster, Erika')
    await user.click(screen.getByRole('button', { name: 'Export' }))
    await user.click(await screen.findByRole('checkbox', { name: 'E-Mail' }))
    await user.click(screen.getByRole('button', { name: 'Export erstellen' }))
    expect(await screen.findByRole('link', { name: /Mitgliederliste.xlsx/ })).toHaveAttribute(
      'href',
      `${base}/exports/5/download/`,
    )
    const post = calls.find((c) => c.key === `POST ${base}/exports/`)!
    const body = JSON.parse(String(post.init?.body))
    expect(body.columns).toEqual(['last_name', 'first_name'])
    expect(body.filters.status).toBe('aktiv')
  })
})

describe('Dachverband', () => {
  it('zeigt Mitglieder aller Vereine nur mit Freigabe', async () => {
    const fed = testOrg({
      id: 2,
      name: 'Testbund',
      type: 'federation',
      type_label: 'Dachverband',
      parent_name: null,
      permissions: ['members.view'],
      modules: ['members'],
      federation_member_access: 'read',
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [fed] }),
      'GET /api/orgs/2/federation/clubs/': () => ({
        status: 200,
        body: [{ id: 7, name: 'TV Beispielhausen' }],
      }),
      'GET /api/orgs/2/federation/members/?status=aktiv&sortierung=name&page=1&page_size=50':
        () => ({
          status: 200,
          body: {
            count: 1,
            next: null,
            previous: null,
            results: [{ ...row, club: 'TV Beispielhausen', club_id: 7 }],
          },
        }),
    })
    renderAt('/mitglieder')
    expect(await screen.findByText('Muster, Erika')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Mitglieder im Dachverband' })).toBeInTheDocument()
    expect(screen.getByText(/nur lesen/)).toBeInTheDocument()
  })

  it('ohne Freigabe kein Menüpunkt Mitglieder', async () => {
    const fed = testOrg({
      id: 2,
      name: 'Testbund',
      type: 'federation',
      federation_member_access: 'none',
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [fed] }),
    })
    renderAt('/')
    await screen.findByRole('heading', { name: 'Testbund' })
    expect(screen.getByRole('navigation', { name: 'Module' })).not.toHaveTextContent('Mitglieder')
  })
})

describe('Foto-Upload-Link', () => {
  it('zeigt nur Vorname und Verein', async () => {
    fakeApi({
      [SESSION]: () => ({ status: 401, body: { status: 401, data: { flows: [] } } }),
      'GET /api/public/photo/abc123/': () => ({
        status: 200,
        body: {
          first_name: 'Erika',
          organization: 'TV Beispielhausen',
          logo_url: null,
          theme: {
            primary: '#123e7a',
            on_primary: '#ffffff',
            accent: '#e0a526',
            on_accent: '#1d2421',
          },
          expires_at: '2026-11-07T12:00:00Z',
          needs_approval: false,
        },
      }),
    })
    renderAt('/foto/abc123')
    expect(await screen.findByRole('heading', { name: 'Hallo Erika!' })).toBeInTheDocument()
    expect(screen.getByText(/Ich willige ein, dass TV Beispielhausen/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Foto hochladen' })).toBeDisabled()
  })

  it('meldet ungültige Links', async () => {
    fakeApi({
      [SESSION]: () => ({ status: 401, body: { status: 401, data: { flows: [] } } }),
      'GET /api/public/photo/alt/': () => ({ status: 404, body: { detail: 'Nicht gefunden.' } }),
    })
    renderAt('/foto/alt')
    expect(await screen.findByText(/nicht \(mehr\) gültig/)).toBeInTheDocument()
  })
})
