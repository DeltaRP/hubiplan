import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const base = '/api/orgs/7/honors/'

const koenig = {
  id: 1,
  name: 'König',
  unit: null,
  unit_name: null,
  sort_order: 1,
  is_public: true,
  is_archived: false,
  numbered: true,
  count_each_reign: false,
  share_down: false,
  name_plural: '',
  plural: 'Könige',
  reign_count: 1,
}

const reign = {
  id: 5,
  dignity: 1,
  dignity_name: 'König',
  year: 2024,
  end_year: null,
  valid_from: null,
  valid_until: null,
  period_text: '2024',
  person: 3,
  name: 'Otto Muster',
  display_name: 'Otto Muster',
  ordinal: null,
  ordinal_text: 'I',
  numbered_name: 'Otto I. Muster',
  note: '',
  origin: null,
  origin_name: '',
  origin_text: '',
  companions: [
    {
      id: 1,
      label: 'Königin',
      person: null,
      name: 'Erika Beispiel',
      display_name: 'Erika Beispiel',
    },
  ],
  photo: null,
}

function renderApp(
  routes: Record<string, () => { status: number; body?: unknown }>,
  path: string,
  extra: Record<string, unknown> = {},
) {
  const org = testOrg({ permissions: ['members.view', 'members.edit'], ...extra })
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
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

describe('Chronik', () => {
  it('zeigt Regentschaften mit Begleitung', async () => {
    renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [reign] }),
      },
      '/mitglieder/wuerdentraeger',
    )
    // Ralf 2026-10-30: Ordnungszahl je Vorname, „Vorname Zahl. Nachname“
    expect(await screen.findByText('Otto I. Muster')).toBeVisible()
    expect(screen.getByText('Königin: Erika Beispiel')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Neue Regentschaft' })).toBeVisible()
  })

  it('alte Adresse /mitglieder/chronik leitet auf Würdenträger weiter', async () => {
    renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [reign] }),
      },
      '/mitglieder/chronik',
    )
    expect(await screen.findByText('Otto I. Muster')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Würdenträger' })).toBeVisible()
  })

  it('zeigt weitergegebene Würden der Einheit darüber und wählt die Herkunft', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [] }),
        [`GET ${base}origins/`]: () => ({ status: 200, body: [{ id: 9, name: 'Jägerzug' }] }),
        [`GET ${base}shared/`]: () => ({
          status: 200,
          body: [
            {
              id: 4,
              name: 'Bundeskönig',
              owner: 'Testbund',
              reigns: [
                {
                  id: 8,
                  period_text: '2024',
                  year: 2024,
                  numbered_name: 'Karl Bürger',
                  note: '',
                  companions: [],
                },
              ],
            },
          ],
        }),
        [`POST ${base}reigns/`]: () => ({ status: 201, body: reign }),
      },
      '/mitglieder/wuerdentraeger',
    )
    expect(await screen.findByText('Karl Bürger')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Bundeskönig (Testbund)' })).toBeVisible()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Neue Regentschaft' }))
    await user.type(screen.getByLabelText('Würdenträger (Name)'), 'Hans Alt')
    await user.selectOptions(screen.getByLabelText(/Aus \(Herkunft/), 'frei')
    await user.type(screen.getByLabelText('Aus (frei)'), 'Alter Zug')
    await user.click(screen.getByRole('button', { name: 'Anlegen' }))
    await waitFor(() => expect(calls.some((c) => c.key === `POST ${base}reigns/`)).toBe(true))
    const post = calls.find((c) => c.key === `POST ${base}reigns/`)
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({
      name: 'Hans Alt',
      origin: null,
      origin_name: 'Alter Zug',
    })
  })

  it('oberste Einheit mit eigenen Mitgliedern: neue Würde ohne Untereinheiten-Abfrage', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [] }),
      },
      '/mitglieder/wuerdentraeger/wuerden',
      { type: 'federation', direct_members: true, modules: ['members'] },
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neue Würde' }))
    expect(screen.queryByText(/Untereinheiten konnten nicht geladen werden/)).toBeNull()
    expect(calls.some((c) => c.key.includes('/departments/'))).toBe(false)
  })

  it('liest eine Königsliste und übernimmt die geprüften Zeilen', async () => {
    const calls = renderApp(
      {
        [`POST ${base}import/preview/`]: () => ({
          status: 200,
          body: {
            new_dignities: ['Kaiser'],
            rows: [
              {
                line: 2,
                year: 2023,
                end_year: null,
                dignity: 'König',
                dignity_id: 1,
                name: 'Muster, Otto',
                person_id: 3,
                candidates: [{ id: 3, name: 'Otto Muster', birth_year: 1970 }],
                companions: [
                  { label: 'Königin', name: 'Erika Beispiel', person_id: null, candidates: [] },
                ],
                note: '',
                ordinal: null,
                ordinal_text: '',
                duplicate: false,
                errors: [],
              },
              {
                line: 3,
                year: 1961,
                end_year: 1963,
                dignity: 'Kaiser',
                dignity_id: null,
                name: 'Wilhelm Vorzeit',
                person_id: null,
                candidates: [],
                companions: [],
                note: 'Jubiläumskaiser',
                ordinal: 4,
                ordinal_text: 'IV',
                duplicate: false,
                errors: [],
              },
              {
                line: 4,
                year: null,
                end_year: null,
                dignity: 'König',
                dignity_id: 1,
                name: '',
                person_id: null,
                candidates: [],
                companions: [],
                note: '',
                ordinal: null,
                ordinal_text: '',
                duplicate: false,
                errors: ['Jahr fehlt oder ist ungültig.'],
              },
            ],
          },
        }),
        [`POST ${base}import/`]: () => ({
          status: 201,
          body: { created: 2, dignities_created: ['Kaiser'] },
        }),
      },
      '/mitglieder/wuerdentraeger/import',
    )
    const user = userEvent.setup()
    const input = await screen.findByLabelText('Datei auswählen')
    await user.upload(input, new File(['x'], 'koenige.xlsx'))
    expect(await screen.findByText(/Neue Würden werden angelegt: Kaiser/)).toBeVisible()
    expect(screen.getByLabelText('Zuordnung Zeile 2')).toHaveValue('3')
    expect(screen.getByLabelText('Zeile 4 übernehmen')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '2 Regentschaften übernehmen' }))
    expect(await screen.findByText(/2 Regentschaften übernommen/)).toBeVisible()
    const post = calls.find((c) => c.key === `POST ${base}import/`)
    const sent = JSON.parse(String(post?.init?.body))
    expect(sent.rows).toHaveLength(2)
    expect(sent.rows[0]).toMatchObject({ year: 2023, person_id: 3, dignity: 'König' })
    expect(sent.rows[1]).toMatchObject({ name: 'Wilhelm Vorzeit', ordinal: 4, end_year: 1963 })
    expect(sent.rows[1]).toMatchObject({ name: 'Wilhelm Vorzeit', person_id: null })
  })

  it('legt eine Würde an', async () => {
    let created = false
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: created ? [koenig] : [] }),
        'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
        [`POST ${base}dignities/`]: () => {
          created = true
          return { status: 201, body: koenig }
        },
      },
      '/mitglieder/wuerdentraeger/wuerden',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neue Würde' }))
    await user.type(screen.getByLabelText(/Bezeichnung/), 'König')
    await user.click(screen.getByRole('button', { name: 'Anlegen' }))
    await waitFor(() => expect(calls.some((c) => c.key === `POST ${base}dignities/`)).toBe(true))
    const table = await screen.findByRole('table')
    expect(within(table).getByText('König')).toBeVisible()
  })

  it('löscht eine Würde nach Rückfrage samt Regentschaften', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
        [`DELETE ${base}dignities/1/?mit_regentschaften=1`]: () => ({ status: 204 }),
      },
      '/mitglieder/wuerdentraeger/wuerden',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'König löschen' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/mit allen 1 Regentschaften gelöscht/)).toBeVisible()
    await user.click(within(dialog).getByRole('button', { name: 'Löschen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `DELETE ${base}dignities/1/?mit_regentschaften=1`)).toBe(
        true,
      ),
    )
  })

  it('speichert eine bestehende Würde automatisch, ohne Speichern-Knopf', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
        [`PATCH ${base}dignities/1/`]: () => ({ status: 200, body: koenig }),
      },
      '/mitglieder/wuerdentraeger/wuerden',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'König bearbeiten' }))
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText(/Bezeichnung/), 'skönig')
    await waitFor(
      () => expect(calls.some((c) => c.key === `PATCH ${base}dignities/1/`)).toBe(true),
      { timeout: 3000 },
    )
    const patch = calls.find((c) => c.key === `PATCH ${base}dignities/1/`)
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ name: 'Königskönig' })
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
  })

  it('speichert eine bestehende Regentschaft automatisch', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [reign] }),
        [`PUT ${base}reigns/5/`]: () => ({ status: 200, body: reign }),
      },
      '/mitglieder/wuerdentraeger',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Otto Muster 2024 bearbeiten' }))
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Bemerkung'), 'Jubiläumskönig')
    await waitFor(() => expect(calls.some((c) => c.key === `PUT ${base}reigns/5/`)).toBe(true), {
      timeout: 3000,
    })
    const put = calls.find((c) => c.key === `PUT ${base}reigns/5/`)
    expect(JSON.parse(String(put?.init?.body))).toMatchObject({
      note: 'Jubiläumskönig',
      year: 2024,
    })
    expect(await screen.findByText('✓ Gespeichert')).toBeInTheDocument()
  })

  it('nimmt bei einer Regentschaft Startjahr und Endjahr an', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [reign] }),
        [`PUT ${base}reigns/5/`]: () => ({ status: 200, body: reign }),
      },
      '/mitglieder/wuerdentraeger',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Otto Muster 2024 bearbeiten' }))
    await user.type(screen.getByLabelText('Endjahr (leer = nur ein Jahr)'), '2026')
    expect(screen.getByLabelText('Startjahr')).toHaveValue(2024)
    await waitFor(
      () => {
        const put = calls.findLast((c) => c.key === `PUT ${base}reigns/5/`)
        expect(JSON.parse(String(put?.init?.body))).toMatchObject({ year: 2024, end_year: 2026 })
      },
      { timeout: 3000 },
    )
  })

  it('setzt eine Ordnungszahl von Hand', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [reign] }),
        [`PUT ${base}reigns/5/`]: () => ({ status: 200, body: reign }),
      },
      '/mitglieder/wuerdentraeger',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Otto Muster 2024 bearbeiten' }))
    const field = screen.getByLabelText('Ordnungszahl (leer = automatisch je Vorname)')
    expect(field).toHaveAttribute('placeholder', 'I')
    await user.type(field, '3')
    await waitFor(
      () => {
        const put = calls.findLast((c) => c.key === `PUT ${base}reigns/5/`)
        expect(JSON.parse(String(put?.init?.body))).toMatchObject({ ordinal: 3 })
      },
      { timeout: 3000 },
    )
  })
})
