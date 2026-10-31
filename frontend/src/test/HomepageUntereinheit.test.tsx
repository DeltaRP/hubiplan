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

const zug = {
  id: 5,
  name: 'Jägerzug',
  founding_year: null,
  website: '',
  website_on_site: false,
  sort_order: 0,
  is_active: true,
  fiscal_start_month: 1,
  fiscal_start_day: 1,
  logo_url: null,
  roles: [],
}

function renderPage(modules: string[]) {
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg({ modules })] }),
    'GET /api/orgs/7/departments/': () => ({ status: 200, body: [zug] }),
    'GET /api/permissions/?org_type=department&org=7': () => ({ status: 200, body: [] }),
    'GET /api/orgs/7/statutes/?department=5': () => ({
      status: 200,
      body: { versions: [], publication: { is_public: false }, can_manage: true },
    }),
    'PATCH /api/orgs/7/departments/5/': () => ({ status: 200, body: zug }),
  })
  render(
    <MemoryRouter initialEntries={['/untereinheiten']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Homepage einer Untereinheit', () => {
  it('speichert die Adresse und den Schalter für die Webseite', async () => {
    const calls = renderPage(['members', 'website'])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jägerzug bearbeiten' }))
    const link = screen.getByRole('checkbox', { name: /Homepage auf der Webseite verlinken/ })
    // Ohne Adresse gibt es nichts zu verlinken
    expect(link).toBeDisabled()
    await user.type(screen.getByLabelText(/Homepage \(optional\)/), 'www.jaegerzug.example')
    expect(link).toBeEnabled()
    await user.click(link)
    await waitFor(() => {
      const bodies = calls
        .filter((c) => c.key === 'PATCH /api/orgs/7/departments/5/')
        .map((c) => JSON.parse(String(c.init?.body)))
      expect(Object.assign({}, ...bodies)).toMatchObject({
        website: 'www.jaegerzug.example',
        website_on_site: true,
      })
    })
  })

  it('ohne Modul Webseite nur das Feld, kein Schalter', async () => {
    renderPage(['members'])
    await userEvent.click(await screen.findByRole('button', { name: 'Jägerzug bearbeiten' }))
    expect(screen.getByLabelText(/Homepage \(optional\)/)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /Homepage auf der Webseite/ })).toBeNull()
  })
})

describe('Bild der Homepage', () => {
  function renderWith(dep: Record<string, unknown>) {
    const unit = { ...zug, website: 'https://www.jaegerzug.example', website_on_site: true, ...dep }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ modules: ['members', 'website'] })],
      }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [unit] }),
      'GET /api/permissions/?org_type=department&org=7': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/statutes/?department=5': () => ({
        status: 200,
        body: { versions: [], publication: { is_public: false }, can_manage: true },
      }),
      'PATCH /api/orgs/7/departments/5/': () => ({ status: 200, body: unit }),
      'DELETE /api/orgs/7/departments/5/homepage-image/': () => ({
        status: 200,
        body: {
          website_image_url: null,
          message: 'Die Homepage bietet kein Vorschaubild an (og:image fehlt).',
        },
      }),
    })
    render(
      <MemoryRouter initialEntries={['/untereinheiten']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    return calls
  }

  it('zeigt das geholte Bild und kann es neu holen', async () => {
    const calls = renderWith({ website_image_url: '/media/homepages/5.jpg' })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Jägerzug bearbeiten' }))
    expect(screen.getByRole('img', { name: 'Bild der Homepage' })).toHaveAttribute(
      'src',
      '/media/homepages/5.jpg',
    )
    expect(screen.getByText(/Von der Homepage übernommen/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Neu von der Homepage holen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/departments/5/homepage-image/')).toBe(
        true,
      ),
    )
  })

  it('ohne Bild: Hinweis und eigenes Bild hochladen', async () => {
    renderWith({ website_image_url: null })
    await userEvent.click(await screen.findByRole('button', { name: 'Jägerzug bearbeiten' }))
    expect(screen.getByText(/Noch kein Bild/)).toBeInTheDocument()
    expect(screen.getByLabelText('Eigenes Bild hochladen')).toBeInTheDocument()
  })

  it('ohne Link auf der Webseite kein Bildfeld', async () => {
    renderWith({ website_on_site: false })
    await userEvent.click(await screen.findByRole('button', { name: 'Jägerzug bearbeiten' }))
    expect(screen.queryByTestId('homepage-image')).toBeNull()
  })
})
