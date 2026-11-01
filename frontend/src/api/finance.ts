// Kasse: Konten, Kategorien, Buchungen, Belege, Jahresübersicht.
import { api } from './client.ts'
import type { Page } from './members.ts'
import type { ClosingInput } from '../learning/checks.ts'
import { locale } from '../i18n/index.ts'

export type AccountKind = 'bank' | 'cash' | 'savings'
export type BookingKind = 'income' | 'expense' | 'transfer'
export type CategoryKind = 'income' | 'expense' | 'both'

export interface Account {
  id: number
  name: string
  /** DATEV-Finanzkonto (nur mit DATEV-Export) */
  datev_account?: string
  kind: AccountKind
  kind_label: string
  iban: string
  bic: string
  bank_name: string
  opening_balance: string
  opening_date: string
  is_active: boolean
  position: number
  /** Bestand heute */
  balance: string
  /** Bestand mit vorgemerkten Buchungen (Datum in der Zukunft), null wenn gleich */
  planned_balance: string | null
  booking_count: number
}

export interface CategoryUsage {
  deletable: boolean
  reasons: string[]
  is_archived: boolean
}

export interface Category {
  id: number
  name: string
  /** DATEV-Sachkonto (nur mit DATEV-Export) */
  datev_account?: string
  kind: CategoryKind
  kind_label: string
  tax_area: string
  tax_area_label: string
  /** Spenden: Einnahmen lassen sich als Zuwendung übernehmen */
  donations: boolean
  is_active: boolean
  booking_count: number
}

export interface Receipt {
  id: number
  name: string
  content_type: string
  size: number
  created_at: string
  // Ausgeblendet statt gelöscht (Aufbewahrungspflicht)
  hidden_at: string | null
  hidden_reason: string
  /** E-Rechnung (XRechnung, ZUGFeRD): ausgelesene Angaben, sonst leer */
  einvoice?: Partial<EInvoiceInfo>
}

export interface EInvoiceInfo {
  format: string
  credit_note: boolean
  number: string
  date: string | null
  due_date: string | null
  currency: string
  seller: string
  seller_vat_id: string
  buyer: string
  net: string | null
  tax: string | null
  gross: string | null
  payable: string
  iban: string
  buyer_reference: string
  lines: { text: string; quantity: string; unit: string; amount: string | null }[]
}

export interface EInvoiceSuggestion {
  kind: 'income' | 'expense'
  date: string | null
  amount: string
  counterparty: string
  reference: string
  text: string
}

export interface Booking {
  id: number
  year: number
  number: number
  display_number: string
  date: string
  kind: BookingKind
  kind_label: string
  amount: string
  account: number
  account_name: string
  to_account: number | null
  to_account_name: string | null
  category: number | null
  category_name: string | null
  tax_area: string
  text: string
  reference: string
  counterparty: string
  membership: number | null
  member_name: string | null
  department: number | null
  department_name: string | null
  project: number | null
  project_name: string | null
  receipts: Receipt[]
  created_at: string
  // GoBD: festgeschrieben = nur noch Storno; löschbar nur am Tag der Erfassung
  fixed: boolean
  deletable: boolean
  cancels: { id: number; number: string } | null
  cancel_reason: string
  cancelled_by: { id: number; number: string; reason: string; date: string } | null
}

export interface Overview {
  year: number
  label: string
  start_date: string
  end_date: string
  years: { year: number; label: string }[]
  tax_areas_enabled: boolean
  accounts: {
    id: number
    name: string
    kind: AccountKind
    kind_label: string
    is_active: boolean
    start: string
    income: string
    expense: string
    transfer_in: string
    transfer_out: string
    end: string
  }[]
  categories: { id: number; name: string; tax_area: string; income: string; expense: string }[]
  tax_areas: { area: string; label: string; income: string; expense: string }[]
  totals: { income: string; expense: string; result: string; start: string; end: string }
  booking_count: number
}

