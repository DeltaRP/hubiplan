// Lizenzaudit 29.10.2026 Teil d (F02, Fachfrage 4).
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { RightsHint } from '../components/RightsHint.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedOut = () => ({ status: 401, body: { status: 401, data: { flows: [] } } })

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

describe('Lizenzaudit 29.10. Teil d', () => {
  it('F02: Seite „Lizenzen“ mit eigener Lizenz und Fremdlizenzen', async () => {
    fakeApi({ [SESSION]: loggedOut })
    renderAt('/lizenz')
    expect(await screen.findByRole('heading', { name: 'Lizenzen' })).toBeInTheDocument()
    expect(screen.getByText(/AGPL-3.0-or-later/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Lizenztext (englisch)' })).toHaveAttribute(
      'href',
      '/lizenzen/LICENSE.txt',
    )
    // AGPL § 13: Link zum Quellcode (ohne Fassungsdatei auf das Repository)
    expect(screen.getByRole('link', { name: 'Quellcode von HUBIplan' })).toHaveAttribute(
      'href',
      'https://github.com/hubiplan/hubiplan',
    )
    expect(
      screen.getByRole('link', { name: 'Lizenzen der enthaltenen Bibliotheken' }),
    ).toHaveAttribute('href', '/lizenzen/drittanbieter.txt')
    expect(document.title).toMatch(/Lizenzen/)
  })

  it('AGPL § 13: Link auf den Quellcode der laufenden Fassung', async () => {
    const sha = '0123456789abcdef0123456789abcdef01234567'
    fakeApi({ [SESSION]: loggedOut })
    // Die Fassungsdatei ist reiner Text, kein JSON
    const api = vi.mocked(globalThis.fetch).getMockImplementation()!
    vi.mocked(globalThis.fetch).mockImplementation(async (input, init) =>
      String(input) === '/lizenzen/fassung.txt' ? new Response(`${sha}\n`) : api(input, init),
    )
    renderAt('/lizenz')
    expect(
      await screen.findByRole('link', { name: 'Quellcode dieser Fassung (0123456)' }),
    ).toHaveAttribute('href', `https://github.com/hubiplan/hubiplan/tree/${sha}`)
  })

  it('F02: Fußzeile verlinkt „Lizenzen“', async () => {
    fakeApi({ [SESSION]: loggedOut })
    renderAt('/anmelden')
    const footer = await screen.findByRole('navigation', { name: 'Rechtliches' })
    expect(footer).toContainElement(screen.getByRole('link', { name: 'Lizenzen' }))
  })

  it('Fachfrage 4: Hinweis auf die Rechte der Urheber', () => {
    render(<RightsHint />)
    expect(screen.getByText(/Erlaubnis der Urheber/)).toBeInTheDocument()
  })
})
