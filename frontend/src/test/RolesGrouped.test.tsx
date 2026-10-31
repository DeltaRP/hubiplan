import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const base = {
  person_name: null,
  user_email: 'simon@example.org',
  user_name: 'Simon Beispiel',
  valid_until: null,
  is_active: true,
}

describe('Benutzer mit mehreren Rollen', () => {
  it('steht einmal da, jede Rolle mit eigenem Zeitraum und eigenen Knöpfen', async () => {
    fakeApi({
      'GET /_allauth/browser/v1/auth/session': () => ({
        status: 200,
        body: { data: { user: testUser } },
      }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/roles/': () => ({ status: 200, body: [] }),
      'GET /api/permissions/?org_type=club&org=7': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/assignments/': () => ({
        status: 200,
        body: [
          { ...base, id: 1, role: 1, role_name: 'Adjutant', valid_from: '2026-10-28' },
          {
            ...base,
            id: 2,
            role: 2,
            role_name: 'Kassenprüfer',
            user_email: 'otto@example.org',
            user_name: 'Otto Muster',
            valid_from: '2026-01-01',
          },
          { ...base, id: 3, role: 3, role_name: '1. Kassierer', valid_from: '2026-10-20' },
        ],
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
    expect(await screen.findAllByText('simon@example.org')).toHaveLength(1)
    const first = screen.getByText('Adjutant').closest('tr')!
    const second = screen.getByText('1. Kassierer').closest('tr')!
    // Die Rollen derselben Person stehen direkt untereinander
    expect(first.nextElementSibling).toBe(second)
    expect(within(first).getByText('simon@example.org').closest('td')).toHaveAttribute(
      'rowspan',
      '2',
    )
    expect(within(first).getByText('2 Rollen, es gelten alle Rechte')).toBeInTheDocument()
    for (const row of [first, second]) {
      expect(within(row).getByRole('button', { name: 'Bearbeiten' })).toBeInTheDocument()
      expect(within(row).getByRole('button', { name: 'Beenden' })).toBeInTheDocument()
    }
    expect(within(second).getByText('20.10.2026 – heute')).toBeInTheDocument()
  })
})
