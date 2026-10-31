import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { SharingPanel } from '../pages/events/EventsPage.tsx'
import { fakeApi, testUser } from './fakeApi.ts'

const session = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})

const sharing = {
  share_up: false,
  share_down: true,
  up_possible: true,
  down_possible: true,
  editable: true,
  units: [
    {
      id: 11,
      name: 'Jägerzug',
      share_up: true,
      share_down: true,
      has_children: false,
      own_admin: false,
    },
    {
      id: 12,
      name: 'Grenadiere',
      share_up: true,
      share_down: true,
      has_children: false,
      own_admin: true,
    },
  ],
}

describe('Weitergabe der Termine', () => {
  it('eigene Voreinstellung und die der Untereinheiten ohne eigene Verwaltung', async () => {
    const calls = fakeApi({
      'GET /_allauth/browser/v1/auth/session': session,
      'GET /api/orgs/7/events/sharing/': () => ({ status: 200, body: sharing }),
      'PATCH /api/orgs/7/events/sharing/': (init) => {
        const body = JSON.parse(String(init?.body))
        return { status: 200, body: { ...sharing, ...('share_up' in body ? body : {}) } }
      },
    })
    render(
      <MemoryRouter>
        <AuthProvider>
          <OrgProvider>
            <SharingPanel base="/api/orgs/7/" />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    const up = await screen.findByRole('checkbox', { name: /Nach oben weitergeben/ })
    expect(up).not.toBeChecked()
    await user.click(up)
    expect(await screen.findByRole('checkbox', { name: /Nach oben weitergeben/ })).toBeChecked()

    expect(
      screen.getByRole('checkbox', { name: 'Grenadiere: nach oben weitergeben' }),
    ).toBeDisabled()
    expect(screen.getByText('entscheidet selbst')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Jägerzug: nach oben weitergeben' }))
    const patches = calls.filter((c) => c.key === 'PATCH /api/orgs/7/events/sharing/')
    expect(JSON.parse(String(patches[1].init?.body))).toEqual({
      units: [{ id: 11, share_up: false }],
    })
  })
})
