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
const KASSIERER = { id: 3, name: 'Kassierer' }

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** Server mit Ansicht in der Sitzung: Rechte schrumpfen während der Ansicht. */
function server() {
  let active: typeof KASSIERER | null = null
  const state = () => ({
    status: 200,
    body: { available: true, roles: [{ id: 1, name: 'Vorstand' }, KASSIERER], active },
  })
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({
      status: 200,
      body: [
        testOrg({
          permissions: active ? ['org.edit'] : ['members.view', 'org.edit', 'roles.preview'],
          role_preview: { available: true, active },
        }),
      ],
    }),
    'GET /api/orgs/7/ansicht/': state,
    'POST /api/orgs/7/ansicht/': () => {
      active = KASSIERER
      return state()
    },
    'DELETE /api/orgs/7/ansicht/': () => {
      active = null
      return state()
    },
  })
  return calls
}

describe('Ansicht als Rolle', () => {
  it('zeigt die Auswahl nur mit dem Recht dafür', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp()
    await screen.findByRole('heading', { name: 'TV Beispielhausen' })
    expect(screen.queryByRole('combobox', { name: 'Ansicht als Rolle' })).not.toBeInTheDocument()
  })

  it('wechselt in die Ansicht einer Rolle und zurück', async () => {
    const calls = server()
    renderApp()
    const user = userEvent.setup()
    const select = await screen.findByRole('combobox', { name: 'Ansicht als Rolle' })
    await within(select).findByRole('option', { name: 'Ansicht als Kassierer' })
    const nav = screen.getByRole('navigation', { name: 'Module' })
    expect(nav).toHaveTextContent('Mitglieder')

    await user.selectOptions(select, 'Ansicht als Kassierer')
    const banner = await screen.findByText(/Ändern ist ausgeschaltet/)
    expect(banner).toHaveTextContent('Ansicht als „Kassierer“')
    const start = calls.find((c) => c.key === 'POST /api/orgs/7/ansicht/')!
    expect(JSON.parse(String(start.init?.body))).toEqual({ role: 3 })
    // Menü wie für die Rolle: ohne Leserecht keine Mitglieder
    expect(nav).not.toHaveTextContent('Mitglieder')
    // Rückgängig gibt es in der Ansicht nicht
    expect(screen.queryByRole('button', { name: /Rückgängig/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Ansicht beenden' }))
    expect(await screen.findByRole('navigation', { name: 'Module' })).toHaveTextContent(
      'Mitglieder',
    )
    expect(screen.queryByText(/Ändern ist ausgeschaltet/)).not.toBeInTheDocument()
    expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/ansicht/')).toBe(true)
  })
})
