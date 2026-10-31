import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'

describe('Ferne Untereinheit (Verbund)', () => {
  it('ist nur zu sehen, nicht zu bearbeiten oder zu löschen', async () => {
    fakeApi({
      [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/departments/': () => ({
        status: 200,
        body: [
          {
            id: 6,
            name: 'Jägerzug Grünrock',
            founding_year: 1950,
            sort_order: 0,
            is_active: true,
            fiscal_start_month: 1,
            fiscal_start_day: 1,
            logo_url: null,
            roles: [],
            is_remote: true,
          },
        ],
      }),
      'GET /api/orgs/7/statutes/?department=6': () => ({
        status: 200,
        body: { versions: [], publication: { is_public: false }, can_manage: false },
      }),
    })
    render(
      <MemoryRouter initialEntries={['/einstellungen/untereinheiten']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jägerzug Grünrock anzeigen' }))
    expect(screen.queryByRole('button', { name: 'Jägerzug Grünrock löschen' })).toBeNull()
    expect(screen.getByText('andere Instanz')).toBeInTheDocument()
    expect(await screen.findByText(/eigenen HUBIplan-Instanz/)).toBeInTheDocument()
  })
})
