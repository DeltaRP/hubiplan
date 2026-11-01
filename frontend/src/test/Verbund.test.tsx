// Einstellungen › Verbund: Kopplungscode, Vorschau, Bestätigen, Datenfluss (erfundene Daten).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider, useOrg } from '../org/OrgContext.tsx'
import { PeeringPage } from '../pages/settings/PeeringPage.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const session = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})

const unitPacket = {
  key: 'unit',
  label: 'Stammdaten der Einheit (Name, Bezeichnung, Logo, Anschrift, Kontakt)',
  personal: 'nur die Kontaktdaten der Einheit',
  levels: [{ value: 'on', label: 'an' }],
  value: 'on',
}

const pending = {
  id: 3,
  direction: 'child',
  state: 'pending',
  state_label: 'Anfrage eingegangen, wartet auf Bestätigung',
  remote: {
    id: 40,
    name: 'Schützenverein Beispiel',
    logo_url: null,
    base_url: 'https://verein.example',
    country: 'DE',
    fingerprint: 'AAAA BBBB CCCC DDDD EEEE FFFF',
  },
  send: [unitPacket],
  receive: [{ ...unitPacket, value: 'on' }],
  last_sync_at: null,
  last_contact_at: null,
  last_error: '',
  error_since: null,
  queued: 0,
  received: {},
  invoices: [],
  register: null,
  transfers: [],
  options: {},
  move: null,
  keys: null,
  keys_changed_at: null,
  wants_more: [],
  circulars: [],
  created_at: '2026-10-30T05:00:00Z',
  activated_at: null,
  ended_at: null,
}

function WhenActive() {
  const { active } = useOrg()
  return active ? <PeeringPage /> : null
}