export interface FinanceSettings {
  tax_areas_enabled: boolean
  cash_counts_enabled?: boolean
  /** Rücklagen nach § 62 AO (zuschaltbar) */
  reserves_enabled?: boolean
  /** DATEV-Export für die Steuerberatung (zuschaltbar) */
  datev_enabled?: boolean
  datev_consultant?: string
  datev_client?: string
  datev_account_length?: number
  datev_chart?: string
  fiscal_start_month: number
  fiscal_start_day: number
  current_year: number
  current_label: string
  years: { year: number; label: string }[]
  tax_areas: { value: string; label: string }[]
  can_edit: boolean
  // Kasse festgeschrieben bis (von Hand) bzw. automatisch bis Ende des vorletzten Monats
  locked_until: string | null
  auto_locked_until: string
}

export interface BookingFilter {
  jahr?: string
  konto?: string
  kategorie?: string
  art?: string
  bereich?: string
  suche?: string
  partner?: string
  ohne_beleg?: boolean
  /** Nummer der Veranstaltung oder "-" für Buchungen ohne Veranstaltung */
  veranstaltung?: string
  von?: string
  bis?: string
  page?: number
  page_size?: number
}

export type ProjectStatus = 'planned' | 'running' | 'done'

export interface Project {
  id: number
  name: string
  starts_on: string
  ends_on: string | null
  description: string
  status: ProjectStatus
  status_label: string
  department: number | null
  department_name: string | null
  series: number | null
  series_name: string | null
  income: string
  expense: string
  result: string
  booking_count: number
  event_count: number
}

export interface ProjectSeries {
  id: number
  name: string
  project_count: number
}

export interface ProjectEvent {
  id: number
  title: string
  starts_at: string
  ends_at: string
  all_day: boolean
  is_series: boolean
  is_cancelled?: boolean
  linked?: boolean
}

export interface Sums {
  income: string
  expense: string
  result: string
}

export interface ProjectEvaluation {
  id: number
  name: string
  starts_on: string
  ends_on: string | null
  status: ProjectStatus
  status_label: string
  description: string
  department_name: string | null
  series: number | null
  series_name: string | null
  tax_areas_enabled: boolean
  categories: ({ id: number | null; name: string; tax_area: string } & Sums)[]
  tax_areas: ({ area: string; label: string } & Sums)[]
  totals: Sums
  booking_count: number
  bookings: {
    id: number
    display_number: string
    date: string
    kind: BookingKind
    kind_label: string
    amount: string
    text: string
    reference: string
    category_name: string | null
    account_name: string
    receipt_count: number
  }[]
  events: ProjectEvent[]
  open_invoices: { count: number; outstanding: string }
}

export interface SeriesComparison {
  id: number
  name: string
  projects: ({
    id: number
    name: string
    starts_on: string
    status: ProjectStatus
    status_label: string
    booking_count: number
  } & Sums)[]
  categories: { id: number | null; name: string; values: Sums[] }[]
}

/** Aufbewahrungsfrist eines abgeschlossenen Geschäftsjahres (Belege 8, Bücher 10 Jahre) */
export interface Retention {
  documents_from: string
  records_from: string
  documents_purged_at: string | null
  records_purged_at: string | null
  purged_by: string
  documents_due: boolean
  records_due: boolean
}

export interface Closings {
  years: {
    year: number
    label: string
    end_date: string
    running: boolean
    closed: boolean
    closed_at: string | null
    closed_by: string | null
    /** Zahlen für die Prüfliste (nur offene Jahre) */
    checks?: ClosingInput | null
    /** Frühere, aufgehobene Abschlüsse (neueste zuerst) */
    reopened?: {
      closed_at: string
      closed_by: string
      reopened_at: string
      reopened_by: string
      reason: string
    }[]
    /** Unterschiede des jetzigen Abschlusses zum zuletzt aufgehobenen */
    changes?: string[]
    /** Ende der Aufbewahrungsfrist (nur abgeschlossene Jahre) */
    retention?: Retention | null
  }[]
  can_close: boolean
  can_reopen: boolean
}

const base = (org: number) => `/api/orgs/${org}/finance`

