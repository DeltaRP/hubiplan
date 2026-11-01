// Vogelschießen im Standmodus: wer dran ist, Schuss, Pfand gefallen, Rückgängig, auch ohne
// Empfang (Rechnung auf dem Gerät), und der Standzugang ohne Anmeldung. Alles erfunden.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { drawFree, project } from '../api/bird.ts'
import type { BirdState, Starter, SyncOp } from '../api/competitions.ts'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/competitions/'

function starter(id: number, name: string, number: string, extra: Partial<Starter> = {}): Starter {
  return {
    id,
    name,
    club: '',
    guest: false,
    membership: id,
    unit: 5,
    unit_name: 'Zug 1',
    number,
    out_of_competition: false,
    presence: '',
    drawn_how: 'hut',
    key: null,
    values: {},
    ...extra,
  }
}

const prize = (id: number, name: string) => ({
  id,
  name,
  sort_order: id,
  award: '',
  fallen: false,
  winner: null,
  winner_name: '',
  unit_name: '',
  club: '',
  number: '',
  shot_number: null,
  shots_for: null,
  live: false,
  fallen_at: null,
})

function bird(extra: Partial<BirdState> = {}): BirdState {
  return {
    prizes: [prize(1, 'Kopf'), prize(2, 'linker Flügel'), prize(3, 'Schweif')],
    order: [],
    upcoming: [],
    shots: 0,
    live_shots: 0,
    since_last: 0,
    round: 0,
    last: null,
    recent: [],
    draw: { missing: [], duplicates: [], gaps: [] },
    stats: {
      shots: 0,
      starters: 3,
      members: 3,
      guests: 0,
      rounds: null,
      duration_minutes: null,
      started: null,
      per_unit: [],
    },
    ...extra,
  }
}

const starters = [
  starter(21, 'Max Muster', '2'),
  starter(22, 'Erika Beispiel', '1'),
  starter(23, 'Otto Normal', '3'),
]

describe('Reihenfolge auf dem Gerät', () => {
  const shot = (s: number | string, hits: number[] = [], key = String(Math.random())): SyncOp => ({
    op: 'shot',
    starter: s,
    hits,
    client_key: key,
    at: '2027-06-13T10:00:00Z',
  })

  it('zählt Schüsse, Runden und Pfänder; wer ein Pfand hat, scheidet aus', () => {
    let view = project(bird(), [], starters, true)
    expect(view.upcoming).toEqual([22, 21, 23])
    const ops = [shot(22), shot(21), shot(23), shot(22), shot(21, [1], 'k')]
    view = project(bird(), ops, starters, true)
    expect(view.total).toBe(5)
    expect(view.round).toBe(2)
    expect(view.prizes[0]).toMatchObject({
      fallen: true,
      winner_name: 'Max Muster',
      shot_number: 5,
      shots_for: 5,
    })
    expect(view.upcoming).toEqual([23, 22])
    expect(view.sinceLast).toBe(0)
    // Rückgängig nimmt den Schuss und das Pfand zurück
    view = project(bird(), [...ops, { op: 'undo', client_key: 'k' }], starters, true)
    expect(view.total).toBe(4)
    expect(view.prizes[0].fallen).toBe(false)
    expect(view.upcoming[0]).toBe(21)
  })

  it('setzt auf dem Stand des Servers auf', () => {
    const state = bird({
      live_shots: 7,
      round: 3,
      recent: [{ number: 7, starter: 23, client_key: null }],
    })
    const view = project(state, [shot(22)], starters, true)
    expect(view.total).toBe(8)
    expect(view.round).toBe(4)
    expect(view.upcoming[0]).toBe(21)
  })

  it('zieht nur freie Nummern', () => {
    const s = [starter(1, 'A', '1'), starter(2, 'B', ''), starter(3, 'C', '3')]
    expect(drawFree(s, 2, () => 0)).toBe(2)
    expect(drawFree([starter(1, 'A', '1')], undefined, () => 0)).toBe(2)
  })
})

