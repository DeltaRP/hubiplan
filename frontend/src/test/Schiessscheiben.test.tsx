// Schießscheiben Schritt 1: Scheibe, Wertungsart und Gleichstandsregeln je Einzelwertung,
// entschiedener Gleichstand in der Auswertung. Alles erfunden.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'
import type { TargetInfo } from '../api/competitions.ts'
import { countedIndexes, scoreShot, totalText } from '../pages/competitions/targetMath.ts'

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
    // Auswahl mit Vorschaubild und Kurzbeschreibung
    const kyfTile = screen.getByRole('radio', { name: /Luftgewehr 10 m Kyffhäuser/ })
    expect(kyfTile.closest('label')?.querySelector('svg.target-preview')).not.toBeNull()
    await user.click(kyfTile)
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

const lgDsb: TargetInfo = {
  ...kyf,
  key: 'lg10_dsb',
  name: 'Luftgewehr 10 m (DSB/ISSF)',
  top_diameter: 0.5,
  ring_width: 2.5,
  inner_diameter: 0.5,
  inner_mode: 'wegschiessen',
  black_diameter: 30.5,
  max_decimal: '10.9',
} as TargetInfo

describe('Wertung im Browser wie auf dem Server', () => {
  const at = (t: TargetInfo, d: number) => scoreShot(t, d, 0)
  const k = kyf as TargetInfo

  it('rechnet Ringe, Zehntel und Innenzehner wie targets.py', () => {
    expect(at(lgDsb, 0)).toMatchObject({ ring: 10, tenths: 109, inner: true, teilerTenths: 0 })
    expect(at(lgDsb, 1.0).tenths).toBe(106)
    expect(at(lgDsb, 2.0).inner).toBe(true)
    expect(at(lgDsb, 2.01).inner).toBe(false)
    expect(at(lgDsb, 2.5)).toMatchObject({ ring: 10, tenths: 100 })
    expect(at(lgDsb, 2.51)).toMatchObject({ ring: 9, tenths: 99 })
    expect(at(lgDsb, 25.1)).toMatchObject({ ring: 0, tenths: 0 })
    expect(at(lgDsb, 1.234).teilerTenths).toBe(1234)
    expect(at(k, 0).tenths).toBe(107)
    expect(at(k, 3.25).ring).toBe(10)
    expect(at(k, 3.26).ring).toBe(9)
  })

  it('zählt die besten Schüsse wie der Server', () => {
    const shots = [0.5, 30, 10, 3.5, 1.0].map((d) => at(k, d))
    expect(shots.map((s) => s.ring)).toEqual([10, 4, 8, 9, 10])
    expect(totalText('ringe', shots, 3)).toBe('29')
    expect([...countedIndexes('ringe', shots, 3)].sort()).toEqual([0, 3, 4])
    expect(totalText('zehntel', shots, 3)).toBe('31.0')
    expect(totalText('teiler', shots, null)).toBe('50.0')
    expect(totalText('ringe', [], 3)).toBe('')
  })
})