export const financeApi = {
  settings: (org: number) => api.get<FinanceSettings>(`${base(org)}/settings/`),
  lockUntil: (org: number, date: string) =>
    api.patch<FinanceSettings>(`${base(org)}/settings/`, { locked_until: date }),
  updateSettings: (org: number, data: Partial<FinanceSettings>) =>
    api.patch<FinanceSettings>(`${base(org)}/settings/`, data),
  /** DATEV-Buchungsstapel (EXTF) eines Geschäftsjahres */
  datevUrl: (org: number, year: number) => `${base(org)}/datev/?jahr=${year}`,
  closings: (org: number) => api.get<Closings>(`${base(org)}/closings/`),
  closeYear: (org: number, year: number) => api.post<Closings>(`${base(org)}/closings/`, { year }),
  purgeYear: (org: number, year: number) =>
    api.post<{ done: string; counts: Record<string, number> }>(
      `${base(org)}/closings/aufbewahrung/`,
      { year },
    ),
  reopenYear: (org: number, year: number, reason: string) =>
    api.delWith<Closings>(`${base(org)}/closings/?jahr=${year}`, { reason }),
  reportUrl: (org: number, year: number) => `${base(org)}/report/?jahr=${year}`,
  /** ZIP für eine Prüfung (Finanzamt, Kassenprüfer): alle Finanzdaten mit Belegen und index.xml */
  exportUrl: (org: number, year: number) => `${base(org)}/export/?jahr=${year}`,
  overview: (org: number, year: number) => api.get<Overview>(`${base(org)}/overview/?jahr=${year}`),

  accounts: (org: number) => api.get<Account[]>(`${base(org)}/accounts/`),
  createAccount: (org: number, data: Partial<Account>) =>
    api.post<Account>(`${base(org)}/accounts/`, data),
  updateAccount: (org: number, id: number, data: Partial<Account>) =>
    api.patch<Account>(`${base(org)}/accounts/${id}/`, data),
  deleteAccount: (org: number, id: number) => api.del(`${base(org)}/accounts/${id}/`),

  categories: (org: number) => api.get<Category[]>(`${base(org)}/categories/`),
  createCategory: (org: number, data: Partial<Category>) =>
    api.post<Category>(`${base(org)}/categories/`, data),
  updateCategory: (org: number, id: number, data: Partial<Category>) =>
    api.patch<Category>(`${base(org)}/categories/${id}/`, data),
  deleteCategory: (org: number, id: number) => api.del(`${base(org)}/categories/${id}/`),
  categoryUsage: (org: number, id: number) =>
    api.get<CategoryUsage>(`${base(org)}/categories/${id}/usage/`),
  archiveCategory: (org: number, id: number) =>
    api.post<Category>(`${base(org)}/categories/${id}/archive/`),
  restoreCategory: (org: number, id: number) =>
    api.post<Category>(`${base(org)}/categories/${id}/restore/`),

  bookings: (org: number, f: BookingFilter) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(f)) {
      if (v === undefined || v === '' || v === false) continue
      q.set(k, v === true ? '1' : String(v))
    }
    return api.get<Page<Booking>>(`${base(org)}/bookings/?${q}`)
  },
  counterparties: (org: number, kind?: string) =>
    api.get<{ name: string; count: number }[]>(
      `${base(org)}/bookings/counterparties/${kind ? `?art=${kind}` : ''}`,
    ),
  booking: (org: number, id: number) => api.get<Booking>(`${base(org)}/bookings/${id}/`),
  createBooking: (org: number, data: Record<string, unknown>) =>
    api.post<Booking>(`${base(org)}/bookings/`, data),
  updateBooking: (org: number, id: number, data: Record<string, unknown>) =>
    api.patch<Booking>(`${base(org)}/bookings/${id}/`, data),
  deleteBooking: (org: number, id: number) => api.del(`${base(org)}/bookings/${id}/`),
  stornoBooking: (org: number, id: number, reason: string) =>
    api.post<Booking>(`${base(org)}/bookings/${id}/storno/`, { reason }),
  renumber: (org: number, year: number) =>
    api.post<{ changed: number }>(`${base(org)}/bookings/renumber/`, { year }),

  projects: (org: number, f: { status?: string; reihe?: string } = {}) => {
    const q = new URLSearchParams()
    if (f.status) q.set('status', f.status)
    if (f.reihe) q.set('reihe', f.reihe)
    return api.get<Project[]>(`${base(org)}/projects/?${q}`)
  },
  createProject: (org: number, data: Record<string, unknown>) =>
    api.post<Project>(`${base(org)}/projects/`, data),
  updateProject: (org: number, id: number, data: Record<string, unknown>) =>
    api.patch<Project>(`${base(org)}/projects/${id}/`, data),
  deleteProject: (org: number, id: number) => api.del(`${base(org)}/projects/${id}/`),
  projectEvaluation: (org: number, id: number) =>
    api.get<ProjectEvaluation>(`${base(org)}/projects/${id}/evaluation/`),
  projectReportUrl: (org: number, id: number, als: 'pdf' | 'xlsx') =>
    `${base(org)}/projects/${id}/report/?als=${als}`,
  assignBookings: (org: number, id: number, bookings: number[]) =>
    api.post<{ changed: number }>(`${base(org)}/projects/${id}/assign/`, { bookings }),
  unassignBookings: (org: number, id: number, bookings: number[]) =>
    api.post<{ changed: number }>(`${base(org)}/projects/${id}/unassign/`, { bookings }),
  eventCandidates: (org: number, id: number, suche = '') =>
    api.get<ProjectEvent[]>(
      `${base(org)}/projects/${id}/event-candidates/${suche ? `?suche=${encodeURIComponent(suche)}` : ''}`,
    ),
  linkEvents: (org: number, id: number, data: { events?: number[]; unlink?: number[] }) =>
    api.post<ProjectEvaluation>(`${base(org)}/projects/${id}/link-events/`, data),

  series: (org: number) => api.get<ProjectSeries[]>(`${base(org)}/series/`),
  createSeries: (org: number, name: string) =>
    api.post<ProjectSeries>(`${base(org)}/series/`, { name }),
  updateSeries: (org: number, id: number, name: string) =>
    api.patch<ProjectSeries>(`${base(org)}/series/${id}/`, { name }),
  deleteSeries: (org: number, id: number) => api.del(`${base(org)}/series/${id}/`),
  seriesComparison: (org: number, id: number) =>
    api.get<SeriesComparison>(`${base(org)}/series/${id}/comparison/`),
  seriesReportUrl: (org: number, id: number, als: 'pdf' | 'xlsx') =>
    `${base(org)}/series/${id}/report/?als=${als}`,

  uploadReceipt: (org: number, booking: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<Receipt>(`${base(org)}/bookings/${booking}/receipts/`, form)
  },
  receiptUrl: (org: number, id: number) => `${base(org)}/receipts/${id}/`,
  /** Lesbare Ansicht (PDF) einer E-Rechnung im XML-Format */
  receiptViewUrl: (org: number, id: number) => `${base(org)}/receipts/${id}/?ansicht=1`,
  /** E-Rechnung lesen (nichts wird gespeichert): Angaben und Buchungsvorschlag */
  readEinvoice: (org: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ einvoice: EInvoiceInfo; suggestion: EInvoiceSuggestion }>(
      `${base(org)}/einvoice/`,
      form,
    )
  },
  // Ohne Grund: löschen (nur kurz nach dem Hochladen), mit Grund: ausblenden
  deleteReceipt: (org: number, id: number, reason?: string) =>
    reason === undefined
      ? api.del(`${base(org)}/receipts/${id}/`)
      : api.delWith<Receipt>(`${base(org)}/receipts/${id}/`, { reason }),

  // Quittungen mit Unterschrift
  cashReceipts: (org: number, status?: CashReceiptStatus) =>
    api.get<Page<CashReceipt>>(`${base(org)}/cash-receipts/${status ? `?status=${status}` : ''}`),
  cashReceipt: (org: number, id: number) =>
    api.get<CashReceipt>(`${base(org)}/cash-receipts/${id}/`),
  createCashReceipt: (org: number, data: CashReceiptInput) =>
    api.post<CashReceipt>(`${base(org)}/cash-receipts/`, data),
  cashReceiptFromInvoice: (
    org: number,
    invoice: number,
    data: { account: number; amount?: string },
  ) => api.post<CashReceipt>(`${base(org)}/cash-receipts/from-invoice/${invoice}/`, data),
  updateCashReceipt: (org: number, id: number, data: Partial<CashReceiptInput>) =>
    api.patch<CashReceipt>(`${base(org)}/cash-receipts/${id}/`, data),
  deleteCashReceipt: (org: number, id: number) => api.del(`${base(org)}/cash-receipts/${id}/`),
  signCashReceipt: (
    org: number,
    id: number,
    role: SignatureRole,
    data: SignatureInput | { use_stored: true } | { declined: string },
  ) => api.put<CashReceipt>(`${base(org)}/cash-receipts/${id}/signatures/${role}/`, data),
  clearSignature: (org: number, id: number, role: SignatureRole) =>
    api.delWith<CashReceipt>(`${base(org)}/cash-receipts/${id}/signatures/${role}/`, {}),
  finalizeCashReceipt: (org: number, id: number, key: string, send: boolean) =>
    api.post<CashReceipt>(
      `${base(org)}/cash-receipts/${id}/finalize/`,
      { confirmed: true, send },
      key,
    ),
  cancelCashReceipt: (org: number, id: number, reason: string) =>
    api.post<CashReceipt>(`${base(org)}/cash-receipts/${id}/cancel/`, { reason }),
  sendCashReceipt: (org: number, id: number, email?: string) =>
    api.post<CashReceipt>(`${base(org)}/cash-receipts/${id}/send/`, email ? { email } : {}),
  cashReceiptPdfUrl: (org: number, id: number) => `${base(org)}/cash-receipts/${id}/pdf/`,
}

