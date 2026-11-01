// Meldungen: zwei Mannschaften melden, Mitglied aus der Liste wählen, abgeben (alles erfunden).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const base = '/api/orgs/7/entries/'

const call = {
  id: 4,
  title: 'Vergleichsschießen 2027',
  organizer: 'Testbund e. V.',
  organizer_address: 'Schützenweg 1\n12345 Musterstadt',
  organizer_email: 'meldung@testbund.example.org',
  salutation: 'Sehr geehrte Damen und Herren,',
  description: '',
  date: '2027-06-12',
  location: 'Musterstadt',
  deadline: '2027-05-31',
  reference_date: null,
  person_fields: [],
  conditions: {},
  fee_amount: null,
  fee_per: 'mannschaft',
  changes_after_deadline: 'ersatz',
  create_competition: true,
  copied_from: null,
  event_id: null,
  event: null,
  calendar: { on: true, can_create: true },
  entry_status: 'entwurf',
  entry_changed: false,
  has_versions: false,
  blocks: [
    {
      id: 9,
      kind: 'mannschaften',
      label: 'Mannschaften',
      help_text: '',
      required: true,
      settings: { min_teams: 1, max_teams: 2, min_size: 5, max_size: 5, positions: [] },
      sort_order: 1,
    },
  ],
}

const entry = (over: Record<string, unknown> = {}) => ({
  id: 1,
  call: 4,
  status: 'entwurf',
  status_label: 'Entwurf',
  changed: false,
  note: '',
  confirmed_note: '',
  competition: null,
  teams: [{ id: 30, block: 9, name: 'Hubertus I', sort_order: 1 }],
  persons: [],
  answers: {},
  hints: [{ text: 'Hubertus I: 0 von mindestens 5 Personen.', block: 9, person: null, team: 30 }],
  versions: [],
  after_deadline: false,
  can_pick_members: true,
  competitions_enabled: true,
  ...over,
})

const options = {
  person_fields: [{ key: 'birth_date', label: 'Geburtsdatum' }],
  member_types: [],
  units: [],
  unit_label: 'Zug',
  signer: 'Max Muster',
  functions: ['1. Vorsitzender'],
  competitions_enabled: true,
}

