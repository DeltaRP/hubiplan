// Wettbewerb und Termin im Kalender: beim Anlegen einen Termin wählen, unter „Einrichten“
// die Zusagen als Starter übernehmen (Ralf 2026-11-01). Alles erfunden.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/competitions/'

const ostern = {
  id: 8,
  title: 'Osterschießen',
  date: '2027-04-04',
  time: '14:00',
  location: 'Schießstand am Deich',
  unit_name: '',
  is_cancelled: false,
  rsvp_enabled: true,
  yes_count: 2,
  competition: null,
}

const detail = {
  id: 3,
  title: 'Osterschießen',
  form: 'rangliste',
  own: true,
  organizer: '',
  drop_out: true,
  fixed_order: false,
  total_shots: null,
  event: 8,
  event_info: ostern,
  calendar: { on: true, can_create: true },
  prizes: [],
  occasion: '',
  discipline: '',
  location: 'Schießstand am Deich',
  date: '2027-04-04',
  description: '',
  details: [],
  status: 'vorbereitung',
  status_label: 'Vorbereitung',
  website: 'aus',
  starter_count: 0,
  can_manage: true,
  units: [],
  scorings: [],
}

function renderAt(path: string, routes: Parameters<typeof fakeApi>[0]) {
  const org = testOrg({ permissions: ['competitions.manage'], modules: ['competitions'] })
  const calls = fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    [`GET ${base}event-candidates/`]: () => ({
      status: 200,
      body: { on: true, can_create: true, events: [ostern] },
    }),
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

describe('Wettbewerb und Termin', () => {
  it('übernimmt Titel und Datum aus dem gewählten Termin', async () => {
    const calls = renderAt('/wettbewerbe', {
      [`GET ${base}`]: () => ({ status: 200, body: [] }),
      [`POST ${base}`]: () => ({ status: 201, body: { ...detail } }),
      [`GET ${base}3/`]: () => ({ status: 200, body: detail }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neuer Wettbewerb' }))
    const picker = await screen.findByLabelText('Termin im Kalender')
    expect(screen.getByRole('option', { name: 'neuen Termin im Kalender anlegen' })).toBeVisible()
    await user.selectOptions(picker, '8')
    expect(screen.getByLabelText('Titel')).toHaveValue('Osterschießen')
    expect(screen.getByLabelText('Datum')).toHaveValue('2027-04-04')
    await user.click(screen.getByRole('button', { name: 'Anlegen' }))
    await waitFor(() => expect(calls.some((c) => c.key === `POST ${base}`)).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.key === `POST ${base}`)?.init?.body))
    expect(body).toMatchObject({ title: 'Osterschießen', date: '2027-04-04', event: 8 })
    expect(body.create_event).toBeUndefined()
  })

  it('übernimmt die Zusagen des Termins als Starter', async () => {
    const calls = renderAt('/wettbewerbe/3/einrichten', {
      [`GET ${base}3/`]: () => ({ status: 200, body: detail }),
      [`GET ${base}3/stand-access/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}3/starters/from-event/`]: () => ({
        status: 200,
        body: { added: 2, already: 0 },
      }),
    })
    const user = userEvent.setup()
    expect(await screen.findByRole('link', { name: /Osterschießen/ })).toHaveAttribute(
      'href',
      '/termine?termin=8&datum=2027-04-04',
    )
    expect(screen.getByText('2 Zusagen zum Termin.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Zusagen als Starter übernehmen' }))
    expect(await screen.findByText('2 Starter aus den Zusagen übernommen.')).toBeVisible()
    expect(calls.some((c) => c.key === `POST ${base}3/starters/from-event/`)).toBe(true)
  })

  it('zeigt den Standzugang direkt beim Erfassen', async () => {
    renderAt('/wettbewerbe/3', {
      [`GET ${base}3/`]: () => ({ status: 200, body: detail }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/stand-access/`]: () => ({ status: 200, body: [] }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Anderes Gerät per QR-Code' }))
    expect(
      await screen.findByRole('heading', { name: 'Standzugang für ein geliehenes Gerät' }),
    ).toBeVisible()
  })

  it('zeigt im Standmodus die Tabellen aller Wertungen mit allen Plätzen', async () => {
    renderAt('/stand/7/3', {
      [`GET ${base}3/`]: () => ({ status: 200, body: { ...detail, status: 'laeuft' } }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/version/`]: () => ({ status: 200, body: { version: 'a' } }),
      [`GET ${base}3/standings/`]: () => ({
        status: 200,
        body: {
          open_shootoffs: 0,
          scorings: [
            {
              scoring: 11,
              name: 'Einzelwertung',
              kind: 'einzel',
              open: [],
              without_value: [],
              rows: [1, 2, 3, 4, 5, 6].map((i) => ({
                key: `s${i}`,
                place: i,
                name: `Schütze ${i}`,
                unit_name: 'Zug 1',
                value: String(30 - i),
                value_text: String(30 - i),
                prize: i <= 3,
              })),
            },
          ],
        },
      }),
    })
    const live = await screen.findByRole('complementary', { name: 'Aktuelle Tabellen' })
    expect(within(live).getByRole('heading', { name: 'Einzelwertung' })).toBeVisible()
    expect(within(live).getByText('Schütze 6')).toBeVisible()
  })

  it('Schießen beenden, Stechen mit eigenen Regeln anlegen, alles im Standmodus', async () => {
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
    }
    const tie = { keys: ['s1', 's2'], names: ['Max Muster', 'Erika Beispiel'], place: 2 }
    let created = false
    const calls = renderAt('/stand/7/3', {
      [`GET ${base}3/`]: () => ({
        status: 200,
        body: { ...detail, status: 'laeuft', scorings: [scoring] },
      }),
      [`GET ${base}3/starters/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/members/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}3/version/`]: () => ({ status: 200, body: { version: 'a' } }),
      [`GET ${base}3/standings/`]: () => ({
        status: 200,
        body: {
          open_shootoffs: 1,
          status: 'laeuft',
          stats: {},
          scorings: [
            {
              scoring: 11,
              name: 'Einzelwertung',
              kind: 'einzel',
              open: [{ ...tie, shootoff: created ? 1 : null }],
              without_value: [{ key: 's3', name: 'Otto Normal' }],
              rows: [],
            },
          ],
        },
      }),
      [`GET ${base}3/shootoffs/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}3/shootoffs/`]: () => {
        created = true
        return {
          status: 201,
          body: { id: 1, scoring: 11, number: 1, shots: 1, counted_shots: null, entries: [] },
        }
      },
      [`POST ${base}3/status/`]: () => ({
        status: 200,
        body: { status: 'vorlaeufig', status_label: 'vorläufig' },
      }),
    })
    const user = userEvent.setup()
    const end = await screen.findByRole('region', { name: 'Abschluss' })
    expect(within(end).getByText(/Noch ohne Ergebnis: 1 \(Otto Normal\)/)).toBeVisible()
    // Schießen beenden: Rückfrage nennt, wer noch fehlt
    await user.click(within(end).getByRole('button', { name: 'Schießen beenden' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Otto Normal')
    await user.click(within(dialog).getByRole('button', { name: 'Schießen beenden' }))
    await waitFor(() => expect(calls.some((c) => c.key === `POST ${base}3/status/`)).toBe(true))
    // Stechen: Regeln vor Ort, vorbelegt aus „Einrichten“ (3 Schuss)
    await user.click(within(end).getByRole('button', { name: 'Stechen anlegen …' }))
    const shots = within(end).getByLabelText('Schüsse im Stechen')
    expect(shots).toHaveValue(3)
    await user.clear(shots)
    await user.type(shots, '1')
    await user.click(within(end).getByRole('button', { name: 'Stechen anlegen' }))
    await waitFor(() => {
      const post = calls.find((c) => c.key === `POST ${base}3/shootoffs/`)
      expect(JSON.parse(String(post?.init?.body))).toMatchObject({
        scoring: 11,
        keys: ['s1', 's2'],
        shots: 1,
      })
    })
  })
})
