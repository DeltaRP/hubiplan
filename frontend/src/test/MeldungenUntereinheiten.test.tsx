// Meldungen Schritt 3: Ausschreibung an die Untereinheiten (alles erfunden).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { DeptEntries } from '../pages/entries/UnitEntries.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const base = '/api/orgs/7/entries/'
const dept = '/api/depts/5/entries/'

const call = {
  id: 4,
  title: 'Preisschießen 2027',
  organizer: 'Testverein',
  organizer_address: '',
  organizer_email: '',
  salutation: '',
  description: '',
  date: '2027-05-09',
  location: 'Vereinsheim',
  deadline: '2027-04-30',
  reference_date: null,
  person_fields: [],
  conditions: {},
  fee_amount: null,
  fee_per: 'mannschaft',
  changes_after_deadline: 'ersatz',
  create_competition: true,
  copied_from: null,
  event_id: null,
  internal: true,
  units: [5, 6],
  strict: false,
  competition: null,
  entry_status: null,
  entry_changed: false,
  entry_question: '',
  event: null,
  calendar: { on: false, can_create: false },
  has_versions: false,
  blocks: [
    {
      id: 9,
      kind: 'mannschaften',
      label: 'Mannschaften',
      help_text: '',
      required: true,
      settings: { min_teams: 1, max_teams: 1, min_size: 2, max_size: 2, positions: [] },
      sort_order: 1,
    },
  ],
}

const options = {
  person_fields: [],
  member_types: [],
  units: [
    { id: 5, name: 'Jägerzug' },
    { id: 6, name: 'Grenadiere' },
  ],
  unit_label: 'Zug',
  signer: 'Max Muster',
  functions: [],
  competitions_enabled: true,
}

const entry = (over: Record<string, unknown> = {}) => ({
  id: 1,
  call: 4,
  status: 'rueckfrage',
  status_label: 'Rückfrage',
  changed: false,
  note: '',
  confirmed_note: '',
  question: 'Zweiter Schütze fehlt',
  unit: 5,
  unit_name: 'Jägerzug',
  competition: null,
  teams: [{ id: 30, block: 9, name: 'Jäger I', sort_order: 1 }],
  persons: [],
  answers: {},
  hints: [],
  versions: [
    {
      id: 70,
      number: 1,
      kind: 'meldung',
      kind_label: 'Meldung',
      channel: 'hubiplan',
      channel_label: 'in HUBIplan',
      sent_to: '',
      changes: [],
      reason: '',
      signed_by: 'Max Muster',
      signed_function: '',
      created_at: '2027-04-01T10:00:00Z',
      shortened: false,
    },
  ],
  after_deadline: false,
  can_pick_members: true,
  competitions_enabled: true,
  ...over,
})

describe('Meldungen an Untereinheiten', () => {
  beforeEach(() => localStorage.clear())

  it('zeigt dem Veranstalter den Eingang und erinnert die Fehlenden', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [
          testOrg({
            permissions: ['entries.submit', 'entries.manage', 'members.view'],
            modules: ['entries'],
          }),
        ],
      }),
      [`GET ${base}calls/4/`]: () => ({ status: 200, body: call }),
      [`GET ${base}calls/4/entry/`]: () => ({ status: 200, body: null }),
      [`GET ${base}options/`]: () => ({ status: 200, body: options }),
      [`GET ${base}calls/4/units/`]: () => ({
        status: 200,
        body: [
          {
            unit: 5,
            name: 'Jägerzug',
            status: 'abgegeben',
            status_label: 'abgegeben',
            changed: false,
            question: '',
            teams: 1,
            persons: 2,
            hints: 0,
            submitted_at: '2027-04-01T10:00:00Z',
            contacts: 1,
          },
          {
            unit: 6,
            name: 'Grenadiere',
            status: null,
            status_label: 'nichts angelegt',
            changed: false,
            question: '',
            teams: 0,
            persons: 0,
            hints: 0,
            submitted_at: null,
            contacts: 1,
          },
        ],
      }),
      [`POST ${base}calls/4/remind/`]: () => ({
        status: 200,
        body: { reminded: ['Grenadiere'], without_contact: [] },
      }),
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
    const user = userEvent.setup()
    expect(await screen.findByText(/1 von 2 Untereinheiten haben gemeldet/)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Grenadiere' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Fehlende erinnern (Mail)' }))
    expect(await screen.findByText('Erinnert: Grenadiere.')).toBeVisible()
    expect(calls.some((c) => c.key === `POST ${base}calls/4/remind/`)).toBe(true)
  })

  it('lässt den Zug nach einer Rückfrage erneut abgeben', async () => {
    const calls = fakeApi({
      [`GET ${dept}calls/4/`]: () => ({ status: 200, body: call }),
      [`GET ${dept}calls/4/entry/`]: () => ({ status: 200, body: entry() }),
      [`GET ${dept}options/`]: () => ({ status: 200, body: options }),
      [`POST ${dept}calls/4/entry/submit/`]: () => ({
        status: 201,
        body: entry({ status: 'abgegeben', status_label: 'abgegeben', question: '' }),
      }),
    })
    render(
      <MemoryRouter initialEntries={['/abteilung/meldungen/4']}>
        <Routes>
          <Route path="/abteilung/meldungen/*" element={<DeptEntries deptId={5} />} />
        </Routes>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    expect(await screen.findByText(/Rückfrage von Testverein: Zweiter Schütze fehlt/)).toBeVisible()
    expect(screen.queryByLabelText('Meldeweg')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Erneut abgeben' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${dept}calls/4/entry/submit/`)).toBe(true),
    )
    expect(await screen.findByRole('heading', { name: /Meldung: abgegeben/ })).toBeVisible()
  })
})