function renderApp(
  routes: Record<string, () => { status: number; body?: unknown }>,
  callBody: Record<string, unknown> = call,
) {
  const org = testOrg({ permissions: ['entries.submit', 'members.view'], modules: ['entries'] })
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    [`GET ${base}calls/4/`]: () => ({ status: 200, body: callBody }),
    [`GET ${base}calls/4/entry/`]: () => ({ status: 200, body: entry() }),
    [`GET ${base}options/`]: () => ({ status: 200, body: options }),
    ...routes,
  })
  render(
    <MemoryRouter initialEntries={['/meldungen/4']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Meldungen', () => {
  beforeEach(() => localStorage.clear())

  it('wählt ein Mitglied aus der Liste und gibt die Meldung per E-Mail ab', async () => {
    const calls = renderApp({
      [`GET ${base}calls/4/candidates/?suche=muel`]: () => ({
        status: 200,
        body: [
          {
            membership: 3,
            name: 'Jürgen Müller',
            first_name: 'Jürgen',
            last_name: 'Müller',
            birth_year: 1980,
            unit_name: 'Zug 1',
            active: true,
            taken: false,
          },
        ],
      }),
      [`POST ${base}calls/4/entry/persons/`]: () => ({
        status: 201,
        body: entry({
          persons: [
            {
              id: 50,
              block: 9,
              team: 30,
              membership: 3,
              name: 'Jürgen Müller',
              club: '',
              guest: false,
              position: '',
              substitute: false,
              sort_order: 1,
            },
          ],
          hints: [],
        }),
      }),
      [`POST ${base}calls/4/entry/submit/`]: () => ({
        status: 201,
        body: entry({ status: 'abgegeben', status_label: 'abgegeben', hints: [] }),
      }),
    })
    const user = userEvent.setup()
    expect(await screen.findByText(/0 von mindestens 5 Personen/)).toBeVisible()
    await user.type(screen.getByLabelText('Mitglied hinzufügen'), 'muel')
    await user.click(await screen.findByRole('button', { name: /Müller, Jürgen/ }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${base}calls/4/entry/persons/`)).toBe(true),
    )
    const added = calls.find((c) => c.key === `POST ${base}calls/4/entry/persons/`)
    expect(JSON.parse(String(added?.init?.body))).toMatchObject({
      block: 9,
      team: 30,
      membership: 3,
    })
    expect(await screen.findByText('Jürgen Müller')).toBeVisible()

    // Meldeweg E-Mail ist vorgewählt, weil der Veranstalter eine Adresse hat
    expect(screen.getByLabelText('E-Mail des Veranstalters')).toHaveValue(
      'meldung@testbund.example.org',
    )
    await user.click(screen.getByRole('button', { name: 'Meldung abgeben' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${base}calls/4/entry/submit/`)).toBe(true),
    )
    const submit = calls.find((c) => c.key === `POST ${base}calls/4/entry/submit/`)
    expect(JSON.parse(String(submit?.init?.body))).toMatchObject({
      channel: 'email',
      email: 'meldung@testbund.example.org',
      function: '1. Vorsitzender',
    })
    expect(await screen.findByRole('heading', { name: /Meldung: abgegeben/ })).toBeVisible()
  })

  it('übernimmt eine Zusage zum Termin in die Mannschaft', async () => {
    const event = {
      id: 12,
      title: 'Vergleichsschießen',
      date: '2027-06-12',
      time: null,
      location: 'Musterstadt',
      unit_name: '',
      is_cancelled: false,
      rsvp_enabled: true,
      yes_count: 2,
    }
    const calls = renderApp(
      {
        [`GET ${base}calls/4/responses/`]: () => ({
          status: 200,
          body: {
            yes: [
              {
                membership: 3,
                name: 'Jürgen Müller',
                unit_name: 'Zug 1',
                birth_year: 1980,
                note: 'nur vormittags',
                taken: false,
              },
              {
                membership: 5,
                name: 'Erika Beispiel',
                unit_name: '',
                birth_year: null,
                note: '',
                taken: true,
              },
            ],
            no_count: 1,
          },
        }),
        [`POST ${base}calls/4/entry/persons/`]: () => ({ status: 201, body: entry() }),
      },
      { ...call, event_id: 12, event },
    )
    const user = userEvent.setup()
    expect(await screen.findByRole('heading', { name: 'Zusagen zum Termin' })).toBeVisible()
    expect(await screen.findByText(/2 Zusagen, davon 1 schon in der Meldung/)).toBeVisible()
    expect(screen.getByText('schon gemeldet')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'zu Hubertus I' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${base}calls/4/entry/persons/`)).toBe(true),
    )
    const added = calls.find((c) => c.key === `POST ${base}calls/4/entry/persons/`)
    expect(JSON.parse(String(added?.init?.body))).toEqual({ block: 9, team: 30, membership: 3 })
  })

  it('öffnet eine zurückgezogene Meldung wieder', async () => {
    const versions = [
      {
        id: 1,
        number: 1,
        kind: 'meldung',
        kind_label: 'Meldung',
        channel: 'brief',
        channel_label: 'Brief',
        sent_to: '',
        changes: [],
        reason: '',
        signed_by: 'Max Muster',
        signed_function: '',
        created_at: '2027-05-01T10:00:00Z',
        shortened: false,
      },
      {
        id: 2,
        number: 2,
        kind: 'rueckzug',
        kind_label: 'Rückzug',
        channel: 'brief',
        channel_label: 'Brief',
        sent_to: '',
        changes: [],
        reason: '',
        signed_by: 'Max Muster',
        signed_function: '',
        created_at: '2027-05-02T10:00:00Z',
        shortened: false,
      },
    ]
    const calls = renderApp({
      [`GET ${base}calls/4/entry/`]: () => ({
        status: 200,
        body: entry({ status: 'zurueckgezogen', status_label: 'zurückgezogen', versions }),
      }),
      [`POST ${base}calls/4/entry/reopen/`]: () => ({ status: 200, body: entry({ versions }) }),
    })
    const user = userEvent.setup()
    expect(await screen.findByRole('button', { name: 'Meldung löschen' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Wieder öffnen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${base}calls/4/entry/reopen/`)).toBe(true),
    )
    // Wieder Entwurf: die nächste Abgabe ist eine neue Meldung
    expect(await screen.findByRole('heading', { name: 'Meldung abgeben' })).toBeVisible()
  })
})
