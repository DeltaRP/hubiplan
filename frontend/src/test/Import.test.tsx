import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const ORG = testOrg({ permissions: ['members.view', 'members.edit'] })
const base = '/api/orgs/7'

const job = {
  id: 4,
  file_name: 'altdaten.csv',
  status: 'validated',
  status_label: 'geprüft',
  headers: ['Name', 'Vorname'],
  sample: [['Muster', 'Erika']],
  row_count: 1,
  mapping: { '0': 'last_name', '1': 'first_name' },
  value_mapping: {},
  options: { link_duplicates: true },
  preview: [{ rows: [2], name: 'Muster, Erika', birth_date: null, status: 'ok', messages: [] }],
  counts: { ok: 1, errors: 0, persons: 1, rows: 1, duplicates: 0 },
  error: '',
  created_at: '2026-10-25T10:00:00Z',
  imported_at: null,
  has_error_file: false,
  undo_blockers: [],
  purged_at: null,
}

describe('Import', () => {
  it('verlangt nach geänderter Zuordnung eine neue Prüfung', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/imports/`]: () => ({ status: 200, body: [job] }),
      [`GET ${base}/import-targets/`]: () => ({
        status: 200,
        body: [
          { key: 'last_name', label: 'Nachname' },
          { key: 'first_name', label: 'Vorname' },
          { key: 'city', label: 'Ort' },
        ],
      }),
      [`GET ${base}/import-templates/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}/member-types/`]: () => ({ status: 200, body: [] }),
      [`GET ${base}/departments/`]: () => ({ status: 200, body: [] }),
    })
    render(
      <MemoryRouter initialEntries={['/mitglieder/import']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'altdaten.csv' }))
    const importButton = await screen.findByRole('button', { name: 'Jetzt importieren' })
    expect(importButton).toBeEnabled()
    await user.selectOptions(screen.getByLabelText('Feld für Vorname'), 'city')
    expect(screen.getByText(/Zuordnung geändert – bitte erneut prüfen/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Jetzt importieren' })).toBeDisabled()
    // Zurück auf den geprüften Stand: wieder freigegeben
    await user.selectOptions(screen.getByLabelText('Feld für Vorname'), 'first_name')
    expect(screen.getByRole('button', { name: 'Jetzt importieren' })).toBeEnabled()
    expect(calls.some((c) => c.key.includes('/run/'))).toBe(false)
  })
})
