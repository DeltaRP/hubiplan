import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
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

const card = {
  first_name: 'Erika',
  last_name: 'Muster',
  status: 'active',
  status_label: 'Gültige Mitgliedschaft',
  member_type: 'aktiv',
  club: 'Hubertus-Schützenverein',
  federation: 'Bürger-Schützenverein',
  department_label: 'Zug',
  departments: ['Jägerzug'],
  photo_url: null,
  logo_url: null,
  theme: { primary: '#123e7a', on_primary: '#ffffff', accent: '#e0a100', on_accent: '#000000' },
  checked_at: '2026-10-24T16:00:00Z',
}

describe('Mitgliedsausweis nach dem Scan', () => {
  it('zeigt Name, Status, Verein und Zug ohne Anmeldung', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      'GET /api/public/card/abc/': () => ({ status: 200, body: card }),
    })
    renderAt('/ausweis/abc')
    expect(await screen.findByRole('heading', { name: 'Erika Muster' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Gültige Mitgliedschaft')
    expect(screen.getByText('Jägerzug')).toBeInTheDocument()
    expect(screen.getByText('Zug')).toBeInTheDocument()
  })

  it('meldet ungültige Ausweise', async () => {
    fakeApi({
      [SESSION]: loggedOut,
      'GET /api/public/card/alt/': () => ({ status: 404, body: { detail: 'Nicht gefunden.' } }),
    })
    renderAt('/ausweis/alt')
    expect(await screen.findByText(/nicht \(mehr\) gültig/)).toBeInTheDocument()
  })

  it('erklärt einen Netz- oder Serverfehler nicht zum ungültigen Ausweis', async () => {
    let fail = true
    fakeApi({
      [SESSION]: loggedOut,
      'GET /api/public/card/abc/': () =>
        fail ? { status: 503, body: { detail: 'Wartung' } } : { status: 200, body: card },
    })
    renderAt('/ausweis/abc')
    expect(await screen.findByText(/kann gerade nicht geprüft werden/)).toBeInTheDocument()
    expect(screen.queryByText(/nicht \(mehr\) gültig/)).not.toBeInTheDocument()
    fail = false
    await userEvent.setup().click(screen.getByRole('button', { name: 'Erneut prüfen' }))
    expect(await screen.findByRole('heading', { name: 'Erika Muster' })).toBeInTheDocument()
  })
})
