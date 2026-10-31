import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const B = '/api/orgs/7/datatransfer'

function renderApp(path: string) {
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

const verband = testOrg({
  type: 'federation',
  type_label: 'Dachverband',
  permissions: ['data.export', 'clubs.manage', 'org.edit'],
})

const preview = {
  kind: 'organization',
  type: 'club',
  name: 'Hubertus',
  source: { type: 'club', name: 'Hubertus' },
  exported_at: '2026-10-24T10:00:00+02:00',
  with_files: false,
  summary: { persons: 2, memberships: 2, roles: 1 },
  errors: [],
  error_count: 0,
  warnings: [],
  warning_count: 0,
  duplicates: [
    {
      person: 5,
      name: 'Muster, Erika',
      birth_date: '1980-05-17',
      candidates: [
        {
          id: 99,
          name: 'Muster, Erika',
          birth_date: '1980-05-17',
          member_number: 12,
          clubs: [{ name: 'Verein A', current: true }],
          member_here: false,
        },
      ],
      choice: '99',
      fixed: false,
    },
  ],
  users: { total: 1, existing: 1, new: 0 },
}

const job = (status: string, extra: Record<string, unknown> = {}) => ({
  id: 3,
  direction: 'import',
  kind: 'organization',
  status,
  status_label: status,
  with_files: false,
  file_name: 'hubertus.json',
  size: 100,
  has_file: true,
  summary: {},
  preview,
  decisions: {},
  options: {},
  error: '',
  subject: null,
  department: null,
  result_organization: null,
  created_by: 'kassenwart@example.org',
  created_at: '2026-10-24T10:00:00Z',
  finished_at: null,
  expires_at: '2026-10-31T10:00:00Z',
  ...extra,
})

describe('Datenübernahme im Dachverband', () => {
  it('Verein aus Datei: Vorschau mit Dublette, dann übernehmen', async () => {
    let state = 'checked'
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [verband] }),
      'GET /api/orgs/7/clubs/': () => ({ status: 200, body: [] }),
      [`POST ${B}/imports/`]: () => ({ status: 201, body: job('pending') }),
      [`GET ${B}/imports/3/`]: () => ({
        status: 200,
        body:
          state === 'done'
            ? job('done', { summary: { organization: { id: 9, name: 'Hubertus' } } })
            : job('checked'),
      }),
      [`PATCH ${B}/imports/3/`]: () => ({ status: 200, body: job('pending') }),
      [`POST ${B}/imports/3/run/`]: () => {
        state = 'done'
        return { status: 200, body: job('running') }
      },
    })
    const user = userEvent.setup()
    renderApp('/einstellungen/vereine')
    expect(await screen.findByText('Verein von Hand anlegen')).toBeInTheDocument()
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await user.upload(input, new File(['{}'], 'hubertus.json', { type: 'application/json' }))
    await user.click(screen.getByRole('button', { name: 'Hochladen und prüfen' }))
    expect(await screen.findByText('Mögliche Dubletten (1)')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /zusammenführen mit Muster, Erika \(Nr\. 12\)/ }))
    await user.selectOptions(screen.getByLabelText('Übernehmen als'), 'new')
    await user.click(screen.getByRole('button', { name: 'Übernehmen' }))
    expect(await screen.findByText(/„Hubertus“ wurde angelegt/)).toBeInTheDocument()
    const patch = calls.find((c) => c.key === `PATCH ${B}/imports/3/`)
    expect(JSON.parse(String(patch?.init?.body)).persons).toEqual({ '5': 'new' })
  })
  it('Untereinheit wird eigene Einheit: Anschrift angeben', async () => {
    const unit = {
      ...preview,
      kind: 'unit',
      duplicates: [],
      users: { total: 0, existing: 0, new: 0 },
    }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [verband] }),
      'GET /api/orgs/7/clubs/': () => ({ status: 200, body: [] }),
      [`POST ${B}/imports/`]: () => ({ status: 201, body: job('pending', { preview: unit }) }),
      [`GET ${B}/imports/3/`]: () => ({ status: 200, body: job('checked', { preview: unit }) }),
      [`PATCH ${B}/imports/3/`]: () => ({ status: 200, body: job('pending', { preview: unit }) }),
    })
    const user = userEvent.setup()
    renderApp('/einstellungen/vereine')
    await screen.findByText('Verein von Hand anlegen')
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await user.upload(input, new File(['{}'], 'zug.json', { type: 'application/json' }))
    await user.click(screen.getByRole('button', { name: 'Hochladen und prüfen' }))
    expect(await screen.findByText(/wird hier eine eigene Einheit/)).toBeInTheDocument()
    const box = document.querySelector('.import-preview') as HTMLElement
    await user.type(within(box).getByLabelText('Ort'), 'Neustadt')
    await user.click(screen.getByRole('button', { name: 'Erneut prüfen' }))
    const patch = calls.find((c) => c.key === `PATCH ${B}/imports/3/`)
    const body = JSON.parse(String(patch?.init?.body))
    expect(body.city).toBe('Neustadt')
    expect(body).not.toHaveProperty('street')
  })
  it('NAF-04: Auftrag aus der Adresse wird nach Neuladen fortgesetzt', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [verband] }),
      'GET /api/orgs/7/clubs/': () => ({ status: 200, body: [] }),
      [`GET ${B}/imports/`]: () => ({ status: 200, body: [job('checked')] }),
      [`GET ${B}/imports/3/`]: () => ({ status: 200, body: job('checked') }),
      [`PATCH ${B}/imports/3/`]: () => ({ status: 200, body: job('checked') }),
    })
    const user = userEvent.setup()
    renderApp('/einstellungen/untereinheiten?import=3')
    expect(await screen.findByText('Mögliche Dubletten (1)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hochladen und prüfen' })).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Übernehmen als'), 'new')
    expect(screen.getByLabelText('Übernehmen als')).toHaveValue('new')
    // Keine späte zweite Fortsetzung, die die Entscheidung zurücksetzt
    await new Promise((r) => setTimeout(r, 300))
    expect(screen.getByLabelText('Übernehmen als')).toHaveValue('new')
    expect(calls.some((c) => c.key === `GET ${B}/imports/3/`)).toBe(true)
  })
})
