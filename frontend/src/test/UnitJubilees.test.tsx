import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { unitJubileeHeading } from '../pages/members/JubileesPage.tsx'
import type { UnitJubileeRow } from '../api/fields.ts'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

describe('Jubiläen von Einheiten', () => {
  it('listet Jubiläen aus dem Gründungsjahr neben denen der Mitglieder', async () => {
    vi.setSystemTime(new Date('2027-03-01T10:00:00'))
    const unit = {
      id: 3,
      kind: 'unit',
      name: 'Jägerzug',
      short_name: 'Jäger',
      path: 'Jägerzug',
      label: 'Zug',
      label_plural: 'Züge',
      label_gender: 'm',
      label_genitive: '',
      founding_year: 1927,
      years: 100,
      year: 2027,
    }
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/jubilees/?von=2027-03-01&bis=2028-02-29': () => ({
        status: 200,
        body: { von: '2027-03-01', bis: '2028-02-29', results: [] },
      }),
      'GET /api/orgs/7/unit-jubilees/?von=2027-03-01&bis=2028-02-29': () => ({
        status: 200,
        body: { von: '2027-03-01', bis: '2028-02-29', results: [unit] },
      }),
    })
    render(
      <MemoryRouter initialEntries={['/mitglieder/jubilaeen']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: 'Jubiläum des Zugs' })).toBeTruthy()
    const table = await screen.findByRole('table', { name: 'Jubiläum des Zugs' })
    expect(within(table).getByRole('columnheader', { name: 'Zug' })).toBeTruthy()
    const cells = within(table)
      .getAllByRole('cell')
      .map((c) => c.textContent)
    expect(cells).toEqual(['2027', 'Jägerzug Zug', '100 Jahre', '1927'])
    vi.useRealTimers()
  })

  it('nennt die eigenen Bezeichnungen statt „Einheiten“', () => {
    const row = (id: number, kind: UnitJubileeRow['kind'], label: string, plural: string) =>
      ({
        id,
        kind,
        name: `E${id}`,
        short_name: '',
        path: `E${id}`,
        label,
        label_plural: plural,
        label_gender: 'm',
        label_genitive: '',
        founding_year: 1927,
        years: 100,
        year: 2027,
      }) as UnitJubileeRow
    expect(
      unitJubileeHeading([row(2, 'unit', 'Zug', 'Züge'), row(3, 'unit', 'Zug', 'Züge')]),
    ).toEqual({ title: 'Jubiläen der Züge', column: 'Zug' })
    expect(
      unitJubileeHeading([
        row(1, 'self', 'Verein', 'Vereine'),
        row(2, 'unit', 'Zug', 'Züge'),
        row(3, 'unit', 'Zug', 'Züge'),
      ]),
    ).toEqual({ title: 'Jubiläen des Vereins und der Züge', column: 'Name' })
  })
})
