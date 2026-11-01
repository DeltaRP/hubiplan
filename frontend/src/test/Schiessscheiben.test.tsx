// Schießscheiben Schritt 1: Scheibe, Wertungsart und Gleichstandsregeln je Einzelwertung,
// entschiedener Gleichstand in der Auswertung. Alles erfunden.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/competitions/'

const scoring = {
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
  prize_places: 3,
  shootoff_shots: 3,
  shootoff_counted: null,
  field_size: null,
  target: '',
  custom_target: {},
  method: 'frei',
  tie_breaks: [],
  series_size: 10,
}

const detail = {
  id: 3,
  title: 'Pokalschießen 2027',
  form: 'rangliste',
  own: true,
  organizer: '',
  drop_out: true,
  fixed_order: false,
  total_shots: null,
  event: null,
  event_info: null,
  calendar: { on: false, can_create: false },
  prizes: [],
  occasion: '',
  discipline: 'Luftgewehr',
  location: '',
  date: '2027-05-01',
  description: '',
  details: [],
  status: 'vorbereitung',
  status_label: 'Vorbereitung',
  website: 'aus',
  starter_count: 0,
  can_manage: true,
  units: [],
  scorings: [scoring],
}

const kyf = {
  key: 'lg10_kyf',
  name: 'Luftgewehr 10 m Kyffhäuser',
  group: 'Luftgewehr',
  top_diameter: 2,
  ring_width: 4.5,
  caliber: 4.5,
  top: 10,
  lowest: 1,
  inner_diameter: null,
  inner_mode: 'beruehren',
  black_diameter: 29,
  spots: 1,
  teiler_factor: 1,
  note: 'Alte Kyffhäuser-Scheibe.',
  rings: [],
  max_decimal: '10.7',
}

const catalog = {
  targets: [kyf],
  custom: 'eigen',
  methods: [
    { value: 'frei', label: 'Wert frei eingeben' },
    { value: 'ringe', label: 'Ringe' },
    { value: 'zehntel', label: 'Zehntel' },
    { value: 'teiler', label: 'Teiler' },
  ],
  tie_breaks: [
    { value: 'serien', label: 'Serien von hinten verglichen' },
    { value: 'ringzahlen', label: 'mehr Zehner, dann Neuner usw.' },
    { value: 'innenzehner', label: 'mehr Innenzehner' },
  ],
  presets: { dsb: ['serien', 'ringzahlen', 'innenzehner'] },
}

function renderAt(path: string, routes: Parameters<typeof fakeApi>[0]) {
  const org = testOrg({ permissions: ['competitions.manage'], modules: ['competitions'] })
  const calls = fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    [`GET ${base}3/`]: () => ({ status: 200, body: detail }),
    [`GET ${base}targets/`]: () => ({ status: 200, body: catalog }),
    [`GET ${base}3/stand-access/`]: () => ({ status: 200, body: [] }),
    ...routes,
  })
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Scheibe und Wertung', () => {
  it('stellt Scheibe, Wertungsart und Gleichstandsregeln ein', async () => {
    const calls = renderAt('/wettbewerbe/3/einrichten', {
      [`PATCH ${base}3/scorings/11/`]: () => ({
        status: 200,
        body: { ...scoring, target: 'lg10_kyf', method: 'ringe', unit_label: 'Ringe' },
      }),
    })
    const user = userEvent.setup()
    const method = await screen.findByLabelText('Wertungsart')
    // ohne Scheibe nur „frei“
    expect(screen.getByRole('option', { name: 'Ringe' })).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Scheibe'), 'lg10_kyf')
    expect(screen.getByText(/Alte Kyffhäuser-Scheibe/)).toBeVisible()
    await user.selectOptions(method, 'ringe')
    // Wert kommt aus den Treffern: keine freie Einheit mehr
    expect(screen.queryByLabelText('Einheit des Werts')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'wie DSB (Auflage)' }))
    expect(screen.getByText(/1\. Serien von hinten verglichen/)).toBeVisible()
    const patches = () =>
      calls
        .filter((c) => c.key === `PATCH ${base}3/scorings/11/`)
        .map((c) => JSON.parse(String(c.init?.body)))
    await waitFor(
      () =>
        expect(Object.assign({}, ...patches())).toMatchObject({
          target: 'lg10_kyf',
          method: 'ringe',
          tie_breaks: ['serien', 'ringzahlen', 'innenzehner'],
        }),
      { timeout: 3000 },
    )
  })

  it('zeigt, welche Regel einen Gleichstand entschieden hat', async () => {
    renderAt('/wettbewerbe/3/auswertung', {
      [`GET ${base}3/shootoffs/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/standings/`]: () => ({
        status: 200,
        body: {
          scorings: [
            {
              scoring: 11,
              name: 'Einzelwertung',
              kind: 'einzel',
              rows: [
                {
                  key: 's1',
                  place: 1,
                  name: 'Berta Erfunden',
                  value: '28',
                  value_text: '28',
                  decided_by: 'mehr Zehner, dann Neuner usw.',
                },
                {
                  key: 's2',
                  place: 2,
                  name: 'Anton Erfunden',
                  value: '28',
                  value_text: '28',
                  decided_by: 'mehr Zehner, dann Neuner usw.',
                },
              ],
              open: [],
              without_value: [],
            },
          ],
          open_shootoffs: 0,
          stats: {},
        },
      }),
    })
    expect(await screen.findByText('Berta Erfunden')).toBeVisible()
    expect(screen.getAllByText(/mehr Zehner, dann Neuner/)).toHaveLength(2)
  })
})
