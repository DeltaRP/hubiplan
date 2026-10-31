import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

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

describe('Offene Aufgaben auf der Startseite', () => {
  it('zeigt Vorgänge mit Link zur Entscheidung', async () => {
    const org = testOrg({ permissions: ['members.view', 'members.edit'] })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/open-tasks/': () => ({
        status: 200,
        body: {
          items: [
            {
              kind: 'change_request',
              kind_label: 'Änderungsmeldung',
              title: 'Erika Muster',
              detail: 'möchte eigene Daten ändern',
              created_at: '2026-10-24T10:00:00Z',
              link: '/mitglieder/anfragen/aenderungen',
            },
          ],
        },
      }),
      'GET /api/orgs/7/jubilees/?von=': () => ({ status: 200, body: [] }),
    })
    renderAt('/')
    expect(await screen.findByRole('heading', { name: /Offene Aufgaben/ })).toBeInTheDocument()
    const link = await screen.findByRole('link', { name: 'Erika Muster' })
    expect(link).toHaveAttribute('href', '/mitglieder/anfragen/aenderungen')
    expect(screen.getByText('Änderungsmeldung')).toBeInTheDocument()
  })

  it('erscheint nicht ohne Entscheidungsrecht', async () => {
    const org = testOrg({ permissions: ['members.view'], modules: [] })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    })
    renderAt('/')
    expect(await screen.findByText('Übersicht')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Offene Aufgaben/ })).not.toBeInTheDocument()
  })
})
