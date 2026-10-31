import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function renderApp(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
          <Where />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

function setup(org = testOrg(), extra = {}) {
  return fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    ...extra,
  })
}

const detail = (overrides = {}) => ({
  id: 7,
  type: 'club',
  type_label: 'Verein',
  name: 'TV Beispielhausen',
  jubilee_years: [10, 25],
  date_precision: 'day',
  federation_duration_rule: 'all_reported',
  member_portal_enabled: false,
  contact_changes_need_approval: true,
  photo_approval_required: false,
  ...overrides,
})

describe('Mitglieder: Unterpunkte', () => {
  it('zeigt im Verein Liste, Entwicklung, Jubiläen, Anfragen, Import und Einrichtung', async () => {
    setup(testOrg({ permissions: ['members.view', 'members.edit', 'org.edit'] }), {
      'GET /api/orgs/7/member-types/': () => ({ status: 200, body: [] }),
    })
    renderApp('/mitglieder/einrichtung')
    const nav = within(await screen.findByRole('navigation', { name: 'Module' }))
    const labels = [
      'Mitgliederliste',
      'Entwicklung',
      'Jubiläen',
      'Anfragen',
      'Import',
      'Einrichtung',
    ]
    for (const label of labels) {
      expect(await nav.findByRole('link', { name: label })).toBeInTheDocument()
    }
    // Einrichtung beginnt mit den Mitgliedsarten
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        '/mitglieder/einrichtung/mitgliedsarten',
      ),
    )
    // Unterpunkte stehen in der Seitenleiste, nicht als Reiter (UX-Audit 31.10. W09)
    expect(await nav.findByRole('link', { name: 'Zusatzfelder' })).toBeInTheDocument()
    const tabs = nav
    expect(tabs.getByRole('link', { name: 'Jubiläen & Dauer' })).toBeInTheDocument()
    expect(tabs.getByRole('link', { name: 'Mitgliederbereich & Fotos' })).toBeInTheDocument()
  })

  it('blendet Import ohne Bearbeitungsrecht aus', async () => {
    setup(testOrg({ permissions: ['members.view'] }), {
      'GET /api/orgs/7/member-types/': () => ({ status: 200, body: [] }),
    })
    renderApp('/mitglieder/einrichtung/mitgliedsarten')
    const nav = within(await screen.findByRole('navigation', { name: 'Module' }))
    expect(await nav.findByRole('link', { name: 'Einrichtung' })).toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Import' })).not.toBeInTheDocument()
  })

  it('leitet alte Adressen weiter', async () => {
    setup(testOrg(), {
      'GET /api/orgs/7/member-types/': () => ({ status: 200, body: [] }),
    })
    renderApp('/einstellungen/mitgliedsarten')
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(
        '/mitglieder/einrichtung/mitgliedsarten',
      ),
    )
  })

  it('leitet alte Wechselanfragen auf Anfragen um', async () => {
    setup(testOrg(), {
      'GET /api/orgs/7/transfers/': () => ({ status: 200, body: [] }),
    })
    renderApp('/mitglieder/wechsel')
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent(/^\/mitglieder\/anfragen$/),
    )
    expect(await screen.findByRole('heading', { name: 'Wechselanfragen' })).toBeInTheDocument()
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(await nav.findByRole('link', { name: 'Änderungsmeldungen' })).toBeInTheDocument()
  })

  it('führt Mitgliedsarten und Zusatzfelder nicht mehr in den Einstellungen', async () => {
    setup(testOrg(), {
      'GET /api/orgs/7/': () => ({ status: 200, body: detail() }),
      'GET /api/orgs/7/roles/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/statutes/': () => ({ status: 404, body: {} }),
    })
    renderApp('/einstellungen/organisation')
    await screen.findByRole('heading', { name: 'Einstellungen' })
    // Unterpunkte der Einstellungen stehen in der Seitenleiste (UX-Audit 31.10. W09)
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(await nav.findByRole('link', { name: 'Organisation' })).toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Mitgliedsarten' })).not.toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Zusatzfelder' })).not.toBeInTheDocument()
  })
})

describe('Mitglieder › Einrichtung › Jubiläen & Dauer', () => {
  it('speichert nur die Felder der Seite', async () => {
    const calls = setup(testOrg(), {
      'GET /api/orgs/7/': () => ({ status: 200, body: detail() }),
      'PATCH /api/orgs/7/': () => ({ status: 200, body: detail({ date_precision: 'year' }) }),
    })
    renderApp('/mitglieder/einrichtung/jubilaeen')
    const select = await screen.findByLabelText(/Genauigkeit für Mitgliedschaften und Jubiläen/)
    await userEvent.setup().selectOptions(select, 'year')
    await waitFor(() => expect(calls.some((c) => c.key === 'PATCH /api/orgs/7/')).toBe(true), {
      timeout: 3000,
    })
    const patch = calls.find((c) => c.key === 'PATCH /api/orgs/7/')!
    expect(JSON.parse(String(patch.init?.body))).toEqual({ date_precision: 'year' })
  })
})
