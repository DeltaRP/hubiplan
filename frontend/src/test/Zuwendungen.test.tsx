// Zuwendungsbestätigungen: nur bei eingetragenen Vereinen, Sammelbestätigung ausstellen.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import type { OrgSummary } from '../api/orgs.ts'
import { financeAccess, financeSections } from '../pages/finanzen/access.ts'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const F = '/api/orgs/7/finance'
const YEAR = new Date().getFullYear()

const base = { modules: ['members', 'finance'], permissions: ['finance.view', 'finance.edit'] }

const SETTINGS = {
  purposes: 'des Brauchtums',
  notice: 'exemption',
  notice_label: 'Freistellungsbescheid',
  tax_office: 'Neuss',
  tax_number: '122/5701/0000',
  notice_date: '2025-03-01',
  assessment_period: '2021 bis 2023',
  fees_allowed: false,
  place: 'Neuss',
  valid_until: '2030-03-01',
  problems: [],
}

function donation(id: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    date: `${YEAR}-01-1${id}`,
    kind: 'money',
    kind_label: 'Geldzuwendung',
    amount: '100.00',
    waiver: false,
    membership: null,
    donor_name: 'Max Muster',
    donor_address: '',
    goods_description: '',
    goods_origin: '',
    goods_documents: false,
    note: '',
    booking: null,
    booking_number: null,
    statement: null,
    statement_number: null,
    ...extra,
  }
}

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

describe('Zuwendungsbestätigungen', () => {
  it('erscheinen für jede Einheit mit Kasse, auch ohne Registereintrag', () => {
    const plain = financeSections(
      financeAccess(testOrg({ ...base, registered: false }) as unknown as OrgSummary),
    )
    expect(plain.map((s) => s.label)).toContain('Zuwendungsbestätigungen')
    const noFinance = financeSections(
      financeAccess(testOrg({ ...base, modules: ['members'] }) as unknown as OrgSummary),
    )
    expect(noFinance.map((s) => s.label)).not.toContain('Zuwendungsbestätigungen')
  })

  it('zwei Zuwendungen ankreuzen ergibt eine Sammelbestätigung', async () => {
    let issued: unknown = null
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ ...base, registered: true })],
      }),
      [`GET ${F}/donation-settings/`]: () => ({ status: 200, body: SETTINGS }),
      [`GET ${F}/donations/?jahr=${YEAR}`]: () => ({
        status: 200,
        body: { count: 2, next: null, previous: null, results: [donation(1), donation(2)] },
      }),
      [`POST ${F}/donation-statements/`]: (init) => {
        issued = JSON.parse(String(init?.body))
        return { status: 201, body: { id: 9, number: `ZB-${YEAR}-0001`, donor_name: 'Max Muster' } }
      },
    })
    const user = userEvent.setup()
    renderApp('/finanzen/zuwendungen')
    const boxes = await screen.findAllByRole('checkbox', { name: /Max Muster .* auswählen/ })
    await user.click(boxes[0])
    await user.click(boxes[1])
    await user.click(screen.getByRole('button', { name: 'Sammelbestätigung ausstellen' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Unterschrift durch (Name)'), 'Erika Kasse')
    await user.click(within(dialog).getByRole('button', { name: 'Ausstellen' }))
    await waitFor(() => expect(issued).toEqual({ donations: [1, 2], signer_name: 'Erika Kasse' }))
    expect(await screen.findByText(/ZB-\d{4}-0001 für Max Muster ausgestellt/)).toBeInTheDocument()
  })
})