// --- Quittungen mit Unterschrift (konzepte/digitale-quittung.md) ---

export type CashReceiptStatus = 'draft' | 'final' | 'cancelled'
export type SignatureRole = 'treasurer' | 'counterparty'

/** Gespeicherte Form einer Unterschrift: Breite 1000, Linienzüge als x,y,x,y,… */
export interface StoredShape {
  w: number
  h: number
  s: number[][]
}

/** So schickt das Zeichenfeld eine Unterschrift (nur Form, keine Zeit- oder Druckwerte). */
export interface SignatureInput {
  width: number
  height: number
  strokes: [number, number][][]
  signed_at?: string
}

export interface CashReceiptInput {
  direction: 'in' | 'out'
  counterparty_name: string
  counterparty_address: string
  membership: number | null
  email: string
  amount: string
  purpose: string
  vat_rate: string | null
  account: number | null
  category: number | null
  project: number | null
}

export interface CashReceipt extends CashReceiptInput {
  id: number
  direction_label: string
  status: CashReceiptStatus
  status_label: string
  account_name: string
  category_name: string
  invoice: number | null
  invoice_number: string | null
  treasurer_signature: StoredShape | null
  treasurer_name: string
  treasurer_signed_at: string | null
  counterparty_signature: StoredShape | null
  counterparty_signed_at: string | null
  no_signature_reason: string
  confirmation_text: string
  missing: string[]
  has_stored_signature: boolean
  number: string
  receipt_date: string | null
  booking: number | null
  booking_number: string | null
  finalized_at: string | null
  pdf_sha256: string
  cancel_reason: string
  cancelled_at: string | null
  cancel_number: string | null
  sent_at: string | null
  source: string
  created_at: string
}

