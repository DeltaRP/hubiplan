import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/honorary-titles/'
const title = (id: number, name: string, extra = {}) => ({
  id,
  name,
  fee_mode: 'none',
  fee_amount: null,
  fee_discount_percent: null,
  fee_text: '',
  is_archived: false,
  sort_order: id,
  in_use: false,
  own: true,
  owner_name: 'Testverein',
  ...extra,
})

function setup(titles: ReturnType<typeof title>[], extra = {}) {
  return fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    [`GET ${base}`]: () => ({ status: 200, body: titles }),
    ...extra,
  })
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/mitglieder/einrichtung/ehrungen']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Ehrungen einrichten', () => {
  it('zeigt Titel mit Beitragsanpassung und legt einen neuen an', async () => {
    const calls = setup(
      [title(1, 'Ehrenmitglied', { fee_mode: 'free', fee_text: 'beitragsfrei' })],
      {
        [`POST ${base}`]: () => ({
          status: 201,
          body: title(2, 'Ehrenmajor', { fee_mode: 'amount', fee_amount: '20.00' }),
        }),
      },
    )
    renderPage()
    const user = userEvent.setup()
    expect((await screen.findAllByText('beitragsfrei')).length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: 'Neue Ehrung' }))
    const form = screen.getByRole('form', { name: 'Ehrung bearbeiten' })
    await user.type(within(form).getByLabelText('Bezeichnung'), 'Ehrenmajor')
    await user.selectOptions(within(form).getByLabelText('Beitrag'), 'amount')
    await user.type(within(form).getByLabelText('Jahresbeitrag in €'), '20')
    await user.click(within(form).getByRole('button', { name: 'Anlegen' }))
    const post = calls.find((c) => c.key === `POST ${base}`)
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({
      name: 'Ehrenmajor',
      fee_mode: 'amount',
      fee_amount: '20',
    })
  })

  it('archiviert einen verliehenen Titel nach Rückfrage', async () => {
    const calls = setup([title(1, 'Ehrenmitglied')], {
      [`GET ${base}1/usage/`]: () => ({
        status: 200,
        body: { deletable: false, reasons: ['3 Mal verliehen'], is_archived: false },
      }),
      [`POST ${base}1/archive/`]: () => ({
        status: 200,
        body: title(1, 'Ehrenmitglied', { is_archived: true }),
      }),
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Ehrenmitglied löschen' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Archivieren' }))
    expect(await screen.findByText('„Ehrenmitglied“ wurde archiviert.')).toBeInTheDocument()
    expect(calls.some((c) => c.key === `POST ${base}1/archive/`)).toBe(true)
  })
})
