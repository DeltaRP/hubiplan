import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

describe('Geburtstage auf der Startseite', () => {
  it('zeigt die nächsten Geburtstage mit Tag und Alter', async () => {
    vi.setSystemTime(new Date('2026-10-29T10:00:00'))
    const row = (member_id: number, first_name: string, date: string, age: number) => ({
      member_id,
      first_name,
      last_name: 'Beispiel',
      date,
      age,
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ modules: ['members'], permissions: ['members.view'] })],
      }),
      'GET /api/orgs/7/jubilees/?von=2026-10-29&bis=2027-01-27': () => ({
        status: 200,
        body: { von: '', bis: '', results: [] },
      }),
      'GET /api/orgs/7/birthdays/?von=2026-10-29&bis=2026-11-28': () => ({
        status: 200,
        body: {
          von: '2026-10-29',
          bis: '2026-11-28',
          results: [
            { ...row(1, 'Erika', '2026-10-29', 60), units: 'Jägerzug' },
            row(2, 'Otto', '2026-10-30', 41),
            row(3, 'Max', '2026-11-05', 50),
          ],
        },
      }),
    })
    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const list = await screen.findByRole('list', { name: 'Geburtstage' })
    const items = within(list)
      .getAllByRole('listitem')
      .map((li) => li.textContent)
    expect(items).toEqual([
      'Erika Beispiel (Jägerzug)heute·60 Jahre',
      'Otto Beispielmorgen·41 Jahre',
      'Max BeispielDo, 5.11.·50 Jahre',
    ])
    const lis = within(list).getAllByRole('listitem')
    expect(lis[0]).toHaveClass('tile-entry-today')
    expect(lis[1]).not.toHaveClass('tile-entry-today')
    expect(within(list).getByRole('link', { name: 'Max Beispiel' })).toHaveAttribute(
      'href',
      '/mitglieder/3',
    )
    vi.useRealTimers()
  })

  it('zeigt auf Wunsch alle Geburtstage', async () => {
    vi.setSystemTime(new Date('2026-10-29T10:00:00'))
    const results = Array.from({ length: 11 }, (_, i) => ({
      member_id: i + 1,
      first_name: `Person${i + 1}`,
      last_name: 'Beispiel',
      date: '2026-11-05',
      age: 30 + i,
    }))
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ modules: ['members'], permissions: ['members.view'] })],
      }),
      'GET /api/orgs/7/jubilees/?von=2026-10-29&bis=2027-01-27': () => ({
        status: 200,
        body: { von: '', bis: '', results: [] },
      }),
      'GET /api/orgs/7/birthdays/?von=2026-10-29&bis=2026-11-28': () => ({
        status: 200,
        body: { von: '2026-10-29', bis: '2026-11-28', results },
      }),
    })
    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const list = await screen.findByRole('list', { name: 'Geburtstage' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(8)
    expect(screen.getByText(/und 3 weitere in den nächsten 30 Tagen/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'alle zeigen' }))
    expect(within(list).getAllByRole('listitem')).toHaveLength(11)
    await userEvent.click(screen.getByRole('button', { name: 'Weniger zeigen' }))
    expect(within(list).getAllByRole('listitem')).toHaveLength(8)
    vi.useRealTimers()
  })
})
