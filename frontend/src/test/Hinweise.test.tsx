import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { MemberPicker } from '../components/MemberPicker.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

function renderApp(path: string) {
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

describe('Hinweise statt stiller Umleitung', () => {
  it('unbekannte Adresse: „Seite nicht gefunden“', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp('/gibt-es-nicht')
    expect(await screen.findByRole('heading', { name: 'Seite nicht gefunden' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Zur Startseite' })).toBeInTheDocument()
  })

  it('fehlendes Recht: erklärt den Arbeitsbereich und setzt den Seitentitel', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ permissions: [], modules: ['members'] })],
      }),
    })
    renderApp('/mitglieder')
    expect(
      await screen.findByRole('heading', { name: 'Kein Zugriff in diesem Arbeitsbereich' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Aktuell gewählt: TV Beispielhausen/)).toBeInTheDocument()
    // Der Vereinsname im Titel kommt mit den Organisationsdaten, unter Last etwas später
    await waitFor(() => expect(document.title).toContain('TV Beispielhausen · HUBIplan'))
  })

  it('Aufnahme ohne Mitgliedsarten verweist auf die Einrichtung', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ permissions: ['members.view', 'members.edit'] })],
      }),
      'GET /api/orgs/7/member-types/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
    })
    renderApp('/mitglieder/neu')
    expect(
      await screen.findByText(/Für die Aufnahme fehlt noch eine Mitgliedsart/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Mitglieder → Einrichtung → Mitgliedsarten' }),
    ).toHaveAttribute('href', '/mitglieder/einrichtung/mitgliedsarten')
  })
})

describe('Mitgliedersuche', () => {
  it('unterscheidet zu kurz, keine Treffer und Fehler', async () => {
    let fail = true
    const search = async (term: string) => {
      if (fail) throw new Error('offline')
      return term === 'Xy' ? [] : [{ id: 1, first_name: 'Erika', last_name: 'Muster', email: '' }]
    }
    render(<MemberPicker orgId={7} value={null} onChange={() => {}} search={search} />)
    const user = userEvent.setup()
    const input = screen.getByLabelText('Mitglied (optional)')
    await user.type(input, 'X')
    expect(screen.getByRole('status')).toHaveTextContent('Mindestens 2 Zeichen eingeben.')
    await user.type(input, 'y')
    expect(await screen.findByText('Suche nicht möglich.')).toBeInTheDocument()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Erneut versuchen' }))
    expect(await screen.findByText('Keine Mitglieder gefunden.')).toBeInTheDocument()
  })
})
