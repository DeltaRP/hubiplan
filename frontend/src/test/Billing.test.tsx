import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const B = '/api/orgs/7/billing'

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

const kassierer = testOrg({
  modules: ['members', 'finance', 'billing'],
  permissions: ['billing.view', 'billing.edit', 'finance.view'],
  sepa_enabled: true,
})

const settings = {
  rhythm: 'yearly',
  due_days: 14,
  pro_rata: false,
  account: 1,
  category: 3,
  intro_text: '',
  footer_text: '',
  qr_code: true,
  vat_enabled: false,
  vat_rate: '19.00',
  tax_number: '',
  club_rate_active: null,
  club_rate_passive: null,
  club_base_amount: null,
  sepa_enabled: true,
  creditor_id: 'DE98ZZZ09999999999',
  prenotification_days: 5,
  org_type: 'club',
  clubs: [],
  rhythms: [{ value: 'yearly', label: 'jährlich' }],
  accounts: [
    { id: 1, name: 'Girokonto', kind: 'bank', has_iban: true },
    { id: 2, name: 'Barkasse', kind: 'cash', has_iban: false },
  ],
  categories: [{ id: 3, name: 'Mitgliedsbeiträge' }],
  current_year: 2025,
  years: [{ year: 2025, label: '2025' }],
  periods: { '2025': [{ index: 1, label: '2025', start: '2025-01-01', end: '2025-12-31' }] },
  department_label: 'Zug',
  department_label_plural: 'Züge',
  can_edit: true,
}

const row = {
  id: 5,
  number: 'R2025-0001',
  status: 'open',
  status_label: 'offen',
  recipient_kind: 'member',
  recipient_name: 'Erika Muster',
  recipient_email: 'erika@example.org',
  membership: 11,
  department: null,
  department_name: null,
  run: 1,
  run_label: '2025',
  date: '2025-02-01',
  due_date: '2025-02-15',
  subject: 'Mitgliedsbeitrag 2025',
  total: '60.00',
  paid: '0.00',
  outstanding: '60.00',
  sent_at: null,
  overdue: false,
  club: null,
  club_name: null,
  dunning_level: 0,
  dunned_at: null,
}
const detail = {
  ...row,
  recipient_address: 'Lindenweg 4\n12345 Musterstadt',
  note: '',
  cancelled_at: null,
  lines: [
    {
      id: 1,
      text: 'Mitgliedsbeitrag 2025',
      detail: 'aktiv',
      amount: '60.00',
      membership: 11,
      member_name: 'Muster, Erika',
      is_fee: true,
    },
  ],
  payments: [],
  dunnings: [],
  vat: [],
}