export const signatureApi = {
  get: () =>
    api.get<{ signature: StoredShape | null; updated_at: string | null }>('/api/me/signature/'),
  save: (data: SignatureInput) =>
    api.put<{ signature: StoredShape | null; updated_at: string | null }>(
      '/api/me/signature/',
      data,
    ),
  remove: () => api.del('/api/me/signature/'),
}

const EUR = new Intl.NumberFormat(locale(), { style: 'currency', currency: 'EUR' })

export function euro(value: string | number | null | undefined): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0)
  return EUR.format(Number.isFinite(n) ? n : 0)
}

/** "12,50" oder "1.234,56" in "12.50" bzw. "1234.56" umwandeln. */
export function parseAmount(input: string): string {
  const t = input.trim().replace(/\s|€/g, '')
  if (!t) return ''
  const normalized = t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t
  return normalized
}

export interface CashCount {
  id: number
  kind: 'count' | 'event'
  kind_label: string
  account: number
  account_name: string
  date: string
  title: string
  project: number | null
  denominations: Record<string, number>
  counted: string
  expected: string
  difference: string
  opening: string
  expenses: string
  withdrawals: string
  takings: string
  lines: { category: number; name: string; amount: string }[]
  note: string
  counted_by: string
  witness: string
  bookings: { id: number; number: string }[]
  pdf_sha256: string
  created_at: string
}

