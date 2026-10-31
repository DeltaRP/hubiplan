import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { groupSteps, resetUndo } from '../components/undo.ts'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const ORG = testOrg({ permissions: ['members.view', 'members.edit', 'audit.view', 'org.edit'] })
const base = '/api/orgs/7'

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

function changeHeaders(id: string, kind = 'update', label = 'Änderung') {
  return {
    'X-Change-Set': id,
    'X-Change-Undoable': '1',
    'X-Change-Kind': kind,
    'X-Change-Label': encodeURIComponent(label),
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

afterEach(() => resetUndo())

describe('Autospeichern', () => {
  it('speichert nur geänderte Felder ohne Speichern-Knopf', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/members/11/`]: () => ({ status: 200, body: detail }),
      [`PATCH ${base}/members/11/`]: () => ({
        status: 200,
        body: { ...detail, first_name: 'Erica' },
        headers: changeHeaders('aaa'),
      }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    const field = await screen.findByLabelText('Vorname')
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument()
    await user.clear(field)
    await user.type(field, 'Erica')
    expect(await screen.findByText('✓ Gespeichert', {}, { timeout: 3000 })).toBeInTheDocument()
    const patches = calls.filter((c) => c.key === `PATCH ${base}/members/11/`)
    expect(patches).toHaveLength(1)
    expect(JSON.parse(String(patches[0].init?.body))).toEqual({ first_name: 'Erica' })
    // Fokus bleibt im Feld (kein gesperrtes Formular während des Speicherns)
    expect(field).toHaveFocus()
  })

  it('zeigt Feldfehler und speichert sie nicht', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/members/11/`]: () => ({ status: 200, body: detail }),
      [`PATCH ${base}/members/11/`]: () => ({
        status: 400,
        body: { last_name: ['Dieses Feld darf nicht leer sein.'] },
      }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    await user.clear(await screen.findByLabelText('Name'))
    expect(
      await screen.findByText('Dieses Feld darf nicht leer sein.', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Nicht gespeichert/)).toBeInTheDocument()
  })
})

describe('Rückgängig und Wiederherstellen', () => {
  it('nimmt die letzte Änderung zurück und stellt sie wieder her', async () => {
    let current = detail
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/members/11/`]: () => ({ status: 200, body: current }),
      [`PATCH ${base}/members/11/`]: () => {
        current = { ...detail, first_name: 'Erica' }
        return { status: 200, body: current, headers: changeHeaders('aaa') }
      },
      [`POST ${base}/changes/aaa/undo/`]: () => {
        current = detail
        return { status: 200, body: { change_set: 'bbb' }, headers: changeHeaders('bbb') }
      },
      [`POST ${base}/changes/bbb/undo/`]: () => {
        current = { ...detail, first_name: 'Erica' }
        return { status: 200, body: { change_set: 'ccc' }, headers: changeHeaders('ccc') }
      },
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    const undoButton = await screen.findByRole('button', {
      name: 'Letzte Änderung rückgängig machen',
    })
    const redoButton = screen.getByRole('button', { name: 'Rückgängig Gemachtes wiederherstellen' })
    expect(undoButton).toBeDisabled()
    const field = await screen.findByLabelText('Vorname')
    await user.clear(field)
    await user.type(field, 'Erica')
    await waitFor(() => expect(undoButton).toBeEnabled(), { timeout: 3000 })

    await user.click(undoButton)
    expect(await screen.findByText('Rückgängig gemacht.')).toBeInTheDocument()
    // Die Seite lädt neu und zeigt den alten Wert
    await waitFor(() => expect(screen.getByLabelText('Vorname')).toHaveValue('Erika'))
    expect(redoButton).toBeEnabled()

    await user.click(redoButton)
    await waitFor(() => expect(screen.getByLabelText('Vorname')).toHaveValue('Erica'))
    expect(calls.map((c) => c.key)).toContain(`POST ${base}/changes/bbb/undo/`)
    expect(undoButton).toBeEnabled()
  })

  it('nimmt mehrere Schritte auf einmal zurück', async () => {
    let n = 0
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/members/11/`]: () => ({ status: 200, body: detail }),
      [`PATCH ${base}/members/11/`]: () => {
        n++
        return {
          status: 200,
          body: detail,
          headers: changeHeaders(`s${n}`, 'update', `Schritt ${n}`),
        }
      },
      [`POST ${base}/changes/s1/undo/`]: () => ({ status: 200, body: { change_set: 'r1' } }),
      [`POST ${base}/changes/s2/undo/`]: () => ({ status: 200, body: { change_set: 'r2' } }),
      [`POST ${base}/changes/s3/undo/`]: () => ({ status: 200, body: { change_set: 'r3' } }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    const field = await screen.findByLabelText('Telefon')
    for (const digit of ['1', '2', '3']) {
      await user.type(field, digit)
      await screen.findByText('✓ Gespeichert', {}, { timeout: 3000 })
      await waitFor(() => expect(n).toBe(Number(digit)), { timeout: 3000 })
    }
    await user.click(screen.getByRole('button', { name: 'Letzte Schritte' }))
    // Neueste zuerst
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items.slice(0, 3)).toEqual(['Schritt 3', 'Schritt 2', 'Schritt 1'])
    await user.click(screen.getByRole('button', { name: 'Schritt 2' }))
    expect(await screen.findByText('2 Schritte rückgängig gemacht.')).toBeInTheDocument()
    expect(calls.filter((c) => c.key.endsWith('/undo/')).map((c) => c.key)).toEqual([
      `POST ${base}/changes/s3/undo/`,
      `POST ${base}/changes/s2/undo/`,
    ])
    await user.click(screen.getByRole('button', { name: 'Letzte Schritte' }))
    expect(screen.getByText('Wiederherstellen bis einschließlich …')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Schritt 2' })).toBeInTheDocument()
  })

  it('Strg+Z außerhalb von Eingabefeldern', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/members/11/`]: () => ({ status: 200, body: detail }),
      [`PATCH ${base}/members/11/`]: () => ({
        status: 200,
        body: detail,
        headers: changeHeaders('aaa'),
      }),
      [`POST ${base}/changes/aaa/undo/`]: () => ({ status: 200, body: { change_set: 'bbb' } }),
    })
    renderAt('/mitglieder/11')
    const user = userEvent.setup()
    const field = await screen.findByLabelText('Telefon')
    await user.type(field, '1')
    await waitFor(
      () =>
        expect(
          screen.getByRole('button', { name: 'Letzte Änderung rückgängig machen' }),
        ).toBeEnabled(),
      { timeout: 3000 },
    )
    // Im Feld gehört Strg+Z dem Browser
    await user.keyboard('{Control>}z{/Control}')
    expect(calls.some((c) => c.key.includes('/undo/'))).toBe(false)
    act(() => field.blur())
    await user.keyboard('{Control>}z{/Control}')
    await waitFor(() => expect(calls.some((c) => c.key.includes('/undo/'))).toBe(true))
  })

  it('fragt bei späteren Änderungen nach und nimmt erst dann trotzdem zurück', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/audit/`]: () => ({
        status: 200,
        body: {
          count: 1,
          page: 1,
          pages: 1,
          results: [
            {
              id: 1,
              timestamp: '2026-10-24T10:00:00Z',
              user_email: 'kassenwart@example.org',
              action: 'delete',
              action_label: 'gelöscht',
              object_type: 'Termin',
              object_repr: 'Sommerfest',
              changes: {},
              undo: { change_set: 'old', state: 'possible', reason: '', is_undo: false },
            },
          ],
        },
      }),
      [`POST ${base}/changes/old/undo/`]: (init) =>
        JSON.parse(String(init?.body)).force
          ? { status: 200, body: { change_set: 'new' } }
          : {
              status: 409,
              body: {
                detail: 'Das lässt sich nicht ohne Weiteres rückgängig machen.',
                problems: ['Termin „Sommerfest“ wurde inzwischen erneut geändert.'],
                can_force: true,
              },
            },
    })
    renderAt('/einstellungen/protokoll')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Wiederherstellen' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/erneut geändert/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Trotzdem zurücknehmen' }))
    await waitFor(() =>
      expect(
        calls.filter((c) => c.key === `POST ${base}/changes/old/undo/`).map((c) => c.init?.body),
      ).toEqual(['{}', '{"force":true}']),
    )
  })
})

describe('Liste der letzten Schritte', () => {
  it('fasst gleiche aufeinanderfolgende Schritte zusammen', () => {
    const e = (setId: string, label: string) => ({ setId, label })
    expect(
      groupSteps([
        e('a', 'Impressum geändert'),
        e('b', 'Impressum geändert'),
        e('c', 'Würde geändert'),
        e('d', 'Impressum geändert'),
      ]),
    ).toEqual([
      { key: 'a', label: 'Impressum geändert', count: 2, upTo: 2 },
      { key: 'c', label: 'Würde geändert', count: 1, upTo: 3 },
      { key: 'd', label: 'Impressum geändert', count: 1, upTo: 4 },
    ])
  })
})
