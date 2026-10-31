// Kontoauszug: Vorschlag übernehmen.
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
const F = '/api/orgs/7/finance'
const org = testOrg({
  modules: ['members', 'finance'],
  permissions: ['finance.view', 'finance.edit'],
})

const statement = {
  id: 3,
  account: 1,
  account_name: 'Girokonto',
  file_name: 'auszug.xml',
  reference: '2026-03',
  date_from: '2026-03-01',
  date_to: '2026-03-31',
  opening_balance: '0.00',
  closing_balance: '60.00',
  line_count: 1,
  duplicate_count: 0,
  open_count: 1,
  balance: { bank: '60.00', book: '0.00', difference: '60.00', ok: false },
  created_at: '2026-04-01T08:00:00Z',
}

const line = {
  id: 11,
  statement: 3,
  account: 1,
  date: '2026-03-03',
  amount: '60.00',
  credit: true,
  name: 'Erika Muster',
  iban: 'DE02120300000000202051',
  purpose: 'Beitrag R2026-0007',
  return_code: '',
  batch_count: 1,
  details: [],
  status: 'open',
  status_label: 'offen',
  suggestion: 'invoice',
  suggestion_label: 'Zahlung zu Rechnung',
  suggestion_sure: true,
  suggested: {
    invoice: { id: 5, number: 'R2026-0007', recipient: 'Erika Muster', outstanding: '60.00' },
  },
  booking: null,
  booking_number: null,
}

describe('Kontoauszug', () => {
  it('zeigt den Vorschlag und übernimmt ihn', async () => {
    let assigned: unknown = null
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${F}/bank-statements/?page_size=50`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [statement] },
      }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [] }),
      [`GET ${F}/bank-lines/?page_size=1000&auszug=3&status=open`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: assigned ? [] : [line] },
      }),
      [`POST ${F}/bank-lines/11/assign/`]: (init) => {
        assigned = JSON.parse(String(init?.body))
        return { status: 200, body: { ...line, status: 'done', booking_number: '2026-0012' } }
      },
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/finanzen/kontoauszuege']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByText(/Zahlung zu R2026-0007/)).toBeInTheDocument()
    expect(screen.getByText(/Kassenbuch 0,00/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Übernehmen' }))
    await waitFor(() => expect(assigned).toEqual({ action: 'suggestion' }))
    expect(await screen.findByText('Alles erledigt.')).toBeInTheDocument()
  })
})