describe('Treffer am Stand antippen', () => {
  it('setzt Treffer auf der Scheibe und schickt sie mit Summe zum Abgleich', async () => {
    const tapScoring = {
      ...scoring,
      target: 'lg10_kyf',
      method: 'ringe',
      unit_label: 'Ringe',
      shots: 3,
      counted_shots: null,
      target_info: { ...kyf, rings: [{ ring: 1, diameter: 83 }] },
    }
    const otto = {
      id: 21,
      name: 'Otto Erfunden',
      club: '',
      guest: false,
      membership: 2,
      unit: null,
      unit_name: '',
      number: '',
      out_of_competition: false,
      presence: '',
      drawn_how: '',
      values: {},
      hits: {},
    }
    const calls = renderAt('/wettbewerbe/3', {
      [`GET ${base}3/`]: () => ({
        status: 200,
        body: { ...detail, status: 'laeuft', scorings: [tapScoring] },
      }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [otto] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}3/sync/`]: () => ({
        status: 200,
        body: { results: [{ ok: true }], conflicts: [], keys: {}, starters: [otto] },
      }),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Schütze (Name oder Startnummer)'), 'otto')
    expect(await screen.findByRole('option', { name: /Otto Erfunden/ })).toBeVisible()
    await user.keyboard('{Enter}')
    const pad = await screen.findByRole('img', { name: /0 Treffer/ })
    // Ansicht „Ganze Scheibe“: 83 mm · 1,08 Rand; 400 px Kantenlänge
    pad.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 400, height: 400, right: 400, bottom: 400 }) as DOMRect
    // Mitte: 10
    fireEvent.pointerDown(pad, { clientX: 200, clientY: 200, pointerId: 1 })
    fireEvent.pointerUp(pad, { pointerId: 1 })
    // ganz außen links oben: kein Ring
    fireEvent.pointerDown(pad, { clientX: 2, clientY: 2, pointerId: 1 })
    fireEvent.pointerUp(pad, { pointerId: 1 })
    expect(screen.getByText(/2 von 3 Treffer · Summe 10/)).toBeVisible()
    // zweiten Treffer wieder entfernen
    await user.click(screen.getByRole('button', { name: 'Schuss 2 entfernen' }))
    expect(screen.getByText(/1 von 3 Treffer · Summe 10/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    const op = () =>
      calls
        .filter((c) => c.key === `POST ${base}3/sync/`)
        .flatMap((c) => JSON.parse(String(c.init?.body)).ops)
        .find((o: { op: string }) => o.op === 'hits')
    await waitFor(() => expect(op()).toBeDefined())
    expect(op()).toMatchObject({ starter: 21, scoring: 11, hits: [{ x: 0, y: 0, spot: null }] })
  })

  it('übernimmt Treffer aus einem Foto als Vorschlag zum Prüfen', async () => {
    const photoScoring = {
      ...scoring,
      target: 'lg10_kyf',
      method: 'ringe',
      unit_label: 'Ringe',
      shots: 2,
      counted_shots: null,
      target_info: { ...kyf, photo: true, rings: [{ ring: 1, diameter: 83 }] },
    }
    const otto = {
      id: 21,
      name: 'Otto Erfunden',
      club: '',
      guest: false,
      membership: 2,
      unit: null,
      unit_name: '',
      number: '',
      out_of_competition: false,
      presence: '',
      drawn_how: '',
      values: {},
      hits: {},
    }
    const calls = renderAt('/wettbewerbe/3', {
      [`GET ${base}3/`]: () => ({
        status: 200,
        body: { ...detail, status: 'laeuft', scorings: [photoScoring] },
      }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [otto] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}3/photo/`]: () => ({
        status: 200,
        body: {
          scoring: 11,
          hits: [
            { x: '0.000', y: '0.000', source: 'foto' },
            { x: '0.000', y: '-10.000', source: 'foto' },
          ],
          needs_review: true,
          note: 'Schuss 2 nah an einer Ringlinie',
          samples: [{ key: 'probe-schluessel-1', spot: null }],
        },
      }),
      [`POST ${base}3/sync/`]: () => ({
        status: 200,
        body: { results: [{ ok: true }], conflicts: [], keys: {}, starters: [otto] },
      }),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Schütze (Name oder Startnummer)'), 'otto')
    expect(await screen.findByRole('option', { name: /Otto Erfunden/ })).toBeVisible()
    await user.keyboard('{Enter}')
    const file = new File([new Uint8Array([1, 2, 3])], 'scheibe.jpg', { type: 'image/jpeg' })
    fireEvent.change(await screen.findByLabelText('Foto der Scheibe'), {
      target: { files: [file] },
    })
    expect(await screen.findByText('Vorschlag aus dem Foto: 2 Treffer.')).toBeVisible()
    expect(screen.getByText(/Bitte genau prüfen/)).toBeVisible()
    expect(screen.getByText(/Schuss 2 nah an einer Ringlinie/)).toBeVisible()
    expect(screen.getAllByText('aus Foto')).toHaveLength(2)
    expect(screen.getByText(/2 von 2 Treffer · Summe 18/)).toBeVisible()
    const upload = calls.find((c) => c.key === `POST ${base}3/photo/`)
    expect(upload?.init?.body).toBeInstanceOf(FormData)
    // zweiten Treffer korrigieren: per Tastatur 1 mm nach oben, dann ist er angetippt
    screen.getByRole('button', { name: /^Schuss 2:/ }).focus()
    await user.keyboard('{Shift>}{ArrowUp}{/Shift}')
    expect(screen.getAllByText('aus Foto')).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    const op = () =>
      calls
        .filter((c) => c.key === `POST ${base}3/sync/`)
        .flatMap((c) => JSON.parse(String(c.init?.body)).ops)
        .find((o: { op: string }) => o.op === 'hits')
    await waitFor(() => expect(op()).toBeDefined())
    expect(op().hits).toEqual([
      { x: 0, y: 0, spot: null, source: 'foto' },
      { x: 0, y: -9, spot: null, source: 'tippen' },
    ])
    // mit Einwilligung des Vereins: bereitgelegter Ausschnitt geht mit den bestätigten Treffern
    expect(op().samples).toEqual(['probe-schluessel-1'])
  })

  it('vergleicht eine von Hand eingegebene Summe mit dem Foto', async () => {
    const photoScoring = {
      ...scoring,
      target: 'lg10_kyf',
      method: 'ringe',
      unit_label: 'Ringe',
      shots: 2,
      counted_shots: null,
      target_info: { ...kyf, photo: true, rings: [{ ring: 1, diameter: 83 }] },
    }
    const otto = {
      id: 21,
      name: 'Otto Erfunden',
      club: '',
      guest: false,
      membership: 2,
      unit: null,
      unit_name: '',
      number: '',
      out_of_competition: false,
      presence: '',
      drawn_how: '',
      values: {},
      hits: {},
    }
    const calls = renderAt('/wettbewerbe/3', {
      [`GET ${base}3/`]: () => ({
        status: 200,
        body: { ...detail, status: 'laeuft', scorings: [photoScoring] },
      }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [otto] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}3/photo/`]: () => ({
        status: 200,
        body: {
          scoring: 11,
          hits: [
            { x: '0.000', y: '0.000', source: 'foto' },
            { x: '0.000', y: '-10.000', source: 'foto' },
          ],
          needs_review: false,
          note: '',
        },
      }),
      [`POST ${base}3/sync/`]: () => ({
        status: 200,
        body: { results: [{ ok: true }], conflicts: [], keys: {}, starters: [otto] },
      }),
    })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Schütze (Name oder Startnummer)'), 'otto')
    expect(await screen.findByRole('option', { name: /Otto Erfunden/ })).toBeVisible()
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('button', { name: 'Nur die Summe eingeben' }))
    const file = new File([new Uint8Array([1, 2, 3])], 'scheibe.jpg', { type: 'image/jpeg' })
    fireEvent.change(await screen.findByLabelText('Foto der Scheibe'), {
      target: { files: [file] },
    })
    expect(await screen.findByText(/Foto zum Vergleich: 18 Ringe/)).toBeVisible()
    await user.type(screen.getByLabelText('Ringe'), '17')
    expect(screen.getByText(/Weicht von der Eingabe ab/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Das Foto ergibt 18')
    await user.click(within(dialog).getByRole('button', { name: 'Eingabe speichern' }))
    const op = () =>
      calls
        .filter((c) => c.key === `POST ${base}3/sync/`)
        .flatMap((c) => JSON.parse(String(c.init?.body)).ops)
        .find((o: { op: string }) => o.op === 'score')
    await waitFor(() => expect(op()).toBeDefined())
    expect(op().value).toBe('17')
  })

  it('sammelt Spiegelausschnitte nur nach Einschalten durch den Verein', async () => {
    let state = { enabled: false, changed_at: null, count: 2, can_manage: true }
    const calls = renderAt('/einstellungen/datenschutz', {
      // die Mitglieder-Hinweise auf derselben Seite sind hier nicht Gegenstand
      'GET /api/orgs/7/imprint/': () => ({ status: 500, body: { detail: 'nicht im Test' } }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${base}photo-samples/`]: () => ({ status: 200, body: state }),
      [`PATCH ${base}photo-samples/`]: (init) => {
        state = { ...state, ...JSON.parse(String(init?.body)) }
        return { status: 200, body: state }
      },
    })
    const user = userEvent.setup()
    const box = await screen.findByRole('checkbox', {
      name: 'Bestätigte Spiegelausschnitte sammeln',
    })
    expect(box).not.toBeChecked()
    expect(screen.getByText(/Gesammelt: 2 Ausschnitte/)).toBeVisible()
    await user.click(box)
    await waitFor(() => expect(box).toBeChecked())
    const patch = calls.find((c) => c.key === `PATCH ${base}photo-samples/`)
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ enabled: true })
    expect(screen.getByRole('button', { name: 'Alle Ausschnitte löschen' })).toBeVisible()
  })
})