describe('Beiträge', () => {
  it('zeigt Rechnungen und bucht eine Zahlung', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${B}/runs/`]: () => ({ status: 200, body: [] }),
      [`GET ${B}/invoices/?page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [row] },
      }),
      [`GET ${B}/invoices/5/`]: () => ({ status: 200, body: detail }),
      [`POST ${B}/invoices/5/payments/`]: () => ({
        status: 200,
        body: {
          ...detail,
          status: 'paid',
          status_label: 'bezahlt',
          paid: '60.00',
          outstanding: '0.00',
          payments: [
            {
              id: 1,
              date: '2025-02-10',
              amount: '60.00',
              method: 'transfer',
              method_label: 'Überweisung',
              account_name: 'Girokonto',
              booking_id: 9,
              booking_number: '2025-0001',
            },
          ],
        },
      }),
    })
    renderApp('/finanzen/rechnungen')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'R2025-0001' }))
    expect(await screen.findByRole('heading', { name: /Rechnung R2025-0001/ })).toBeInTheDocument()
    const amount = screen.getByLabelText('Betrag (€)')
    expect(amount).toHaveValue('60,00')
    await user.clear(amount)
    await user.type(amount, '60')
    await user.click(screen.getByRole('button', { name: 'Zahlung buchen' }))
    expect(await screen.findByText('Bezahlt.')).toBeInTheDocument()
    expect(screen.getByText('Buchung 2025-0001')).toBeInTheDocument()
    const pay = calls.find((c) => c.key === `POST ${B}/invoices/5/payments/`)!
    expect(JSON.parse(String(pay.init?.body))).toMatchObject({
      amount: '60',
      method: 'transfer',
      account: 1,
    })
  })

  it('öffnet eine Rechnung direkt über die Adresse', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${B}/runs/`]: () => ({ status: 200, body: [] }),
      [`GET ${B}/invoices/?page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [row] },
      }),
      [`GET ${B}/invoices/5/`]: () => ({ status: 200, body: detail }),
    })
    renderApp('/finanzen/rechnungen?rechnung=5')
    expect(await screen.findByRole('heading', { name: /Rechnung R2025-0001/ })).toBeInTheDocument()
  })

  it('berechnet die Vorschau eines Beitragslaufs und legt ihn an', async () => {
    let runs: unknown[] = []
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${B}/runs/`]: () => ({ status: 200, body: runs }),
      [`POST ${B}/runs/preview/`]: () => ({
        status: 200,
        body: {
          label: '2025',
          start: '2025-01-01',
          end: '2025-12-31',
          exists: false,
          members: 3,
          members_total: '150.00',
          departments: [{ id: 4, name: 'Jägerzug', members: 12, total: '720.00' }],
          skipped: [{ membership: 9, name: 'Ehre, Emil', reason: 'beitragsfrei (Ehrenmitglied)' }],
        },
      }),
      [`POST ${B}/runs/`]: () => {
        runs = [
          {
            id: 1,
            year: 2025,
            rhythm: 'yearly',
            rhythm_label: 'jährlich',
            period: 1,
            start_date: '2025-01-01',
            end_date: '2025-12-31',
            label: '2025',
            invoice_date: '2025-02-01',
            due_date: '2025-02-15',
            created_at: '2025-02-01T10:00:00Z',
            summary: {
              counts: { draft: 4, open: 0, paid: 0, cancelled: 0 },
              totals: { draft: '870.00', open: '0.00', paid: '0.00', cancelled: '0.00' },
              members: 15,
              departments: 0,
              paid: '0.00',
              unsent_with_email: 0,
              without_email: 1,
            },
          },
        ]
        return { status: 201, body: runs[0] }
      },
    })
    renderApp('/finanzen/rechnungen/beitragslaeufe')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neuer Beitragslauf' }))
    await user.click(screen.getByRole('button', { name: 'Vorschau berechnen' }))
    expect(await screen.findByText(/Sammelrechnung Jägerzug: 12 Mitglieder/)).toBeInTheDocument()
    expect(screen.getByText('Gesamt: 870,00 €')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Rechnungsentwürfe erstellen' }))
    expect(
      await screen.findByRole('button', { name: 'Entwürfe festschreiben' }),
    ).toBeInTheDocument()
    const steps = screen.getByRole('list', { name: 'Stand des Beitragslaufs' })
    expect(within(steps).getByText('Entwürfe prüfen').closest('li')).toHaveAttribute(
      'aria-current',
      'step',
    )
    const created = calls.find((c) => c.key === `POST ${B}/runs/`)!
    expect(JSON.parse(String(created.init?.body))).toMatchObject({ year: 2025, period: 1 })
  })

  it('speichert Beiträge je Mitgliedsart mit Komma', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${B}/fees/`]: () => ({
        status: 200,
        body: [
          { member_type: 1, name: 'aktiv', active: true, amount: '60.00' },
          { member_type: 2, name: 'passiv', active: false, amount: null },
        ],
      }),
      [`GET ${B}/age-rates/`]: () => ({ status: 200, body: [] }),
      [`PUT ${B}/fees/`]: () => ({
        status: 200,
        body: [
          { member_type: 1, name: 'aktiv', active: true, amount: '60.00' },
          { member_type: 2, name: 'passiv', active: false, amount: '30.50' },
        ],
      }),
    })
    renderApp('/finanzen/einstellungen/beitraege')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('passiv (€ im Jahr)'), '30,50')
    // Autospeichern, kein Knopf
    expect(await screen.findByText('✓ Gespeichert', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(calls.filter((c) => c.key === `PUT ${B}/fees/`)).toHaveLength(1)
    const put = calls.find((c) => c.key === `PUT ${B}/fees/`)!
    expect(JSON.parse(String(put.init?.body))).toEqual([
      { member_type: 1, amount: '60.00' },
      { member_type: 2, amount: '30.50' },
    ])
  })

  it('erstellt fällige Mahnungen und bietet nicht verschickte zum Drucken an', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/dunnings/`]: () => ({
        status: 200,
        body: {
          levels: [
            { id: 1, level: 1, name: 'Zahlungserinnerung', days: 14, fee: '0.00', text: '' },
          ],
          proposals: [
            {
              ...row,
              overdue: true,
              days_overdue: 20,
              next_level: 1,
              next_level_name: 'Zahlungserinnerung',
              fee: '0.00',
            },
            {
              ...row,
              id: 6,
              number: 'R2025-0002',
              recipient_name: 'Otto Ohnemail',
              recipient_email: '',
              overdue: true,
              days_overdue: 20,
              next_level: 1,
              next_level_name: 'Zahlungserinnerung',
              fee: '0.00',
            },
          ],
        },
      }),
      [`POST ${B}/dunnings/`]: () => ({
        status: 201,
        body: { created: 2, sent: 1, unsent: [8] },
      }),
    })
    renderApp('/finanzen/rechnungen/mahnungen')
    const user = userEvent.setup()
    expect(await screen.findByText('Otto Ohnemail')).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: '2 Mahnungen erstellen und per E-Mail versenden' }),
    )
    expect(
      await screen.findByText(/2 Mahnungen erstellt, 1 per E-Mail verschickt/),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Mahnungen zum Drucken (PDF)' })).toHaveAttribute(
      'href',
      `${B}/dunnings/pdf/?ids=8`,
    )
    const post = calls.find((c) => c.key === `POST ${B}/dunnings/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({ invoices: [5, 6], send: true })
  })

  it('zeigt im Dachverband die Vorschau je Verein', async () => {
    const verband = testOrg({
      type: 'federation',
      modules: ['finance', 'billing'],
      permissions: ['billing.view', 'billing.edit'],
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [verband] }),
      [`GET ${B}/settings/`]: () => ({
        status: 200,
        body: { ...settings, org_type: 'federation', clubs: [{ id: 3, name: 'Verein A' }] },
      }),
      [`GET ${B}/runs/`]: () => ({ status: 200, body: [] }),
      [`POST ${B}/runs/preview/`]: () => ({
        status: 200,
        body: {
          label: '2025',
          start: '2025-01-01',
          end: '2025-12-31',
          exists: false,
          clubs: [{ id: 3, name: 'Verein A', members: 4, total: '54.00' }],
          clubs_total: '54.00',
        },
      }),
    })
    renderApp('/finanzen/rechnungen/beitragslaeufe')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neuer Beitragslauf' }))
    await user.click(screen.getByRole('button', { name: 'Vorschau berechnen' }))
    expect(await screen.findByText('Verein A: 4 gemeldete Mitglieder, 54,00 €')).toBeInTheDocument()
    expect(screen.getByText('Gesamt: 54,00 €')).toBeInTheDocument()
  })

  it('zeigt dem Verein die Rechnungen des Dachverbands', async () => {
    const verein = testOrg({
      modules: ['members', 'finance', 'billing'],
      permissions: ['billing.view'],
      parent_name: 'Testbund',
    })
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [verein] }),
      [`GET ${B}/received/`]: () => ({
        status: 200,
        body: {
          federation: 'Testbund',
          invoices: [
            {
              ...detail,
              id: 9,
              number: 'R2025-0003',
              recipient_kind: 'club',
              subject: 'Verbandsbeitrag 2025',
              total: '54.00',
              outstanding: '54.00',
              lines: [{ id: 1, text: 'aktive Mitglieder', detail: '2 × 10,00 €', amount: '20.00' }],
            },
          ],
        },
      }),
    })
    renderApp('/finanzen/rechnungen/dachverband')
    expect(
      await screen.findByRole('heading', { name: 'Rechnungen von Testbund' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Verbandsbeitrag 2025')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute(
      'href',
      `${B}/received/9/pdf/`,
    )
  })

  it('erstellt einen Lastschriftlauf und bietet die Datei für die Bank an', async () => {
    let runs: unknown[] = []
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${B}/mandates/?`]: () => ({
        status: 200,
        body: { count: 0, next: null, previous: null, results: [] },
      }),
      [`GET ${B}/debits/proposals/`]: () => ({
        status: 200,
        body: {
          creditor_id: 'DE98ZZZ09999999999',
          account: 'Girokonto',
          account_has_iban: true,
          earliest: '2030-01-07',
          prenotification_days: 5,
          invoices: runs.length
            ? []
            : [
                {
                  ...row,
                  mandate: 'MITGL-11-1',
                  holder: 'Erika Muster',
                  iban_masked: 'DE02 **** 2051',
                },
              ],
        },
      }),
      [`GET ${B}/debits/`]: () => ({ status: 200, body: runs }),
      [`POST ${B}/debits/`]: () => {
        runs = [
          {
            id: 3,
            collection_date: '2030-01-07',
            account: 1,
            account_name: 'Girokonto',
            status: 'created',
            status_label: 'erstellt',
            total: '60.00',
            created_at: '2030-01-01T10:00:00Z',
            booked_at: null,
            items: [
              {
                id: 1,
                invoice: 5,
                invoice_number: 'R2025-0001',
                recipient_name: 'Erika Muster',
                recipient_email: 'erika@example.org',
                payer: 'Erika Muster',
                mandate_reference: 'MITGL-11-1',
                amount: '60.00',
                sequence: 'FRST',
                prenotified_at: '2030-01-01T10:00:00Z',
                payment: null,
              },
            ],
          },
        ]
        return { status: 201, body: { ...(runs[0] as object), prenotified: 1 } }
      },
    })
    renderApp('/finanzen/lastschrift')
    const user = userEvent.setup()
    expect(await screen.findByText('MITGL-11-1')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Einzugsdatum/)).toHaveValue('2030-01-07')
    await user.click(screen.getByRole('button', { name: /^1 Lastschriften über/ }))
    expect(await screen.findByText(/1 Ankündigungen per E-Mail verschickt/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Datei für die Bank (SEPA-XML)' })).toHaveAttribute(
      'href',
      `${B}/debits/3/xml/`,
    )
    const post = calls.find((c) => c.key === `POST ${B}/debits/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({
      invoices: [5],
      collection_date: '2030-01-07',
    })
  })

  it('Arbeitsbereich einer Untereinheit: Rechnung an ein Mitglied ohne Beitragsläufe', async () => {
    const zug = testOrg({
      id: 21,
      name: 'Jägerzug',
      type: 'unit',
      type_label: 'Zug',
      modules: ['finance', 'billing'],
      permissions: ['billing.view', 'billing.edit', 'finance.view', 'finance.edit'],
      sepa_enabled: false,
    })
    const Z = '/api/orgs/21/billing'
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [zug] }),
      [`GET ${Z}/settings/`]: () => ({ status: 200, body: { ...settings, org_type: 'unit' } }),
      [`GET ${Z}/invoices/?page=1`]: () => ({
        status: 200,
        body: { count: 0, next: null, previous: null, results: [] },
      }),
      [`GET ${Z}/members/?suche=An`]: () => ({
        status: 200,
        body: [{ id: 31, first_name: 'Anna', last_name: 'Zugmitglied', email: '' }],
      }),
      [`POST ${Z}/invoices/`]: () => ({
        status: 201,
        body: { ...detail, id: 6, status: 'draft', issuer_name: 'Jägerzug' },
      }),
    })
    renderApp('/finanzen/rechnungen')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neue Rechnung' }))
    expect(screen.queryByLabelText('Empfänger')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Beitragslauf')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Beitragsläufe' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Mitglied'), 'An')
    await user.click(await screen.findByRole('button', { name: /Zugmitglied, Anna/ }))
    await user.type(screen.getByLabelText('Posten 1'), 'Zugfahrt')
    await user.type(screen.getByLabelText('Betrag (€)'), '25')
    await user.click(screen.getByRole('button', { name: 'Entwurf anlegen' }))
    await screen.findByRole('heading', { name: /Rechnung/ })
    const post = calls.find((c) => c.key === `POST ${Z}/invoices/`)!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({
      recipient_kind: 'member',
      membership: 31,
    })
    expect(calls.some((c) => c.key.includes('/runs/'))).toBe(false)
  })

  it('speichert keine Rechnung, deren Summe unvollständige Posten enthält', async () => {
    const zug = testOrg({
      id: 21,
      name: 'Jägerzug',
      type: 'unit',
      type_label: 'Zug',
      modules: ['billing'],
      permissions: ['billing.view', 'billing.edit'],
      sepa_enabled: false,
    })
    const Z = '/api/orgs/21/billing'
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [zug] }),
      [`GET ${Z}/settings/`]: () => ({ status: 200, body: { ...settings, org_type: 'unit' } }),
      [`GET ${Z}/invoices/?page=1`]: () => ({
        status: 200,
        body: { count: 0, next: null, previous: null, results: [] },
      }),
      [`GET ${Z}/members/?suche=An`]: () => ({
        status: 200,
        body: [{ id: 31, first_name: 'Anna', last_name: 'Zugmitglied', email: '' }],
      }),
      [`POST ${Z}/invoices/`]: () => ({
        status: 201,
        body: { ...detail, id: 6, status: 'draft', issuer_name: 'Jägerzug' },
      }),
    })
    renderApp('/finanzen/rechnungen')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neue Rechnung' }))
    await user.type(screen.getByLabelText('Mitglied'), 'An')
    await user.click(await screen.findByRole('button', { name: /Zugmitglied, Anna/ }))
    await user.type(screen.getByLabelText(/^Posten 1/), 'Beitrag')
    await user.type(screen.getAllByLabelText(/^Betrag/)[0], '10')
    await user.click(screen.getByRole('button', { name: 'Posten hinzufügen' }))
    await user.type(screen.getAllByLabelText(/^Betrag/)[1], '50')
    expect(screen.getByText(/Summe 60,00/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Entwurf anlegen' }))
    expect(await screen.findByText(/Posten 2: Bitte eine Bezeichnung ergänzen/)).toBeInTheDocument()
    expect(calls.some((c) => c.key === `POST ${Z}/invoices/`)).toBe(false)
    await user.type(screen.getByLabelText(/^Posten 2/), 'Umlage')
    await user.click(screen.getByRole('button', { name: 'Entwurf anlegen' }))
    await screen.findByRole('heading', { name: /Rechnung/ })
    const post = calls.find((c) => c.key === `POST ${Z}/invoices/`)!
    const lines = JSON.parse(String(post.init?.body)).lines
    expect(lines.map((l: { amount: string }) => l.amount)).toEqual(['10', '50'])
  })

  it('oberste Einheit mit eigenen Mitgliedern: Rechnung an Mitglied oder Untereinheit', async () => {
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({
        status: 200,
        body: {
          ...settings,
          org_type: 'federation',
          department_label: 'Verein',
          keeps_members: true,
          units: [{ id: 3, name: 'Verein A' }],
        },
      }),
      [`GET ${B}/invoices/?page=1`]: () => ({
        status: 200,
        body: { count: 0, next: null, previous: null, results: [] },
      }),
      [`POST ${B}/invoices/`]: () => ({ status: 201, body: { ...detail, id: 6, status: 'draft' } }),
    })
    renderApp('/finanzen/rechnungen')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Neue Rechnung' }))
    expect(screen.getByLabelText('Mitglied')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Empfänger'), 'unit')
    await user.selectOptions(screen.getByLabelText('Verein'), '3')
    await user.type(screen.getByLabelText(/^Posten 1/), 'Umlage')
    await user.type(screen.getAllByLabelText(/^Betrag/)[0], '10')
    await user.click(screen.getByRole('button', { name: 'Entwurf anlegen' }))
    await screen.findByRole('heading', { name: /Rechnung/ })
    const post = calls.find((c) => c.key === `POST ${B}/invoices/`)!
    const body = JSON.parse(String(post.init?.body))
    expect([body.recipient_kind, body.unit]).toEqual(['unit', 3])
  })

  it('speichert einen Rechnungsentwurf automatisch und legt neue Posten nur einmal an', async () => {
    const draft = { ...detail, status: 'draft', status_label: 'Entwurf', run: null }
    const saved = {
      ...draft,
      lines: [
        ...draft.lines,
        { id: 9, text: 'Umlage', detail: '', amount: '5.00', membership: 11, is_fee: false },
      ],
    }
    const calls = fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [kassierer] }),
      [`GET ${B}/settings/`]: () => ({ status: 200, body: settings }),
      [`GET ${B}/runs/`]: () => ({ status: 200, body: [] }),
      [`GET ${B}/invoices/?page=1`]: () => ({
        status: 200,
        body: { count: 1, next: null, previous: null, results: [row] },
      }),
      [`GET ${B}/invoices/5/`]: () => ({ status: 200, body: draft }),
      [`PATCH ${B}/invoices/5/`]: () => ({ status: 200, body: saved }),
    })
    renderApp('/finanzen/rechnungen?rechnung=5')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Bearbeiten' }))
    expect(screen.queryByRole('button', { name: /speichern/i })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Posten hinzufügen' }))
    await user.type(screen.getByLabelText(/^Posten 2/), 'Umlage')
    await user.type(screen.getAllByLabelText(/^Betrag/)[1], '5')
    const patches = () => calls.filter((c) => c.key === `PATCH ${B}/invoices/5/`)
    await waitFor(() => expect(patches()).toHaveLength(1), { timeout: 3000 })
    const first = JSON.parse(String(patches()[0].init?.body))
    expect(first.lines.map((l: { id: number | null }) => l.id)).toEqual([1, null])
    await user.type(screen.getAllByLabelText('Zusatz (optional)')[1], 'Fahrt')
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
    await waitFor(() => expect(patches().length).toBeGreaterThanOrEqual(2))
    const last = JSON.parse(String(patches().at(-1)!.init?.body))
    expect(last.lines.map((l: { id: number | null }) => l.id)).toEqual([1, 9])
    expect(last.lines[1]).toMatchObject({ text: 'Umlage', detail: 'Fahrt' })
  })
})
