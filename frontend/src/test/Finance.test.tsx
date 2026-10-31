import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const F = '/api/orgs/7/finance'

function Where() {
  const { search } = useLocation()
  return <output data-testid="adresse">{search}</output>
}

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Where />
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const kassierer = testOrg({
  modules: ['members', 'finance'],
  permissions: ['finance.view', 'finance.edit'],
})
const settings = {
  tax_areas_enabled: false,
  tax_areas: [],
  can_edit: true,
  fiscal_start_month: 7,
  fiscal_start_day: 1,
  current_year: 2025,
  current_label: '2025/26',
  years: [{ year: 2025, label: '2025/26' }],
}
const giro = {
  id: 1,
  name: 'Girokonto',
  kind: 'bank',
  kind_label: 'Bankkonto',
  iban: '',
  bic: '',
  bank_name: '',
  opening_balance: '100.00',
  opening_date: '2025-07-01',
  is_active: true,
  position: 0,
  balance: '160.00',
  booking_count: 1,
}
const beitraege = {
  id: 3,
  name: 'Beiträge',
  kind: 'income',
  kind_label: 'Einnahmen',
  tax_area: '',
  tax_area_label: '',
  is_active: true,
  booking_count: 1,
}
const booking = {
  id: 9,
  year: 2025,
  number: 1,
  display_number: '2025/26-0001',
  date: '2025-08-01',
  kind: 'income',
  kind_label: 'Einnahme',
  amount: '60.00',
  account: 1,
  account_name: 'Girokonto',
  to_account: null,
  to_account_name: null,
  category: 3,
  category_name: 'Beiträge',
  tax_area: '',
  text: 'Beitrag Muster',
  reference: '',
  counterparty: '',
  membership: null,
  member_name: null,
  department: null,
  department_name: null,
  receipts: [],
  created_at: '2025-08-01T10:00:00Z',
}

