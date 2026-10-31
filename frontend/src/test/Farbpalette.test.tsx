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

const theme = {
  primary_color: '#1f4e2c',
  accent_color: '',
  primary_color_name: 'Grün',
  accent_color_name: '',
  extra_colors: [],
  logo_url: null,
  effective: {
    primary: '#1f4e2c',
    on_primary: '#ffffff',
    accent: '#c9a227',
    on_accent: '#1d2421',
    logo_url: null,
    inherited_from: { colors: null, logo: null },
  },
}

describe('Farbpalette (Erscheinungsbild)', () => {
  it('fügt eine weitere Farbe mit Namen hinzu', async () => {
    const org = testOrg({ permissions: ['org.edit', 'theme.edit'] })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      'GET /api/orgs/7/theme/': () => ({ status: 200, body: theme }),
      'PATCH /api/orgs/7/theme/': () => ({ status: 200, body: theme }),
    })
    render(
      <MemoryRouter initialEntries={['/einstellungen/erscheinungsbild']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    expect(await screen.findByLabelText('Name der Hauptfarbe', {}, { timeout: 5000 })).toHaveValue(
      'Grün',
    )
    await user.click(screen.getByRole('button', { name: 'Farbe hinzufügen' }))
    await user.type(screen.getByLabelText('Name der 3. Farbe'), 'Weinrot')
    await waitFor(
      () =>
        expect(
          calls.some(
            (c) =>
              c.key === 'PATCH /api/orgs/7/theme/' &&
              JSON.parse(String(c.init?.body)).extra_colors?.[0]?.name === 'Weinrot',
          ),
        ).toBe(true),
      { timeout: 3000 },
    )
    expect(screen.getByText(/Text darauf/)).toBeVisible()
  })
})