const detail = {
  id: 4,
  title: 'Vogelschießen 2027',
  form: 'vogel',
  own: true,
  organizer: '',
  occasion: '',
  discipline: 'Armbrust',
  location: '',
  date: '2027-06-13',
  description: '',
  details: [],
  status: 'laeuft',
  status_label: 'läuft',
  website: 'aus',
  drop_out: true,
  fixed_order: false,
  total_shots: null,
  starter_count: 3,
  can_manage: true,
  units: [{ id: 5, name: 'Zug 1' }],
  scorings: [],
  prizes: [
    { id: 1, name: 'Kopf', award: '', sort_order: 1 },
    { id: 2, name: 'linker Flügel', award: '', sort_order: 2 },
    { id: 3, name: 'Schweif', award: '', sort_order: 3 },
  ],
}

function syncBody(state = bird()) {
  return {
    status: 200,
    body: { results: [], conflicts: [], keys: {}, starters, status: 'laeuft', bird: state },
  }
}

describe('Vogelschießen am Stand', () => {
  beforeEach(() => localStorage.clear())

  it('Schuss und Pfand gefallen gehen in die Warteschlange und an den Server', async () => {
    const org = testOrg({ permissions: ['competitions.results'], modules: ['competitions'] })
    const seen: BirdState['recent'] = []
    const calls = fakeApi({
      [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${base}4/`]: () => ({ status: 200, body: detail }),
      [`GET ${base}4/starters/`]: () => ({ status: 200, body: starters }),
      [`GET ${base}4/members/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}4/bird/`]: () => ({ status: 200, body: bird() }),
      [`POST ${base}4/sync/`]: (init) => {
        // Server merkt sich die Schüsse (ohne Pfänder, die zählt hier nur das Gerät)
        for (const op of JSON.parse(String(init?.body)).ops as SyncOp[])
          if (op.op === 'shot')
            seen.push({
              number: seen.length + 1,
              starter: op.starter as number,
              client_key: op.client_key,
            })
        return syncBody(
          bird({ live_shots: seen.length, recent: [...seen], round: seen.length ? 1 : 0 }),
        )
      },
    })
    render(
      <MemoryRouter initialEntries={['/stand/7/4']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    // Erika hat Los 1 und ist dran
    expect(await screen.findByText('Erika Beispiel', { selector: 'strong' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Schuss' }))
    await user.click(screen.getByRole('button', { name: 'Pfand gefallen' }))
    await user.click(await screen.findByRole('button', { name: /Kopf/ }))
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    await waitFor(() => {
      const ops = calls
        .filter((c) => c.key === `POST ${base}4/sync/`)
        .flatMap((c) => JSON.parse(String(c.init?.body)).ops as SyncOp[])
      expect(ops.filter((o) => o.op === 'shot')).toHaveLength(2)
    })
    const ops = calls
      .filter((c) => c.key === `POST ${base}4/sync/`)
      .flatMap((c) => JSON.parse(String(c.init?.body)).ops as SyncOp[])
      .filter((o) => o.op === 'shot')
    expect(ops[0]).toMatchObject({ starter: 22, hits: [] })
    expect(ops[1]).toMatchObject({ starter: 21, hits: [1] })
  })

  it('Standzugang öffnet den Wettbewerb ohne Anmeldung', async () => {
    const pub = '/api/public/stand/schluessel-1/'
    fakeApi({
      [SESSION]: () => ({ status: 401, body: { status: 401 } }),
      [`GET ${pub}`]: () => ({
        status: 200,
        body: {
          ...detail,
          can_manage: false,
          stand_access: { label: 'Tablet 1', expires_at: '2027-06-13T21:59:59Z' },
        },
      }),
      [`GET ${pub}starters/`]: () => ({ status: 200, body: starters }),
      [`GET ${pub}members/`]: () => ({ status: 200, body: [] }),
      [`POST ${pub}sync/`]: () => syncBody(),
    })
    render(
      <MemoryRouter initialEntries={['/stand/zugang/schluessel-1']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByText(/Standzugang Tablet 1/)).toBeVisible()
    expect(await screen.findByText('Erika Beispiel', { selector: 'strong' })).toBeVisible()
    expect(screen.queryByText('Beenden')).toBeNull()
  })
})