describe('Kasse', () => {
  it('zeigt die Übersicht des Geschäftsjahres', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/overview/?jahr=2025`]: () => ({
        status: 200,
        body: {
          year: 2025,
          label: '2025/26',
          start_date: '2025-07-01',
          end_date: '2026-06-30',
          years: settings.years,
          tax_areas_enabled: false,
          accounts: [
            {
              id: 1,
              name: 'Girokonto',
              kind: 'bank',
              kind_label: 'Bankkonto',
              is_active: true,
              start: '100.00',
              income: '60.00',
              expense: '0.00',
              transfer_in: '0.00',
              transfer_out: '0.00',
              end: '160.00',
            },
          ],
          categories: [{ id: 3, name: 'Beiträge', tax_area: '', income: '60.00', expense: '0.00' }],
          tax_areas: [],
          totals: {
            income: '60.00',
            expense: '0.00',
            result: '60.00',
            start: '100.00',
            end: '160.00',
          },
          booking_count: 1,
        },
      }),
    })
    renderApp('/finanzen')
    expect(await screen.findByRole('heading', { name: 'Einnahmen 2025/26' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Girokonto' })).toBeInTheDocument()
    expect(screen.getAllByText(/160,00/).length).toBeGreaterThan(0)
    // Arbeitsschritte in sichtbarer Reihenfolge
    const steps = screen.getByRole('navigation', { name: 'Arbeitsschritte' })
    expect(within(steps).getByRole('link', { name: /Buchen/ })).toHaveAttribute(
      'href',
      '/finanzen/kassenbuch',
    )
  })

  it('erfasst eine Einnahme mit Komma-Betrag', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [booking] },
      }),
      [`POST ${F}/bookings/`]: () => ({ status: 201, body: { ...booking, id: 10, number: 2 } }),
    })
    renderApp('/finanzen/kassenbuch')
    expect(await screen.findByRole('button', { name: '2025/26-0001' })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Einnahme' }))
    const form = screen.getByRole('heading', { name: 'Neue Einnahme' }).closest('form')!
    const f = within(form)
    await user.type(f.getByLabelText('Betrag (€)'), '1.234,50')
    await user.selectOptions(f.getByLabelText('Kategorie'), '3')
    await user.type(f.getByLabelText('Buchungstext'), 'Spende')
    await user.click(f.getByRole('button', { name: 'Buchen' }))
    await screen.findByRole('heading', { name: /Einnahme 2025\/26-0001/ })
    const post = calls.find((c) => c.key === `POST ${F}/bookings/`)!
    const body = JSON.parse(String(post.init?.body))
    expect(body).toMatchObject({
      kind: 'income',
      amount: '1234.50',
      account: 1,
      category: 3,
      text: 'Spende',
    })
    expect(body.number).toBeUndefined()
  })

  it('erfasst eine Ausgabe an ein Geschäft mit Vorschlag', async () => {
    const material = { ...beitraege, id: 4, name: 'Material', kind: 'expense' }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege, material] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/counterparties/`]: () => ({
        status: 200,
        body: [{ name: 'Getränke Müller', count: 3 }],
      }),
      [`GET ${F}/bookings/counterparties/?art=expense`]: () => ({
        status: 200,
        body: [{ name: 'Getränke Müller', count: 3 }],
      }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [booking] },
      }),
      [`POST ${F}/bookings/`]: () => ({
        status: 201,
        body: { ...booking, id: 10, number: 2, kind: 'expense', counterparty: 'Getränke Müller' },
      }),
    })
    renderApp('/finanzen/kassenbuch')
    expect(await screen.findByRole('button', { name: '2025/26-0001' })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Ausgabe' }))
    const form = screen.getByRole('heading', { name: 'Neue Ausgabe' }).closest('form')!
    const f = within(form)
    const partner = f.getByLabelText(/Empfänger/)
    await waitFor(() =>
      expect(
        form.querySelector('datalist#booking-partner-suggestions option[value="Getränke Müller"]'),
      ).not.toBeNull(),
    )
    // Mitglied/Abteilung sind bei Ausgaben eingeklappt
    expect(form.querySelector('details.booking-assign')?.hasAttribute('open')).toBe(false)
    await user.type(f.getByLabelText('Betrag (€)'), '45,90')
    await user.type(partner, 'Getränke Müller')
    await user.selectOptions(f.getByLabelText('Kategorie'), '4')
    await user.type(f.getByLabelText('Buchungstext'), 'Wasser und Saft')
    await user.click(f.getByRole('button', { name: 'Buchen' }))
    await screen.findByRole('heading', { name: /Ausgabe 2025\/26-0001/ })
    const post = calls.find((c) => c.key === `POST ${F}/bookings/`)!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({
      kind: 'expense',
      amount: '45.90',
      category: 4,
      counterparty: 'Getränke Müller',
      membership: null,
    })
  })

  it('liest eine E-Rechnung ein und hängt sie nach dem Buchen als Beleg an', async () => {
    const material = { ...beitraege, id: 4, name: 'Material', kind: 'expense' }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege, material] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/counterparties/?art=expense`]: () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [booking] },
      }),
      [`POST ${F}/einvoice/`]: () => ({
        status: 200,
        body: {
          einvoice: { number: 'RE-0815', seller: 'Musterbrauerei GmbH', payable: '595.00' },
          suggestion: {
            kind: 'expense',
            date: '2025-07-14',
            amount: '595.00',
            counterparty: 'Musterbrauerei GmbH',
            reference: 'RE-0815',
            text: 'Rechnung RE-0815 Musterbrauerei GmbH',
          },
        },
      }),
      [`POST ${F}/bookings/`]: () => ({
        status: 201,
        body: { ...booking, id: 10, number: 2, kind: 'expense' },
      }),
      [`POST ${F}/bookings/10/receipts/`]: () => ({
        status: 201,
        body: { id: 1, name: 'rechnung.xml', content_type: 'application/xml', size: 10 },
      }),
    })
    renderApp('/finanzen/kassenbuch')
    expect(await screen.findByRole('button', { name: '2025/26-0001' })).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Ausgabe' }))
    const form = screen.getByRole('heading', { name: 'Neue Ausgabe' }).closest('form')!
    const f = within(form)
    const file = new File(['<Invoice/>'], 'rechnung.xml', { type: 'application/xml' })
    await user.upload(f.getByLabelText(/E-Rechnung einlesen/), file)
    expect(await f.findByText(/E-Rechnung RE-0815 von Musterbrauerei GmbH/)).toBeInTheDocument()
    expect(f.getByLabelText('Betrag (€)')).toHaveValue('595,00')
    await user.selectOptions(f.getByLabelText('Kategorie'), '4')
    await user.click(f.getByRole('button', { name: 'Buchen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${F}/bookings/10/receipts/`)).toBe(true),
    )
    const post = calls.find((c) => c.key === `POST ${F}/bookings/`)!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({
      kind: 'expense',
      date: '2025-07-14',
      amount: '595.00',
      counterparty: 'Musterbrauerei GmbH',
      reference: 'RE-0815',
      category: 4,
    })
  })

  it('blättert im Kassenbuch vor und zurück (über 100 Buchungen)', async () => {
    const page = (n: number) => () => ({
      status: 200,
      body: {
        count: 201,
        next: null,
        previous: null,
        results: [{ ...booking, id: n, display_number: `Seite-${n}` }],
      },
    })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: page(1),
      [`GET ${F}/bookings/?jahr=2025&page=2`]: page(2),
      [`GET ${F}/bookings/?jahr=2025&page=3`]: page(3),
    })
    renderApp('/finanzen/kassenbuch')
    const user = userEvent.setup()
    expect(await screen.findByRole('button', { name: 'Seite-1' })).toBeInTheDocument()
    expect(screen.getByText('Seite 1 von 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(await screen.findByRole('button', { name: 'Seite-2' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Weiter' }))
    expect(await screen.findByRole('button', { name: 'Seite-3' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Weiter' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Zurück' }))
    expect(await screen.findByRole('button', { name: 'Seite-2' })).toBeInTheDocument()
    expect(calls.some((c) => c.key === `GET ${F}/bookings/?jahr=2025&page=3`)).toBe(true)
  })

  it('öffnet Buchungen über die Adresse und schließt sie mit Zurück', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [booking] },
      }),
      [`GET ${F}/bookings/42/`]: () => ({
        status: 200,
        body: { ...booking, id: 42, display_number: '2024/25-0042' },
      }),
    })
    // Direktlink auf eine Buchung, die nicht auf der ersten Seite steht
    renderApp('/finanzen/kassenbuch?buchung=42')
    expect(
      await screen.findByRole('heading', { name: 'Einnahme 2024/25-0042' }),
    ).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
    await waitFor(() => expect(screen.getByTestId('adresse').textContent).toBe(''))
    // Aus der Liste öffnen: steht in der Adresse
    await user.click(await screen.findByRole('button', { name: '2025/26-0001' }))
    expect(
      await screen.findByRole('heading', { name: 'Einnahme 2025/26-0001' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('adresse').textContent).toBe('?buchung=9')
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: 'Einnahme 2025/26-0001' }),
      ).not.toBeInTheDocument(),
    )
    expect(screen.getByTestId('adresse').textContent).toBe('')
  })

  it('ist für Kassenprüfer nur lesbar', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ modules: ['finance'], permissions: ['finance.view'] })],
      }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: { ...settings, can_edit: false } }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [booking] },
      }),
    })
    renderApp('/finanzen/kassenbuch')
    expect(await screen.findByRole('button', { name: '2025/26-0001' })).toBeInTheDocument()
    expect(screen.getByText('nur lesen')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Einnahme' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Neu nummerieren' })).not.toBeInTheDocument()
  })

  it('lässt den Verein die steuerlichen Bereiche selbst einschalten', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      [`PATCH ${F}/settings/`]: () => ({
        status: 200,
        body: {
          ...settings,
          tax_areas_enabled: true,
          tax_areas: [{ value: 'ideal', label: 'ideeller Bereich' }],
        },
      }),
    })
    renderApp('/finanzen/einstellungen/kategorien')
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText(/steuerlichen Bereichen zuordnen/))
    expect(
      await screen.findByRole('columnheader', { name: 'steuerlicher Bereich' }),
    ).toBeInTheDocument()
    const patch = calls.find((c) => c.key === `PATCH ${F}/settings/`)!
    expect(JSON.parse(String(patch.init?.body))).toEqual({ tax_areas_enabled: true })
  })

  it('storniert eine festgeschriebene Buchung statt sie zu löschen', async () => {
    const fixed = {
      ...booking,
      id: 42,
      display_number: '2025/26-0042',
      fixed: true,
      deletable: false,
      cancels: null,
      cancel_reason: '',
      cancelled_by: null,
    }
    const cancelled = {
      ...fixed,
      cancelled_by: { id: 50, number: '2025/26-0050', reason: 'doppelt', date: '2025-09-01' },
    }
    let done = false
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      [`GET ${F}/bookings/?jahr=2025&page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [done ? cancelled : fixed] },
      }),
      [`GET ${F}/bookings/42/`]: () => ({ status: 200, body: fixed }),
      [`POST ${F}/bookings/42/storno/`]: () => {
        done = true
        return { status: 201, body: cancelled }
      },
    })
    renderApp('/finanzen/kassenbuch?buchung=42')
    expect(await screen.findByText(/ist festgeschrieben/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Löschen' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Betrag (€)')).toBeDisabled()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Stornieren' }))
    const dialog = await screen.findByRole('dialog', {
      name: 'Buchung 2025/26-0042 stornieren?',
    })
    await user.type(within(dialog).getByRole('textbox'), 'doppelt')
    await user.click(within(dialog).getByRole('button', { name: 'Stornieren' }))
    expect(await screen.findByText(/Storniert durch Buchung 2025\/26-0050/)).toBeInTheDocument()
    const post = calls.find((c) => c.key === `POST ${F}/bookings/42/storno/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({ reason: 'doppelt' })
  })

  it('schließt ein Geschäftsjahr ab', async () => {
    const years = (closed: boolean) => ({
      years: [
        {
          year: 2025,
          label: '2025/26',
          end_date: '2026-06-30',
          running: true,
          closed: false,
          closed_at: null,
          closed_by: null,
        },
        {
          year: 2024,
          label: '2024/25',
          end_date: '2025-06-30',
          running: false,
          closed,
          closed_at: closed ? '2025-08-01T10:00:00Z' : null,
          closed_by: closed ? 'Karla' : null,
        },
      ],
      can_close: true,
      can_reopen: false,
    })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/closings/`]: () => ({ status: 200, body: years(false) }),
      [`POST ${F}/closings/`]: () => ({ status: 201, body: years(true) }),
    })
    renderApp('/finanzen/abschluss/jahresabschluss')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Abschließen' }))
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Geschäftsjahr 2024/25 abschließen?',
    })
    await user.click(within(dialog).getByRole('button', { name: 'Abschließen' }))
    expect(await screen.findByText('Geschäftsjahr 2024/25 ist abgeschlossen.')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Kassenbericht' })[1]).toHaveAttribute(
      'href',
      `${F}/report/?jahr=2024`,
    )
    const post = calls.find((c) => c.key === `POST ${F}/closings/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({ year: 2024 })
  })

  it('hebt einen Abschluss nur mit Grund auf und zeigt den alten Stand', async () => {
    const year = (closed: boolean) => ({
      year: 2024,
      label: '2024',
      end_date: '2024-12-31',
      running: false,
      closed,
      closed_at: closed ? '2025-02-01T10:00:00Z' : null,
      closed_by: closed ? 'Karla' : null,
      reopened: closed
        ? []
        : [
            {
              closed_at: '2025-02-01T10:00:00Z',
              closed_by: 'Karla',
              reopened_at: '2025-03-01T10:00:00Z',
              reopened_by: 'Vera Vorstand',
              reason: 'Rechnung fehlte',
            },
          ],
      changes: [],
    })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/closings/`]: () => ({
        status: 200,
        body: { years: [year(true)], can_close: true, can_reopen: true },
      }),
      [`DELETE ${F}/closings/?jahr=2024`]: () => ({
        status: 200,
        body: { years: [year(false)], can_close: true, can_reopen: true },
      }),
    })
    renderApp('/finanzen/abschluss/jahresabschluss')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Abschluss aufheben' }))
    const dialog = await screen.findByRole('dialog', { name: 'Abschluss 2024 aufheben?' })
    await user.type(within(dialog).getByRole('textbox'), 'Rechnung fehlte')
    await user.click(within(dialog).getByRole('button', { name: 'Aufheben' }))
    expect(await screen.findByText('Abschluss 2024 aufgehoben.')).toBeInTheDocument()
    expect(screen.getByText(/von Vera Vorstand: Rechnung fehlte/)).toBeInTheDocument()
    const del = calls.find((c) => c.key === `DELETE ${F}/closings/?jahr=2024`)!
    expect(JSON.parse(String(del.init?.body))).toEqual({ reason: 'Rechnung fehlte' })
  })

  it('bereinigt ein Jahr nach Ablauf der Aufbewahrungsfrist', async () => {
    let purged = false
    const year = () => ({
      year: 2014,
      label: '2014',
      end_date: '2014-12-31',
      running: false,
      closed: true,
      closed_at: '2015-02-01T10:00:00Z',
      closed_by: 'Karla',
      reopened: [],
      changes: [],
      retention: {
        documents_from: '2024-01-01',
        records_from: '2026-01-01',
        documents_purged_at: purged ? '2026-10-31T10:00:00Z' : null,
        records_purged_at: purged ? '2026-10-31T10:00:00Z' : null,
        purged_by: purged ? 'Vera Vorstand' : '',
        documents_due: !purged,
        records_due: !purged,
      },
    })
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/closings/`]: () => ({
        status: 200,
        body: { years: [year()], can_close: true, can_reopen: true },
      }),
      [`POST ${F}/closings/aufbewahrung/`]: () => {
        purged = true
        return {
          status: 200,
          body: { done: 'Belege gelöscht, Bücher anonymisiert', counts: { Buchungen: 3 } },
        }
      },
    })
    renderApp('/finanzen/abschluss/jahresabschluss')
    const user = userEvent.setup()
    expect(await screen.findByText(/Aufbewahrungsfrist abgelaufen/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Abschluss aufheben' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Daten bereinigen' }))
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Geschäftsjahr 2014 bereinigen?',
    })
    await user.click(within(dialog).getByRole('button', { name: 'Endgültig bereinigen' }))
    expect(
      await screen.findByText('Geschäftsjahr 2014: Belege gelöscht, Bücher anonymisiert.'),
    ).toBeInTheDocument()
    expect(await screen.findByText(/Bücher anonymisiert am/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Abschluss aufheben' })).not.toBeInTheDocument()
    const post = calls.find((c) => c.key === `POST ${F}/closings/aufbewahrung/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({ year: 2014 })
  })
})

describe('Kategorien löschen und umbenennen', () => {
  const cat = (id: number, name: string, active = true, count = 0) => ({
    ...beitraege,
    id,
    name,
    is_active: active,
    booking_count: count,
  })
  const base = (extra = {}) => ({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
    [`GET ${F}/settings/`]: () => ({ status: 200, body: settings }),
    ...extra,
  })

  it('archiviert eine gebuchte Kategorie nach Hinweis', async () => {
    const calls = fakeApi(
      base({
        [`GET ${F}/categories/`]: () => ({ status: 200, body: [cat(3, 'Beiträge', true, 4)] }),
        [`GET ${F}/categories/3/usage/`]: () => ({
          status: 200,
          body: {
            deletable: false,
            reasons: ['in 4 Buchungen verwendet (Geschäftsjahr 2025/26)'],
            is_archived: false,
          },
        }),
        [`POST ${F}/categories/3/archive/`]: () => ({
          status: 200,
          body: cat(3, 'Beiträge', false, 4),
        }),
      }),
    )
    renderApp('/finanzen/einstellungen/kategorien')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Beiträge löschen' }))
    expect(
      await screen.findByText('in 4 Buchungen verwendet (Geschäftsjahr 2025/26)'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Archivieren' }))
    expect(await screen.findByText('„Beiträge“ wurde archiviert.')).toBeInTheDocument()
    expect(calls.some((c) => c.key === `POST ${F}/categories/3/archive/`)).toBe(true)
  })

  it('löscht eine unbenutzte, stellt eine archivierte wieder her und benennt um', async () => {
    const calls = fakeApi(
      base({
        [`GET ${F}/categories/`]: () => ({
          status: 200,
          body: [cat(3, 'Beiträge', true, 4), cat(5, 'Tombola'), cat(6, 'Alt', false, 2)],
        }),
        [`GET ${F}/categories/5/usage/`]: () => ({
          status: 200,
          body: { deletable: true, reasons: [], is_archived: false },
        }),
        [`DELETE ${F}/categories/5/`]: () => ({ status: 204 }),
        [`POST ${F}/categories/6/restore/`]: () => ({ status: 200, body: cat(6, 'Alt') }),
        [`PATCH ${F}/categories/3/`]: () => ({ status: 200, body: cat(3, 'Mitgliedsbeiträge') }),
      }),
    )
    renderApp('/finanzen/einstellungen/kategorien')
    const user = userEvent.setup()
    expect(await screen.findByText('Archivierte Kategorien')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Tombola löschen' }))
    expect(await screen.findByText(/wird nirgends verwendet/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Löschen' }))
    expect(await screen.findByText('„Tombola“ wurde gelöscht.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Alt wiederherstellen' }))
    expect(await screen.findByText('„Alt“ ist wieder verfügbar.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Beiträge umbenennen' }))
    const input = screen.getByRole('textbox', { name: 'Neuer Name für Beiträge' })
    await user.clear(input)
    await user.type(input, 'Mitgliedsbeiträge')
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
    expect(
      await screen.findByText('„Beiträge“ heißt jetzt „Mitgliedsbeiträge“.'),
    ).toBeInTheDocument()
    const patch = calls.find((c) => c.key === `PATCH ${F}/categories/3/`)
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ name: 'Mitgliedsbeiträge' })
    expect(calls.some((c) => c.key === `DELETE ${F}/categories/5/`)).toBe(true)
  })
})

describe('Kassenzählung', () => {
  it('erstellt einen Kassenbericht für ein Fest mit Aufteilung', async () => {
    const org = testOrg({
      modules: ['members', 'finance'],
      permissions: ['finance.view', 'finance.edit'],
      cash_counts_enabled: true,
    })
    const kasse = { ...giro, id: 2, name: 'Barkasse', kind: 'cash', kind_label: 'Barkasse' }
    const saved = {
      id: 5,
      kind: 'event',
      kind_label: 'Kassenbericht',
      account: 2,
      account_name: 'Barkasse',
      date: '2025-07-12',
      title: 'Getränkezelt',
      project: null,
      denominations: { '10000': 3, '5000': 1 },
      counted: '350.00',
      expected: '0.00',
      difference: '0.00',
      opening: '100.00',
      expenses: '0.00',
      withdrawals: '0.00',
      takings: '250.00',
      lines: [{ category: 3, name: 'Beiträge', amount: '250.00' }],
      note: '',
      counted_by: 'Karla',
      witness: '',
      bookings: [{ id: 40, number: '2025/26-0040' }],
      pdf_sha256: 'x',
      created_at: '2025-07-12T22:00:00Z',
    }
    let done = false
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${F}/cash-counts/?page=1`]: () => ({
        status: 200,
        body: { count: done ? 1 : 0, results: done ? [saved] : [] },
      }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro, kasse] }),
      [`GET ${F}/categories/`]: () => ({ status: 200, body: [beitraege] }),
      [`POST ${F}/cash-counts/`]: () => {
        done = true
        return { status: 201, body: saved }
      },
    })
    renderApp('/finanzen/kassenzaehlung')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Kassenbericht Fest' }))
    await user.type(screen.getByLabelText('Fest bzw. Verkaufsstand'), 'Getränkezelt')
    await user.type(screen.getByLabelText('100 €'), '3')
    await user.type(screen.getByLabelText('50 €'), '1')
    expect(screen.getByText('Summe: 350,00 €')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/Anfangsbestand/), '100')
    expect(screen.getByText('Tageseinnahme: 250,00 €')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Kategorie'), 'Beiträge')
    await user.type(screen.getByLabelText('Betrag in €'), '250')
    await user.type(screen.getByLabelText('Gezählt von'), 'Karla')
    await user.click(screen.getByRole('button', { name: 'Speichern und buchen' }))
    expect(await screen.findByText(/gebucht als 2025\/26-0040\./)).toBeInTheDocument()
    const post = calls.find((c) => c.key === `POST ${F}/cash-counts/`)!
    const body = JSON.parse(String(post.init?.body))
    expect(body).toMatchObject({
      kind: 'event',
      account: 2,
      title: 'Getränkezelt',
      denominations: { '10000': 3, '5000': 1 },
      opening: '100',
      lines: [{ category: 3, amount: '250' }],
      counted_by: 'Karla',
    })
  })
})

describe('DATEV-Export', () => {
  it('schaltet den Export ein und speichert die Mandantendaten', async () => {
    let current = { ...settings, datev_enabled: false, datev_consultant: '', datev_client: '' }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${F}/accounts/`]: () => ({ status: 200, body: [giro] }),
      [`GET ${F}/settings/`]: () => ({ status: 200, body: current }),
      [`PATCH ${F}/settings/`]: (init) => {
        current = { ...current, ...JSON.parse(String(init?.body)) }
        return { status: 200, body: current }
      },
    })
    renderApp('/finanzen/einstellungen/konten')
    const user = userEvent.setup()
    await user.click(await screen.findByLabelText('DATEV-Export für die Steuerberatung nutzen'))
    await user.type(await screen.findByLabelText('Beraternummer'), '1234567')
    await user.tab()
    await waitFor(() => expect(current.datev_consultant).toBe('1234567'))
    const patches = calls.filter((c) => c.key === `PATCH ${F}/settings/`)
    expect(JSON.parse(String(patches[0].init?.body))).toEqual({ datev_enabled: true })
  })
})
