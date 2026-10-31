// Anmelden über eine gekoppelte Instanz (erfundene Daten).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { leaveTo } from '../api/peering.ts'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { LoginPage } from '../pages/LoginPage.tsx'
import { RemoteLoginCard } from '../pages/settings/RemoteLoginCard.tsx'
import { VerbundConfirmPage, VerbundFinishPage } from '../pages/VerbundLoginPages.tsx'
import { fakeApi, testUser } from './fakeApi.ts'

const anonymous = () => ({ status: 401, body: { status: 401, data: { flows: [] }, meta: {} } })
const session = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})
const VERBAND = '11111111-1111-1111-1111-111111111111'
const VEREIN = '22222222-2222-2222-2222-222222222222'

function renderAt(path: string, routes: Parameters<typeof fakeApi>[0], ui: React.ReactNode) {
  const calls = fakeApi(routes)
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="*" element={ui} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

afterEach(() => vi.restoreAllMocks())

describe('Anmelden über andere Instanz', () => {
  it('Anmeldeseite bietet gekoppelte Instanzen an', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    const calls = renderAt(
      '/anmelden',
      {
        'GET /_allauth/browser/v1/auth/session': anonymous,
        'GET /api/peering/sso/choices/': () => ({
          status: 200,
          body: [{ instance_id: VERBAND, base_url: 'https://verband.example' }],
        }),
        'POST /api/peering/sso/start/': () => ({
          status: 200,
          body: { url: 'https://verband.example/verbund/anmelden?rp=x&state=y&purpose=login' },
        }),
      },
      <LoginPage />,
    )
    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Anmelden mit verband.example' }))
    await waitFor(() => expect(go).toHaveBeenCalled())
    expect(go.mock.calls[0][0]).toContain('https://verband.example/verbund/anmelden')
    const start = calls.find((c) => c.key === 'POST /api/peering/sso/start/')
    expect(JSON.parse(String(start?.init?.body))).toEqual({
      idp: VERBAND,
      purpose: 'login',
      next: '/',
    })
  })

  it('Heimat-Instanz fragt vor dem Verknüpfen', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    const calls = renderAt(
      `/verbund/anmelden?rp=${VEREIN}&state=abc&purpose=link`,
      {
        'GET /_allauth/browser/v1/auth/session': session,
        [`GET /api/peering/sso/describe/?rp=${VEREIN}`]: () => ({
          status: 200,
          body: { base_url: 'https://verein.example', fingerprint: 'AAAA', linked: false },
        }),
        'POST /api/peering/sso/issue/': () => ({
          status: 200,
          body: { url: 'https://verein.example/verbund/angemeldet#tok' },
        }),
      },
      <VerbundConfirmPage />,
    )
    expect(await screen.findByText(/mit deinem Konto dort verknüpfen/)).toBeInTheDocument()
    expect(go).not.toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Verknüpfen' }))
    await waitFor(() =>
      expect(go).toHaveBeenCalledWith('https://verein.example/verbund/angemeldet#tok'),
    )
    const issue = calls.find((c) => c.key === 'POST /api/peering/sso/issue/')
    expect(JSON.parse(String(issue?.init?.body))).toEqual({
      rp: VEREIN,
      state: 'abc',
      purpose: 'link',
    })
  })

  it('schon verknüpft: Wechsel ohne Rückfrage', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    renderAt(
      `/verbund/anmelden?rp=${VEREIN}&state=abc&purpose=login`,
      {
        'GET /_allauth/browser/v1/auth/session': session,
        [`GET /api/peering/sso/describe/?rp=${VEREIN}`]: () => ({
          status: 200,
          body: { base_url: 'https://verein.example', fingerprint: 'AAAA', linked: true },
        }),
        'POST /api/peering/sso/issue/': () => ({
          status: 200,
          body: { url: 'https://verein.example/verbund/angemeldet#tok' },
        }),
      },
      <VerbundConfirmPage />,
    )
    await waitFor(() => expect(go).toHaveBeenCalledTimes(1))
  })

  it('alte Anmeldung: erst Passwort und Code bestätigen', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    const calls = renderAt(
      `/verbund/anmelden?rp=${VEREIN}&state=abc&purpose=login`,
      {
        'GET /_allauth/browser/v1/auth/session': session,
        [`GET /api/peering/sso/describe/?rp=${VEREIN}`]: () => ({
          status: 200,
          body: { base_url: 'https://verein.example', fingerprint: 'AAAA', linked: false },
        }),
        'POST /api/peering/sso/issue/': (init) =>
          JSON.parse(String(init?.body)).password
            ? { status: 200, body: { url: 'https://verein.example/verbund/angemeldet#tok' } }
            : {
                status: 409,
                body: { detail: 'Bitte bestätigen.', reauth: true, needs_code: true },
              },
      },
      <VerbundConfirmPage />,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Bei verein.example anmelden' }))
    expect(await screen.findByLabelText('Passwort')).toBeInTheDocument()
    expect(go).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText('Passwort'), 'geheim-erfunden')
    await user.type(screen.getByLabelText('Code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Bei verein.example anmelden' }))
    await waitFor(() => expect(go).toHaveBeenCalled())
    const issues = calls.filter((c) => c.key === 'POST /api/peering/sso/issue/')
    expect(JSON.parse(String(issues[1].init?.body))).toMatchObject({
      password: 'geheim-erfunden',
      code: '123456',
    })
  })

  it('Konto mit Rollen: eigener Code als zweiter Schritt', async () => {
    const calls = renderAt(
      '/verbund/angemeldet#TOKEN123',
      {
        'GET /_allauth/browser/v1/auth/session': anonymous,
        'POST /api/peering/sso/finish/': (init) =>
          JSON.parse(String(init?.body)).code
            ? { status: 200, body: { purpose: 'login', next: '/', user: testUser } }
            : { status: 200, body: { purpose: 'login', mfa_required: true } },
      },
      <VerbundFinishPage />,
    )
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Code'), '654321')
    await user.click(screen.getByRole('button', { name: 'Anmelden' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.key === 'POST /api/peering/sso/finish/')).toHaveLength(2),
    )
    const second = calls.filter((c) => c.key === 'POST /api/peering/sso/finish/')[1]
    expect(JSON.parse(String(second.init?.body))).toEqual({ code: '654321' })
  })

  it('Bestätigung einlösen meldet an', async () => {
    const calls = renderAt(
      '/verbund/angemeldet#TOKEN123',
      {
        'GET /_allauth/browser/v1/auth/session': anonymous,
        'POST /api/peering/sso/finish/': () => ({
          status: 200,
          body: { purpose: 'login', next: '/', user: testUser },
        }),
      },
      <VerbundFinishPage />,
    )
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'POST /api/peering/sso/finish/')).toBe(true),
    )
    const finish = calls.find((c) => c.key === 'POST /api/peering/sso/finish/')
    expect(JSON.parse(String(finish?.init?.body))).toEqual({ token: 'TOKEN123' })
  })

  it('Mein Konto: verknüpfen und lösen', async () => {
    const go = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    const calls = renderAt(
      '/mein-konto/app',
      {
        'GET /_allauth/browser/v1/auth/session': session,
        'GET /api/peering/sso/account/': () => ({
          status: 200,
          body: {
            login_enabled: true,
            links: [
              {
                id: 4,
                base_url: 'https://verband.example',
                email: 'verband@example.org',
                created_at: '2026-10-30T07:00:00Z',
                last_used_at: null,
              },
            ],
            linkable: [{ instance_id: VEREIN, base_url: 'https://verein.example' }],
            accounts: [],
          },
        }),
        'POST /api/peering/sso/start/': () => ({
          status: 200,
          body: { url: 'https://verein.example/verbund/anmelden?x=1' },
        }),
        'DELETE /api/peering/sso/links/4/': () => ({ status: 204 }),
      },
      <RemoteLoginCard />,
    )
    const user = userEvent.setup()
    expect(await screen.findByText(/Anmelden mit verband.example/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Zugang verknüpfen' }))
    await waitFor(() =>
      expect(go).toHaveBeenCalledWith('https://verein.example/verbund/anmelden?x=1'),
    )
    const start = calls.find((c) => c.key === 'POST /api/peering/sso/start/')
    expect(JSON.parse(String(start?.init?.body))).toEqual({
      idp: VEREIN,
      purpose: 'link',
      next: '/mein-konto/app',
    })
    await user.click(screen.getByRole('button', { name: 'Lösen' }))
    await user.click(await screen.findByRole('button', { name: /OK|Ja|Bestätigen/ }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'DELETE /api/peering/sso/links/4/')).toBe(true),
    )
  })
})
