import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const assignment = {
  id: 5,
  person_name: null,
  user_email: 'erika@example.org',
  user_name: 'Erika Beispiel',
  role: 1,
  role_name: 'Kassiererin',
  valid_from: '2026-10-28',
  valid_until: null,
  is_active: true,
}

describe('Rollenzuordnung bearbeiten', () => {
  it('ändert den Zeitraum einer Zuordnung', async () => {
    const calls = fakeApi({
      'GET /_allauth/browser/v1/auth/session': () => ({
        status: 200,
        body: { data: { user: testUser } },
      }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/roles/': () => ({
        status: 200,
        body: [
          {
            id: 1,
            name: 'Kassiererin',
            description: '',
            is_board: true,
            permissions: [],
            assignment_count: 1,
          },
        ],
      }),
      'GET /api/orgs/7/assignments/': () => ({ status: 200, body: [assignment] }),
      'GET /api/permissions/?org_type=club&org=7': () => ({ status: 200, body: [] }),
      'PATCH /api/orgs/7/assignments/5/': () => ({
        status: 200,
        body: { ...assignment, valid_from: '2019-02-01' },
      }),
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
    const user = userEvent.setup()
    const row = (await screen.findByText('erika@example.org')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Bearbeiten' }))
    const from = within(row).getByLabelText('von')
    await user.clear(from)
    await user.type(from, '2019-02-01')
    await user.click(within(row).getByRole('button', { name: 'Speichern' }))
    const patch = calls.find((c) => c.key === 'PATCH /api/orgs/7/assignments/5/')
    expect(patch && JSON.parse(String(patch.init?.body))).toEqual({
      valid_from: '2019-02-01',
      valid_until: null,
    })
  })
})
