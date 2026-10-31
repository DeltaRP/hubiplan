// Finanzamt-Prüfung C3: Kettenprüfung des Änderungsprotokolls (erfundene Daten)
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const ORG = testOrg({ permissions: ['members.view', 'audit.view', 'org.edit'] })
const base = '/api/orgs/7'
const empty = { count: 0, page: 1, pages: 1, results: [] }

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

describe('Änderungsprotokoll: Kettenprüfung', () => {
  it('prüft auf Knopfdruck und zeigt gefundene Veränderungen', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [ORG] }),
      [`GET ${base}/audit/`]: () => ({ status: 200, body: empty }),
      [`GET ${base}/audit/kette/`]: () => ({ status: 200, body: { check: null } }),
      [`POST ${base}/audit/kette/`]: () => ({
        status: 200,
        body: {
          check: {
            checked_at: '2026-10-31T10:00:00Z',
            ok: false,
            entries: 12,
            cleared: 2,
            head_seq: 12,
            head_hash: 'a'.repeat(64),
            problems: ['Nr. 4 bis 4 fehlen (gelöscht).'],
          },
        },
      }),
    })
    renderAt('/einstellungen/protokoll')
    const user = userEvent.setup()
    expect(await screen.findByText(/noch nicht geprüft/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Jetzt prüfen' }))
    expect(await screen.findByText('Protokoll wurde verändert')).toBeInTheDocument()
    expect(screen.getByText('Nr. 4 bis 4 fehlen (gelöscht).')).toBeInTheDocument()
    expect(screen.getByText(/2 aus Datenschutzgründen geleert/)).toBeInTheDocument()
    expect(calls.some((c) => c.key === `POST ${base}/audit/kette/`)).toBe(true)
  })
})