export interface CashCountInput {
  kind: 'count' | 'event'
  account: number
  date: string
  title?: string
  project?: number | null
  denominations: Record<string, number>
  opening?: string
  expenses?: string
  withdrawals?: string
  lines?: { category: number; amount: string }[]
  note?: string
  category?: number | null
  counted_by: string
  witness?: string
}

/** Stückelung in Cent: Scheine und Münzen */
export const DENOMINATIONS = [
  50000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 2, 1,
]

export const cashCountApi = {
  list: (org: number) =>
    api.get<{ results: CashCount[]; count: number }>(`${base(org)}/cash-counts/?page=1`),
  create: (org: number, data: CashCountInput) =>
    api.post<CashCount>(`${base(org)}/cash-counts/`, data),
  pdfUrl: (org: number, id: number) => `${base(org)}/cash-counts/${id}/pdf/`,
}

/** Rücklage nach § 62 AO (bindet Mittel für einen Zweck, bewegt kein Geld) */
export type ReserveKind = 'purpose' | 'replacement' | 'free' | 'other'

export const RESERVE_KINDS: { value: ReserveKind; label: string }[] = [
  { value: 'purpose', label: 'Projektrücklage (§ 62 Abs. 1 Nr. 1 AO)' },
  { value: 'replacement', label: 'Wiederbeschaffungsrücklage (§ 62 Abs. 1 Nr. 2 AO)' },
  { value: 'free', label: 'freie Rücklage (§ 62 Abs. 1 Nr. 3 AO)' },
  { value: 'other', label: 'sonstige Rücklage' },
]

export interface ReserveMovement {
  id: number
  direction: 'add' | 'release'
  direction_label: string
  date: string
  year: number
  year_label: string
  amount: string
  note: string
  created_by_name: string
  created_at: string
  /** Geschäftsjahr noch offen: lässt sich löschen */
  open: boolean
}

export interface Reserve {
  id: number
  name: string
  kind: ReserveKind
  kind_label: string
  purpose: string
  is_active: boolean
  balance: string
  movements: ReserveMovement[]
}

export interface ReserveOverview {
  reserves: Reserve[]
  total: string
  funds: string
  free: string
}

export const reserveApi = {
  list: (org: number) => api.get<ReserveOverview>(`${base(org)}/reserves/`),
  create: (org: number, data: Pick<Reserve, 'name' | 'kind' | 'purpose'>) =>
    api.post<Reserve>(`${base(org)}/reserves/`, data),
  update: (
    org: number,
    id: number,
    data: Partial<Pick<Reserve, 'name' | 'purpose' | 'is_active'>>,
  ) => api.patch<Reserve>(`${base(org)}/reserves/${id}/`, data),
  remove: (org: number, id: number) => api.del(`${base(org)}/reserves/${id}/`),
  move: (
    org: number,
    id: number,
    data: { direction: 'add' | 'release'; date: string; amount: string; note: string },
  ) => api.post<ReserveMovement>(`${base(org)}/reserves/${id}/movements/`, data),
  removeMove: (org: number, id: number, move: number) =>
    api.del(`${base(org)}/reserves/${id}/movements/${move}/`),
}