function renderPage(routes: Parameters<typeof fakeApi>[0], type = 'federation') {
  const calls = fakeApi({
    'GET /_allauth/browser/v1/auth/session': session,
    'GET /api/me/organizations/': () => ({
      status: 200,
      body: [testOrg({ type, permissions: ['org.edit', 'peering.manage', 'members.edit'] })],
    }),
    ...routes,
  })
  render(
    <MemoryRouter>
      <AuthProvider>
        <OrgProvider>
          <WhenActive />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

const overview = (extra: object) => ({
  enabled: true,
  can_offer: false,
  can_join: false,
  instance: { base_url: 'https://verband.example', fingerprint: '1111 2222 3333 4444 5555 6666' },
  couplings: [],
  ...extra,
})

describe('Verbund', () => {
  it('ohne eingeschalteten Verbund nur ein Hinweis', async () => {
    renderPage({
      'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ enabled: false }) }),
    })
    expect(await screen.findByText(/nicht eingeschaltet/)).toBeInTheDocument()
    expect(screen.queryByText('Kopplungscode erzeugen')).not.toBeInTheDocument()
  })

  it('Code erzeugen und eine Anfrage bestätigen', async () => {
    const calls = renderPage({
      'GET /api/orgs/7/peering/': () => ({
        status: 200,
        body: overview({ can_offer: true, couplings: [pending] }),
      }),
      'POST /api/orgs/7/peering/codes/': () => ({
        status: 201,
        body: { code: 'HUBIPLAN1-abc', expires_at: '2026-11-01T05:00:00Z' },
      }),
      'POST /api/orgs/7/peering/couplings/3/accept/': () => ({
        status: 200,
        body: { ...pending, state: 'active', state_label: 'aktiv' },
      }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Kopplungscode erzeugen' }))
    expect(await screen.findByDisplayValue('HUBIPLAN1-abc')).toBeInTheDocument()
    const card = screen.getByRole('heading', { name: /Schützenverein Beispiel/ }).parentElement!
    expect(within(card).getByText(/AAAA BBBB/)).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Bestätigen' }))
    const accept = calls.find((c) => c.key === 'POST /api/orgs/7/peering/couplings/3/accept/')
    expect(JSON.parse(String(accept?.init?.body))).toEqual({ packets: { unit: 'on' } })
  })

  it('angekündigten Umzug nur mit Fingerabdruck bestätigen', async () => {
    const moving = {
      ...pending,
      state: 'moving',
      state_label: 'Umzug angekündigt, wartet auf Bestätigung',
      move: {
        from: 'https://verein.example',
        base_url: 'https://neu.example',
        fingerprint: '9999 8888 7777',
        country: 'DE',
        at: '2026-10-30T10:00:00Z',
      },
    }
    const calls = renderPage({
      'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ couplings: [moving] }) }),
      'POST /api/orgs/7/peering/couplings/3/move-confirm/': () => ({
        status: 200,
        body: { ...pending, state: 'active', state_label: 'aktiv' },
      }),
    })
    const user = userEvent.setup()
    expect(await screen.findByText(/meldet einen Umzug/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lösen' })).not.toBeInTheDocument()
    const confirm = screen.getByRole('button', { name: 'Umzug bestätigen' })
    expect(confirm).toBeDisabled()
    await user.type(screen.getByLabelText('Fingerabdruck von der anderen Seite'), '9999 8888 7777')
    await user.click(confirm)
    const call = calls.find((c) => c.key === 'POST /api/orgs/7/peering/couplings/3/move-confirm/')
    expect(JSON.parse(String(call?.init?.body))).toEqual({ fingerprint: '9999 8888 7777' })
  })

  it('Notfallwechsel der Gegenstelle: Hinweis, bestätigen tut die Plattform', async () => {
    const withKeys = {
      ...pending,
      state: 'active',
      state_label: 'aktiv',
      keys: { fingerprint: 'AAAA BBBB CCCC', at: '2026-10-30T10:00:00Z' },
    }
    renderPage({
      'GET /api/orgs/7/peering/': () => ({
        status: 200,
        body: overview({ couplings: [withKeys] }),
      }),
    })
    expect(await screen.findByText(/meldet einen Notfallwechsel/)).toBeInTheDocument()
    expect(screen.getByText(/bestätigt die\s+Plattformverwaltung/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Neue Schlüssel bestätigen' })).toBeNull()
  })

  it('mehr Daten der Gegenseite erst nach Zustimmung', async () => {
    const wanting = {
      ...pending,
      state: 'active',
      state_label: 'aktiv',
      wants_more: [
        {
          key: 'members',
          label: 'Mitglieder',
          level: 'b',
          level_label: 'namentlich',
          accepted: 'a',
          accepted_label: 'Zahlen',
          personal: 'Namen und Geburtsdaten',
        },
      ],
    }
    const calls = renderPage({
      'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ couplings: [wanting] }) }),
      'POST /api/orgs/7/peering/couplings/3/more-accept/': () => ({
        status: 200,
        body: { ...wanting, wants_more: [] },
      }),
    })
    const user = userEvent.setup()
    expect(await screen.findByText(/möchte mehr senden/)).toBeInTheDocument()
    expect(screen.getByText(/namentlich \(bisher Zahlen\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Annehmen' }))
    const call = calls.find((c) => c.key === 'POST /api/orgs/7/peering/couplings/3/more-accept/')
    expect(JSON.parse(String(call?.init?.body))).toEqual({ key: 'members' })
  })

  it('Code prüfen zeigt die Gegenseite vor dem Koppeln', async () => {
    const calls = renderPage(
      {
        'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ can_join: true }) }),
        'POST /api/orgs/7/peering/inspect/': () => ({
          status: 200,
          body: {
            remote: {
              name: 'Bürgerbund Musterstadt',
              base_url: 'https://verband.example',
              country: 'DE',
              fingerprint: '1111 2222',
            },
            send: [unitPacket],
            receive: [{ key: 'unit', label: 'Stammdaten der Einheit', personal: '' }],
          },
        }),
      },
      'club',
    )
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Kopplungscode'), 'HUBIPLAN1-xyz')
    await user.click(screen.getByRole('button', { name: 'Prüfen' }))
    expect(await screen.findByText('Bürgerbund Musterstadt')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Koppeln' })).toBeInTheDocument()
    const inspect = calls.find((c) => c.key === 'POST /api/orgs/7/peering/inspect/')
    expect(JSON.parse(String(inspect?.init?.body))).toEqual({ code: 'HUBIPLAN1-xyz' })
  })

  it('Eingangsrechnung als bezahlt melden', async () => {
    const above = {
      ...pending,
      id: 5,
      direction: 'parent',
      state: 'active',
      state_label: 'aktiv',
      remote: { ...pending.remote, name: 'Bürgerbund Musterstadt' },
      received: {
        members: {
          level: 'a',
          on: '2026-10-30',
          total: 3,
          counts: [
            { kind: 'active', birth: '1980-05', n: 2 },
            { kind: 'passive', birth: '1990-01', n: 1 },
          ],
        },
        results: {
          competitions: [
            {
              uid: '12',
              title: 'Bundesmeisterschaft',
              date: '2026-09-20',
              location: 'Musterstadt',
              scorings: [
                {
                  name: 'Vereine',
                  kind: 'einheit',
                  field: 2,
                  rows: [
                    { place: 1, name: 'Anderer Verein', value: '290', own: false },
                    { place: 2, name: 'Schützenverein Beispiel', value: '280', own: true },
                  ],
                },
              ],
            },
          ],
        },
      },
      invoices: [
        {
          id: 9,
          incoming: true,
          number: '2026-0001',
          subject: 'Verbandsbeitrag 2026',
          date: '2026-10-30',
          due_date: '2026-11-13',
          total: '30.00',
          status: 'open',
          status_label: 'offen',
          paid: '0.00',
          settled: false,
          paid_reported_on: null,
          booking_id: null,
          lines: [],
          bank: { holder: 'Bürgerbund Musterstadt', iban: 'DE89370400440532013000' },
          invoice_id: null,
          download_url: '/api/orgs/7/peering/couplings/5/invoices/9/file/',
        },
      ],
    }
    const calls = renderPage(
      {
        'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ couplings: [above] }) }),
        'POST /api/orgs/7/peering/couplings/5/invoices/9/paid/': () => ({
          status: 200,
          body: { ...above.invoices[0], paid_reported_on: '2026-10-30' },
        }),
      },
      'club',
    )
    const user = userEvent.setup()
    expect(await screen.findByText(/Gemeldete Mitglieder/)).toHaveTextContent(
      '3 (2 aktiv, 1 passiv)',
    )
    expect(screen.getByText('Wettbewerbsergebnisse von oben: 1')).toBeInTheDocument()
    expect(screen.getByText('2. Schützenverein Beispiel (280)').tagName).toBe('STRONG')
    expect(screen.getByText('Bundesmeisterschaft')).toBeInTheDocument()
    expect(screen.getByText('Eingangsrechnungen')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'bezahlt melden' }))
    expect(screen.getByText(/IBAN DE89370400440532013000/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Melden' }))
    const report = calls.find(
      (c) => c.key === 'POST /api/orgs/7/peering/couplings/5/invoices/9/paid/',
    )
    expect(JSON.parse(String(report?.init?.body))).toHaveProperty('date')
  })

  it('Klärfall: dieselbe Person wählen', async () => {
    const child = {
      ...pending,
      state: 'active',
      state_label: 'aktiv',
      register: {
        counts: { active: 2, unclear: 1, withdrawn: 0 },
        unclear: [
          {
            id: 11,
            last_name: 'Aktiv',
            first_name: 'Anna',
            birth_date: '1980-05-17',
            candidates: [
              {
                id: 99,
                name: 'Anna Aktiv',
                birth_date: '1980-05-17',
                member_number: 12,
                units: ['Nachbarverein Musterstadt'],
              },
            ],
          },
        ],
        conflicts: [],
      },
    }
    const calls = renderPage({
      'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ couplings: [child] }) }),
      'POST /api/orgs/7/peering/couplings/3/members/11/resolve/': () => ({
        status: 200,
        body: child,
      }),
    })
    const user = userEvent.setup()
    expect(await screen.findByText(/Ist das dieselbe Person/)).toBeInTheDocument()
    expect(screen.getByText(/Nachbarverein Musterstadt/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'dieselbe Person' }))
    const call = calls.find(
      (c) => c.key === 'POST /api/orgs/7/peering/couplings/3/members/11/resolve/',
    )
    expect(JSON.parse(String(call?.init?.body))).toEqual({ person: 99 })
  })

  it('Wechselanfrage des Dachverbands: Austritt bestätigen', async () => {
    const above = {
      ...pending,
      id: 6,
      direction: 'parent',
      state: 'active',
      state_label: 'aktiv',
      remote: { ...pending.remote, name: 'Bürgerbund Musterstadt' },
      send: [
        unitPacket,
        {
          key: 'members',
          label: 'Mitgliedermeldung an die Einheit darüber',
          personal: '',
          levels: [
            { value: 'a', label: 'Stufe A' },
            { value: 'b', label: 'Stufe B' },
          ],
          value: 'b',
        },
      ],
      transfers: [
        {
          id: 21,
          role: 'from',
          status: 'pending',
          status_label: 'offen',
          name: 'Anna Aktiv',
          to_unit: 'Nachbarverein Musterstadt',
          entry_date: '2026-11-01',
          member_type_name: 'aktiv',
          message: 'Umzug',
          response: '',
          created_at: '2026-10-30T06:00:00Z',
          decided_at: null,
          member_id: 5,
        },
      ],
    }
    const calls = renderPage(
      {
        'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ couplings: [above] }) }),
        'GET /api/orgs/7/member-types/': () => ({ status: 200, body: [] }),
        'POST /api/orgs/7/peering/couplings/6/transfers/21/decide/': () => ({
          status: 200,
          body: above,
        }),
      },
      'club',
    )
    const user = userEvent.setup()
    expect(
      await screen.findByText(/möchte zu Nachbarverein Musterstadt wechseln/),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Austritt bestätigen' }))
    const call = calls.find(
      (c) => c.key === 'POST /api/orgs/7/peering/couplings/6/transfers/21/decide/',
    )
    expect(JSON.parse(String(call?.init?.body))).toEqual({ decision: 'exit', response: '' })
  })

  it('Umzug: neue Instanz prüfen, Fingerabdruck eingeben, melden', async () => {
    const active = { ...pending, state: 'active', state_label: 'aktiv' }
    const calls = renderPage({
      'GET /api/orgs/7/peering/': () => ({ status: 200, body: overview({ couplings: [active] }) }),
      'POST /api/orgs/7/peering/move/': (init) => {
        const body = JSON.parse(String(init?.body))
        return body.fingerprint
          ? { status: 200, body: { done: 1, failed: [] } }
          : { status: 200, body: { base_url: 'https://neu.example', fingerprint: '9999 8888' } }
      },
    })
    const user = userEvent.setup()
    await user.click(await screen.findByText('Umzug auf eine andere Instanz'))
    await user.type(screen.getByLabelText('Adresse der neuen Instanz'), 'https://neu.example')
    await user.click(screen.getByRole('button', { name: 'Neue Instanz prüfen' }))
    expect(await screen.findByText('9999 8888')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/Fingerabdruck zur Bestätigung/), '9999 8888')
    await user.click(screen.getByRole('button', { name: 'Umzug melden' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Umzug melden' }),
    )
    expect(
      await screen.findByText(/1 Gegenstelle\(n\) haben den Umzug übernommen/),
    ).toBeInTheDocument()
    const moves = calls.filter((c) => c.key === 'POST /api/orgs/7/peering/move/')
    expect(JSON.parse(String(moves[1]?.init?.body))).toEqual({
      base_url: 'https://neu.example',
      fingerprint: '9999 8888',
    })
  })
})
