import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const received = {
  id: 4,
  subject: 'Königsschießen',
  sender: 'Testbund',
  kind_label: 'Vereinsmitteilung',
  sent_at: '2026-10-20T10:00:00Z',
  channel: 'mail',
}

function renderApp(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Menüpunkt Rundschreiben', () => {
  it('Verein ohne Verfassen-Recht sieht empfangene Rundschreiben', async () => {
    fakeApi({
      [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ permissions: ['members.view'] })],
      }),
      'GET /api/orgs/7/circulars/received/': () => ({ status: 200, body: [received] }),
      'GET /api/orgs/7/circulars/received/4/': () => ({
        status: 200,
        body: { ...received, body: 'Bitte **pünktlich** sein.', attachments: [] },
      }),
    })
    renderApp('/rundschreiben')
    const nav = within(await screen.findByRole('navigation', { name: 'Module' }))
    expect(await nav.findByRole('link', { name: 'Rundschreiben' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Verfassen' })).not.toBeInTheDocument()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Königsschießen' }))
    expect((await screen.findByText('pünktlich')).tagName).toBe('STRONG')
  })

  it('alte Adresse unter Mitglieder leitet weiter', async () => {
    fakeApi({
      [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ permissions: ['members.view', 'circulars.send'] })],
      }),
      'GET /api/orgs/7/circulars/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/circulars/options/': () => ({ status: 200, body: {} }),
      'GET /api/orgs/7/circulars/templates/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/circulars/received/': () => ({ status: 200, body: [] }),
    })
    renderApp('/mitglieder/rundschreiben')
    expect(await screen.findByRole('link', { name: 'Verfassen' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Empfangen' })).toBeInTheDocument()
  })
})
