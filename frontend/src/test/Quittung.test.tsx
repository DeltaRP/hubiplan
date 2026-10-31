// Digitale Quittung: Unterschrift im Vollbild, Abschluss mit Bestätigung.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const Q = '/api/orgs/7/finance/cash-receipts'
const SHAPE = { w: 1000, h: 333, s: [[10, 100, 300, 40, 600, 160]] }

const org = testOrg({
  modules: ['members', 'finance'],
  permissions: ['finance.view', 'finance.edit'],
})

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    direction: 'out',
    direction_label: 'Verein zahlt Geld aus',
    status: 'draft',
    status_label: 'Entwurf',
    counterparty_name: 'Max Muster',
    counterparty_address: '',
    membership: null,
    email: '',
    amount: '120.50',
    purpose: 'Auslagen',
    vat_rate: null,
    account: 1,
    account_name: 'Barkasse',
    category: 2,
    category_name: 'Auslagen',
    project: null,
    invoice: null,
    invoice_number: null,
    treasurer_signature: SHAPE,
    treasurer_name: 'Karla',
    treasurer_signed_at: '2026-10-30T10:00:00Z',
    counterparty_signature: null,
    counterparty_signed_at: null,
    no_signature_reason: '',
    confirmation_text: 'Ich habe 120,50 € von Verein A erhalten. Zweck: Auslagen',
    missing: ['Unterschrift des Empfängers'],
    has_stored_signature: false,
    number: '',
    receipt_date: null,
    booking: null,
    booking_number: null,
    finalized_at: null,
    pdf_sha256: '',
    cancel_reason: '',
    cancelled_at: null,
    cancel_number: null,
    sent_at: null,
    source: 'Browser',
    created_at: '2026-10-30T10:00:00Z',
    ...overrides,
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

beforeEach(() => {
  // jsdom kann nicht zeichnen; die Linien zählen trotzdem
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

describe('Quittung', () => {
  it('Gegenseite unterschreibt im Vollbild, dann abschließen', async () => {
    let signed: unknown = null
    let finalized: RequestInit | undefined
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${Q}/5/`]: () => ({ status: 200, body: receipt() }),
      [`PUT ${Q}/5/signatures/counterparty/`]: (init) => {
        signed = JSON.parse(String(init?.body))
        return {
          status: 200,
          body: receipt({ counterparty_signature: SHAPE, missing: [] }),
        }
      },
      [`POST ${Q}/5/finalize/`]: (init) => {
        finalized = init
        return {
          status: 200,
          body: receipt({
            status: 'final',
            status_label: 'abgeschlossen',
            counterparty_signature: SHAPE,
            missing: [],
            number: '2026-0007',
            receipt_date: '2026-10-30',
          }),
        }
      },
    })
    const user = userEvent.setup()
    renderApp('/finanzen/quittungen/5')
    const box = await screen.findByRole('button', { name: 'Max Muster unterschreiben lassen' })
    await user.click(box)
    const dialog = screen.getByRole('dialog', { name: /Betrag erhalten: Max Muster/ })
    expect(within(dialog).getByText(/Ich habe 120,50 € von Verein A erhalten/)).toBeInTheDocument()
    const confirm = within(dialog).getByRole('button', { name: 'Bestätigen' })
    expect(confirm).toBeDisabled()
    const canvas = within(dialog).getByRole('img', { name: /Betrag erhalten/ })
    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 50, pointerId: 1 })
    fireEvent.pointerMove(canvas, { clientX: 150, clientY: 20, pointerId: 1 })
    fireEvent.pointerMove(canvas, { clientX: 300, clientY: 80, pointerId: 1 })
    fireEvent.pointerUp(canvas, { pointerId: 1 })
    await user.click(confirm)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(signed).toMatchObject({
      strokes: [
        [
          [10, 50],
          [150, 20],
          [300, 80],
        ],
      ],
    })
    // Nur Form: keine Zeit- oder Druckwerte
    expect(JSON.stringify(signed)).not.toMatch(/time|pressure/)

    const close = screen.getByRole('button', { name: 'Quittung abschließen' })
    expect(close).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /Ich bestätige, 120,50\s€ ausgezahlt/ }))
    await user.click(close)
    expect(await screen.findByRole('heading', { name: 'Quittung 2026-0007' })).toBeInTheDocument()
    expect(JSON.parse(String(finalized?.body))).toMatchObject({ confirmed: true })
    expect(new Headers(finalized?.headers).get('Idempotency-Key')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'PDF öffnen' })).toHaveAttribute('href', `${Q}/5/pdf/`)
    expect(calls.some((c) => c.key.startsWith('DELETE'))).toBe(false)
  })

  it('belegt die hinterlegte Kassierer-Unterschrift vor', async () => {
    let used: unknown = null
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${Q}/5/`]: () => ({
        status: 200,
        body: receipt({
          treasurer_signature: null,
          treasurer_name: '',
          has_stored_signature: true,
        }),
      }),
      [`PUT ${Q}/5/signatures/treasurer/`]: (init) => {
        used = JSON.parse(String(init?.body))
        return { status: 200, body: receipt() }
      },
    })
    renderApp('/finanzen/quittungen/5')
    await waitFor(() => expect(used).toEqual({ use_stored: true }))
    expect(await screen.findByRole('img', { name: 'Unterschrift Kassierer' })).toBeInTheDocument()
  })

  it('Quittungen stehen im Menü Finanzen', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${Q}/`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [receipt()] },
      }),
    })
    renderApp('/finanzen/quittungen')
    expect(await screen.findByRole('link', { name: 'Quittung ausstellen' })).toHaveAttribute(
      'href',
      '/finanzen/quittungen/neu',
    )
    expect(await screen.findByRole('link', { name: 'Entwurf' })).toHaveAttribute(
      'href',
      '/finanzen/quittungen/5',
    )
  })
})
