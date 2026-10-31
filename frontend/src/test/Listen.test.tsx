import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const ORG = testOrg({ permissions: ['audit.view', 'org.edit'] })
const base = '/api/orgs/7'

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

const entry = (id: number, repr: string) => ({
  id,
  timestamp: '2026-10-24T10:00:00Z',
  user_email: 'vorstand@example.org',
  action: 'update',
  action_label: 'geändert',
  object_type: 'Mitglied',
  object_repr: repr,
  changes: {},
  undo: null,
})

describe('Änderungsprotokoll', () => {
  it('blättert und sucht auf dem Server', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/audit/`]: () => ({
        status: 200,
        body: { count: 230, page: 1, pages: 5, results: [entry(1, 'Person 230')] },
      }),
      [`GET ${base}/audit/?seite=2`]: () => ({
        status: 200,
        body: { count: 230, page: 2, pages: 5, results: [entry(2, 'Person 180')] },
      }),
      [`GET ${base}/audit/?q=Person+001&von=2026-01-01`]: () => ({
        status: 200,
        body: { count: 1, page: 1, pages: 1, results: [entry(3, 'Person 001')] },
      }),
    })
    renderAt('/einstellungen/protokoll')
    const user = userEvent.setup()
    expect(await screen.findByText(/Person 230/)).toBeInTheDocument()
    expect(screen.getByText('230 Einträge · Seite 1 von 5')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(await screen.findByText(/Person 180/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Suchen'), 'Person 001')
    await user.type(screen.getByLabelText('von'), '2026-01-01')
    await user.click(screen.getByRole('button', { name: 'Suchen' }))
    expect(await screen.findByText(/Person 001/)).toBeInTheDocument()
    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(`GET ${base}/audit/?q=Person+001&von=2026-01-01`),
    )
  })
})

describe('Postausgang', () => {
  it('filtert nach Status', async () => {
    const mail = {
      id: 1,
      created_at: '2026-10-24T10:00:00Z',
      organization_name: null,
      to: 'm@example.org',
      reply_to: '',
      subject: 'Rechnung 2026',
      body: 'x',
      kind: '',
      status: 'failed',
      status_label: 'Versand fehlgeschlagen',
      error: '',
      attachments: [],
    }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/outbox/`]: () => ({
        status: 200,
        body: { count: 0, page: 1, pages: 1, results: [] },
      }),
      [`GET ${base}/outbox/?status=failed`]: () => ({
        status: 200,
        body: { count: 1, page: 1, pages: 1, results: [mail] },
      }),
    })
    renderAt('/einstellungen/postausgang')
    const user = userEvent.setup()
    expect(await screen.findByText('Noch keine Mails.')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Status'), 'failed')
    expect(await screen.findByText('Rechnung 2026')).toBeInTheDocument()
    expect(calls.map((c) => c.key)).toContain(`GET ${base}/outbox/?status=failed`)
  })
})
