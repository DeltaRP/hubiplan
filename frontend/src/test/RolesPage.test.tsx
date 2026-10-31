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

const role = (id: number, name: string, assignment_count: number) => ({
  id,
  name,
  description: '',
  permissions: [],
  is_board: true,
  assignment_count,
})

function setup() {
  let roles = [role(3, 'Kassierer', 2), role(4, 'Beisitzer', 0)]
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    'GET /api/orgs/7/roles/': () => ({ status: 200, body: roles }),
    'GET /api/permissions/?org_type=club&org=7': () => ({ status: 200, body: [] }),
    'GET /api/orgs/7/assignments/': () => ({ status: 200, body: [] }),
    'DELETE /api/orgs/7/roles/3/': () => {
      roles = roles.filter((r) => r.id !== 3)
      return { status: 204 }
    },
    'DELETE /api/orgs/7/roles/4/': () => {
      roles = roles.filter((r) => r.id !== 4)
      return { status: 204 }
    },
  })
  render(
    <MemoryRouter initialEntries={['/einstellungen/rollen']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

// Rollenname nur in der Tabelle suchen (er steht auch im Zuordnungsformular)
const IN_TABLE = { selector: 'td > strong' }

async function openRole(name: string) {
  const user = userEvent.setup()
  const row = (await screen.findByText(name, IN_TABLE)).closest('tr') as HTMLElement
  await user.click(within(row).getByRole('button', { name: 'Bearbeiten' }))
  await user.click(screen.getByRole('button', { name: 'Löschen' }))
  return user
}

describe('Rollen löschen', () => {
  it('löscht eine vergebene Rolle nach Rückfrage mit Anzahl der Zuordnungen', async () => {
    const calls = setup()
    const user = await openRole('Kassierer')
    const dialog = await screen.findByRole('alertdialog', { name: 'Rolle „Kassierer“ löschen?' })
    expect(dialog).toHaveTextContent('2 Benutzer haben diese Rolle noch.')
    expect(dialog).toHaveTextContent('Alle 2 Zuordnungen werden beendet')
    await user.click(within(dialog).getByRole('button', { name: 'Löschen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/roles/3/')).toBe(true),
    )
    await waitFor(() => expect(screen.queryByText('Kassierer', IN_TABLE)).not.toBeInTheDocument())
  })

  it('fragt bei einer freien Rolle ohne Hinweis auf Zuordnungen', async () => {
    const calls = setup()
    const user = await openRole('Beisitzer')
    const dialog = await screen.findByRole('alertdialog', { name: 'Rolle „Beisitzer“ löschen?' })
    expect(dialog).not.toHaveTextContent('Zuordnung')
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen' }))
    expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/roles/4/')).toBe(false)
  })
})
