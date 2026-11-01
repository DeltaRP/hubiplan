// Anmeldung an der Nextcloud mit dem HUBIplan-Konto (erfundene Daten).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { leaveTo } from '../api/peering.ts'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { NextcloudLoginPage } from '../pages/NextcloudLoginPage.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const session = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})
const QUERY =
  'client_id=hp-abc&redirect_uri=https%3A%2F%2Fcloud.example.org%2Fapps%2Fuser_oidc%2Fcode&response_type=code&scope=openid&state=s1'

function renderAt(routes: Parameters<typeof fakeApi>[0]) {
  const calls = fakeApi(routes)
  render(
    <MemoryRouter initialEntries={[`/oidc/anmelden?${QUERY}`]}>
      <AuthProvider>
        <Routes>
          <Route path="*" element={<NextcloudLoginPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

afterEach(() => vi.restoreAllMocks())

describe('Bei der Nextcloud anmelden', () => {
  it('geht ohne Rückfrage mit Code zurück', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    const calls = renderAt({
      'GET /_allauth/browser/v1/auth/session': session,
      'POST /api/oidc/authorize/': () => ({
        status: 200,
        body: { redirect: 'https://cloud.example.org/apps/user_oidc/code?code=x&state=s1' },
      }),
    })
    await waitFor(() =>
      expect(go).toHaveBeenCalledWith(
        'https://cloud.example.org/apps/user_oidc/code?code=x&state=s1',
      ),
    )
    const post = calls.find((c) => c.key === 'POST /api/oidc/authorize/')
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({
      client_id: 'hp-abc',
      redirect_uri: 'https://cloud.example.org/apps/user_oidc/code',
      state: 's1',
    })
  })

  it('erklärt, warum es nicht geht', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    renderAt({
      'GET /_allauth/browser/v1/auth/session': session,
      'POST /api/oidc/authorize/': () => ({
        status: 400,
        body: {
          detail: 'Dein Konto hat bei Verein A keinen Zugang zu „Nextcloud“.',
          redirect: '',
          back: 'https://cloud.example.org',
        },
      }),
    })
    expect(await screen.findByText(/keinen Zugang/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Zurück zur Nextcloud' })).toHaveAttribute(
      'href',
      'https://cloud.example.org',
    )
    expect(go).not.toHaveBeenCalled()
  })
})

describe('Einstellungen › Nextcloud', () => {
  it('trägt eine Nextcloud ein und zeigt das Geheimnis einmal', async () => {
    const org = testOrg({ permissions: ['roles.manage'] })
    const created = {
      id: 3,
      name: 'Nextcloud',
      base_url: 'https://cloud.example.org',
      client_id: 'hp-abc',
      audience: 'board',
      require_mfa: false,
      groups_board: true,
      groups_roles: true,
      groups_units: true,
      groups_members: true,
      is_active: true,
      created_at: '2026-11-01T20:00:00Z',
      last_used_at: null,
      redirect_uri: 'https://cloud.example.org/apps/user_oidc/code',
      discovery_url: 'https://verein.example.org/api/oidc/.well-known/openid-configuration',
      client_secret: 'geheim-123',
    }
    const calls = fakeApi({
      'GET /_allauth/browser/v1/auth/session': session,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/nextcloud/': () => ({ status: 200, body: [] }),
      'POST /api/orgs/7/nextcloud/': () => ({ status: 201, body: created }),
    })
    render(
      <MemoryRouter initialEntries={['/einstellungen/nextcloud']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    await user.type(
      await screen.findByLabelText('Adresse der Nextcloud'),
      'https://cloud.example.org',
    )
    await user.click(screen.getByRole('button', { name: 'Eintragen' }))
    expect(await screen.findByText('geheim-123')).toBeInTheDocument()
    expect(screen.getByText('hp-abc')).toBeInTheDocument()
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/nextcloud/')
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      name: 'Nextcloud',
      base_url: 'https://cloud.example.org',
    })
  })
})
