import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/fields/'
const field = (id: number, label: string, archived = false, inherited = false) => ({
  id,
  label,
  key: label.toLowerCase(),
  field_type: 'text',
  choices: [],
  repeatable: false,
  subfields: [],
  federation_wide: inherited,
  help_text: '',
  sort_order: 0,
  is_archived: archived,
  inherited,
  owner_name: inherited ? 'Dachverband' : 'Verein',
  in_use: true,
})

function setup(fields: ReturnType<typeof field>[], extra = {}) {
  return fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    [`GET ${base}`]: () => ({ status: 200, body: fields }),
    ...extra,
  })
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/einstellungen/zusatzfelder']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Zusatzfelder löschen', () => {
  it('löscht ein benutztes Feld erst nach Bestätigung samt Werten', async () => {
    const calls = setup([field(1, 'Notiz'), field(9, 'Ehrennadel', false, true)], {
      [`GET ${base}1/usage/`]: () => ({
        status: 200,
        body: { deletable: false, value_count: 12, is_archived: false },
      }),
      [`DELETE ${base}1/?mit_werten=1`]: () => ({ status: 204 }),
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Notiz löschen' }))
    // Felder des Dachverbands kann der Verein nicht löschen
    expect(screen.queryByRole('button', { name: 'Ehrennadel löschen' })).not.toBeInTheDocument()
    expect(await screen.findByText(/bei 12 Personen ausgefüllt/)).toBeInTheDocument()
    const remove = screen.getByRole('button', { name: 'Samt Werten löschen' })
    expect(remove).toBeDisabled()
    await user.click(screen.getByLabelText(/alle Werte bei 12 Personen endgültig löschen/))
    await user.click(remove)
    expect(await screen.findByText('„Notiz“ wurde gelöscht.')).toBeInTheDocument()
    expect(calls.some((c) => c.key === `DELETE ${base}1/?mit_werten=1`)).toBe(true)
  })

  it('archiviert, löscht unbenutzte Felder und stellt wieder her', async () => {
    const calls = setup([field(1, 'Notiz'), field(2, 'Leer'), field(3, 'Alt', true)], {
      [`GET ${base}1/usage/`]: () => ({
        status: 200,
        body: { deletable: false, value_count: 1, is_archived: false },
      }),
      [`POST ${base}1/archive/`]: () => ({ status: 200, body: field(1, 'Notiz', true) }),
      [`GET ${base}2/usage/`]: () => ({
        status: 200,
        body: { deletable: true, value_count: 0, is_archived: false },
      }),
      [`DELETE ${base}2/`]: () => ({ status: 204 }),
      [`POST ${base}3/restore/`]: () => ({ status: 200, body: field(3, 'Alt') }),
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Notiz löschen' }))
    await user.click(await screen.findByRole('button', { name: 'Archivieren' }))
    expect(await screen.findByText('„Notiz“ wurde archiviert.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Leer löschen' }))
    expect(await screen.findByText(/bei niemandem ausgefüllt/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Löschen' }))
    expect(await screen.findByText('„Leer“ wurde gelöscht.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Wiederherstellen' }))
    expect(await screen.findByText('„Alt“ ist wieder verfügbar.')).toBeInTheDocument()
    expect(calls.some((c) => c.key === `POST ${base}1/archive/`)).toBe(true)
    expect(calls.some((c) => c.key === `DELETE ${base}2/`)).toBe(true)
  })
})
