import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { buildFederationTerms, buildTerms, fillTerms } from '../org/terms.ts'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

describe('Abteilungsbezeichnung', () => {
  it('bildet Artikel und Fälle', () => {
    const zug = buildTerms('Zug', 'Züge', 'm')
    expect(fillTerms('Mitglieder {gen}, Rollen in {diesem}, {pl_dat}', zug)).toBe(
      'Mitglieder des Zugs, Rollen in diesem Zug, Zügen',
    )
    expect(fillTerms('Unbekannt{adj} {sg}', buildTerms('Korps', 'Korps', 'n', 'Korps'))).toBe(
      'Unbekanntes Korps',
    )
    expect(fillTerms('{Gen}', buildTerms('Abteilung', 'Abteilungen'))).toBe('Der Abteilung')
  })

  it('zeigt die Rollen eines Zugs ohne das Wort Abteilung', async () => {
    const terms = buildTerms('Zug', 'Züge', 'm')
    const org = testOrg({
      department_label: 'Zug',
      department_label_plural: 'Züge',
      department_terms: terms,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/departments/': () => ({
        status: 200,
        body: [
          {
            id: 5,
            name: '1. Zug',
            founding_year: 1950,
            sort_order: 0,
            is_active: true,
            fiscal_start_month: 1,
            fiscal_start_day: 1,
            logo_url: null,
            roles: [],
          },
        ],
      }),
      'GET /api/permissions/?org_type=department&org=7': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/statutes/?department=5': () => ({
        status: 200,
        body: { versions: [], publication: { is_public: false }, can_manage: true },
      }),
    })
    render(
      <MemoryRouter initialEntries={['/einstellungen/untereinheiten']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    // Alte Adresse unter Einstellungen führt zum eigenen Menüpunkt „Züge“ (Ralf 2026-10-30)
    expect(await screen.findByRole('heading', { level: 1, name: 'Züge' })).toBeInTheDocument()
    const nav = within(screen.getByRole('navigation', { name: 'Module' }))
    expect(nav.getByRole('link', { name: 'Züge' })).toHaveAttribute('href', '/untereinheiten')
    expect(screen.queryByRole('heading', { name: 'Einstellungen' })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: '1. Zug bearbeiten' }))
    expect(await screen.findByText('Rollen in diesem Zug')).toBeInTheDocument()
    expect(screen.getByText('Zug anlegen')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/Abteilung/)
  })
})

describe('Name des Dachverbands', () => {
  it('bildet Artikel und Fälle des Namens', () => {
    const bsv = buildFederationTerms('BSV')
    expect(fillTerms('an {dv_akk} melden · {dv_Vom} · Mitglieder {dv_gen}', bsv)).toBe(
      'an den BSV melden · Vom BSV · Mitglieder des BSV',
    )
    expect(buildFederationTerms('Bruderschaft', 'f').dv_im).toBe('in der Bruderschaft')
    expect(buildFederationTerms().dv_akk).toBe('den Dachverband')
    expect(fillTerms('{dv_im}', buildTerms('Zug', 'Züge', 'm'))).toBe('im Dachverband')
  })
})
