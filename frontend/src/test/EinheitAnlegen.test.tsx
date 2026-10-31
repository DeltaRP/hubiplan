import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { PlatformOrgsPage } from '../pages/platform/PlatformPages.tsx'
import { fakeApi, testUser } from './fakeApi.ts'

const session = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})

const bund = {
  id: 7,
  type: 'federation',
  type_label: 'Dachverband',
  keeps_members: false,
  can_switch_members: false,
  federation: null,
  federation_name: null,
  name: 'Testbund',
  postal_code: '12345',
  city: 'Musterstadt',
  federation_member_access: 'none',
  enabled_modules: [],
  is_active: true,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <OrgProvider>
          <PlatformOrgsPage />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Einheit anlegen auf der Plattform', () => {
  it('ein Knopf, Schalter statt Art, Bezeichnung folgt dem Schalter', async () => {
    const calls = fakeApi({
      'GET /_allauth/browser/v1/auth/session': session,
      'GET /api/platform/orgs/': () => ({ status: 200, body: [bund] }),
      'POST /api/platform/orgs/': () => ({ status: 201, body: { ...bund, id: 8 } }),
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Einheit anlegen' }))
    expect(screen.queryByText(/Übergeordnete Einheit anlegen/)).toBeNull()

    const keeps = screen.getByRole('checkbox', { name: /Führt eigene Mitglieder/ })
    expect(keeps).toBeChecked()
    expect(screen.getByRole('heading', { name: 'Verein anlegen' })).toBeInTheDocument()

    await user.click(keeps)
    expect(screen.getByRole('heading', { name: 'Dachverband anlegen' })).toBeInTheDocument()
    expect(screen.getByText(/Zugriff auf Mitgliedsdaten/)).toBeInTheDocument()

    // Unter einer übergeordneten Einheit immer mit eigenen Mitgliedern
    await user.selectOptions(screen.getByLabelText('Übergeordnete Einheit'), '7')
    expect(keeps).toBeChecked()
    expect(keeps).toBeDisabled()

    await user.type(screen.getByLabelText(/Vollständiger Name/), 'Neuer Verein')
    await user.type(screen.getByLabelText(/Gründungsjahr/), '2001')
    await user.type(screen.getByLabelText(/Straße und Hausnummer/), 'Weg 2')
    await user.type(screen.getByLabelText(/^PLZ/), '54321')
    await user.type(screen.getByLabelText(/^Ort/), 'Neustadt')
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    await waitFor(() => expect(calls.some((c) => c.key === 'POST /api/platform/orgs/')).toBe(true))
    const post = calls.find((c) => c.key === 'POST /api/platform/orgs/')
    const body = JSON.parse(String(post?.init?.body))
    expect(body.federation).toBe(7)
    expect(body.type).toBeUndefined()
    expect(body.label).toBe('Verein')
  })
})
