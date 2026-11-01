// Wettbewerbe: schnelles Erfassen beim Kartenschießen (Name, Enter, Punkte, Enter) mit
// Abgleich über die Warteschlange (Standmodus offline, Ralf 2026-11-01). Alles erfunden.
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
const base = '/api/orgs/7/competitions/'

const detail = {
  id: 3,
  title: 'Preisschießen 2027',
  occasion: 'Schützenfest',
  discipline: 'Luftgewehr',
  location: '',
  date: '2027-06-14',
  description: '',
  details: [],
  status: 'laeuft',
  status_label: 'läuft',
  website: 'aus',
  starter_count: 1,
  can_manage: true,
  units: [{ id: 5, name: 'Zug 1' }],
  scorings: [
    {
      id: 11,
      competition: 3,
      name: 'Einzelwertung',
      kind: 'einzel',
      sort_order: 1,
      shots: 5,
      counted_shots: 3,
      max_per_shot: '10.000',
      unit_label: 'Punkte',
      decimals: 0,
      higher_better: true,
      source: null,
      team_mode: 'beste',
      team_size: null,
      prize_places: 10,
      shootoff_shots: 3,
      shootoff_counted: null,
    },
  ],
}

const otto = {
  id: 21,
  name: 'Otto Normal',
  club: '',
  guest: false,
  membership: 2,
  unit: 5,
  unit_name: 'Zug 1',
  number: '',
  out_of_competition: false,
  values: { '11': '25.000' },
}

function renderApp(routes: Record<string, () => { status: number; body?: unknown }>) {
  const org = testOrg({
    permissions: ['competitions.results'],
    modules: ['competitions'],
  })
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    [`GET ${base}3/`]: () => ({ status: 200, body: detail }),
    [`GET ${base}3/starters/`]: () => ({ status: 200, body: [otto] }),
    [`GET ${base}3/members/`]: () => ({
      status: 200,
      body: [
        { membership: 1, name: 'Jürgen Müller', birth_year: 1980, unit: 5, unit_name: 'Zug 1' },
        { membership: 2, name: 'Otto Normal', birth_year: 1975, unit: 5, unit_name: 'Zug 1' },
      ],
    }),
    ...routes,
  })
  render(
    <MemoryRouter initialEntries={['/wettbewerbe/3']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Wettbewerbe erfassen', () => {
  beforeEach(() => localStorage.clear())

  it('Name, Enter, Punkte, Enter: legt den Schützen an und überträgt die Punkte', async () => {
    const calls = renderApp({
      [`POST ${base}3/sync/`]: () => ({
        status: 200,
        body: { results: [{ ok: true }, { ok: true }], conflicts: [], keys: {}, starters: [otto] },
      }),
    })
    const user = userEvent.setup()
    const search = await screen.findByLabelText('Schütze (Name oder Startnummer)')
    await waitFor(() => expect(calls.some((c) => c.key === `GET ${base}3/members/`)).toBe(true))
    // „muel“ findet „Müller“
    await user.type(search, 'muel')
    expect(await screen.findByRole('option', { name: /Jürgen Müller/ })).toBeVisible()
    await user.keyboard('{Enter}')
    const points = await screen.findByLabelText(/Punkte/)
    expect(points).toHaveFocus()
    await user.type(points, '27{Enter}')
    await waitFor(() => expect(calls.some((c) => c.key === `POST ${base}3/sync/`)).toBe(true))
    const sync = calls.find((c) => c.key === `POST ${base}3/sync/`)
    const ops = JSON.parse(String(sync?.init?.body)).ops
    expect(ops[0]).toMatchObject({ op: 'starter', membership: 1 })
    expect(ops[1]).toMatchObject({
      op: 'score',
      scoring: 11,
      value: '27',
      starter: ops[0].client_key,
    })
    // Zurück im Suchfeld für den nächsten Schützen
    expect(screen.getByLabelText('Schütze (Name oder Startnummer)')).toHaveFocus()
  })

  it('warnt, wenn der Schütze schon Punkte hat', async () => {
    renderApp({})
    const user = userEvent.setup()
    const search = await screen.findByLabelText('Schütze (Name oder Startnummer)')
    await user.type(search, 'otto')
    expect(await screen.findByRole('option', { name: /Otto Normal.*schon 25/ })).toBeVisible()
    await user.keyboard('{Enter}')
    await user.type(await screen.findByLabelText(/Punkte/), '28{Enter}')
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('Durch 28 ersetzen?')
  })
})
