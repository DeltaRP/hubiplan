import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

const row = (o: Record<string, unknown>) => ({
  member_id: 1,
  last_name: 'Beispiel',
  first_name: 'Anna',
  birth_date: '1960-01-01',
  member_number: 4711,
  kind: 'club',
  organization: 'TV Beispielhausen',
  organization_short: 'TVB',
  years: 50,
  date: '2027-04-01',
  ...o,
})

// Anna hat zwei Jubiläen am selben Tag, Bernd eins
const ROWS = [
  row({}),
  row({ last_name: 'Muster', first_name: 'Bernd', member_id: 2, member_number: null, years: 25 }),
  row({ kind: 'federation', organization: 'Testbund', organization_short: 'TB' }),
]

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Jubiläen einer Person zusammengefasst', () => {
  afterEach(() => vi.useRealTimers())

  it('zeigt den Namen in der Kachel nur einmal', async () => {
    vi.setSystemTime(new Date('2027-03-01T10:00:00'))
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/jubilees/?von=2027-03-01&bis=2027-05-30': () => ({
        status: 200,
        body: { von: '2027-03-01', bis: '2027-05-30', results: ROWS },
      }),
    })
    renderAt('/')
    const anna = await screen.findAllByRole('link', { name: 'Anna Beispiel' })
    expect(anna).toHaveLength(1)
    const entry = anna[0].closest('li') as HTMLElement
    expect(entry).toHaveTextContent('50 J.·TVB·1.4.2027')
    expect(entry).toHaveTextContent('50 J.·TB·1.4.2027')
    // Anna steht vor Bernd (Reihenfolge nach dem ersten Jubiläum)
    const names = screen.getAllByRole('link', { name: /^(Anna|Bernd) / }).map((l) => l.textContent)
    expect(names).toEqual(['Anna Beispiel', 'Bernd Muster'])
  })

  it('fasst in der Jubiläenliste die Zeilen einer Person zusammen', async () => {
    vi.setSystemTime(new Date('2027-03-01T10:00:00'))
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/jubilees/?von=2027-03-01&bis=2028-02-29': () => ({
        status: 200,
        body: { von: '2027-03-01', bis: '2028-02-29', results: ROWS },
      }),
    })
    renderAt('/mitglieder/jubilaeen')
    const annaLinks = await screen.findAllByRole('link', { name: 'Beispiel, Anna' })
    expect(annaLinks).toHaveLength(1)
    const nameCell = annaLinks[0].closest('td') as HTMLElement
    expect(nameCell).toHaveAttribute('rowspan', '2')
    const rows = within(nameCell.closest('tbody') as HTMLElement).getAllByRole('row')
    expect(rows.map((r) => r.textContent)).toEqual([
      '1.4.2027Beispiel, Anna50 Jahre TVB',
      '1.4.202750 Jahre TB',
      '1.4.2027Muster, Bernd25 Jahre TVB',
    ])
    // Ralf 2026-10-30: keine Verbandsnummer in der Jubiläenliste
    expect(screen.queryByText(/Verbandsnr/)).not.toBeInTheDocument()
    expect(screen.getByText(/3 Jubiläen/)).toBeInTheDocument()
  })
})
