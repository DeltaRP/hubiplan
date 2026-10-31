// Beiträge und Rechnungen: Beitragsregeln, Beitragsläufe, Rechnungen, Zahlungen.
import { api, newRequestKey } from './client.ts'
import type { Page, PickedMember } from './members.ts'
import type { DeptTerms } from '../org/terms.ts'

export type Rhythm = 'yearly' | 'halfyearly' | 'quarterly' | 'monthly'
export type InvoiceStatus = 'draft' | 'open' | 'paid' | 'cancelled'

export interface PeriodInfo {
  index: number
  label: string
  start: string
  end: string
}

export interface BillingSettings {
  rhythm: Rhythm
  due_days: number
  pro_rata: boolean
  account: number | null
  category: number | null
  intro_text: string
  footer_text: string
  qr_code: boolean
  vat_enabled: boolean
  vat_rate: string
  tax_number: string
  club_rate_active: string | null
  club_rate_passive: string | null
  club_base_amount: string | null
  sepa_enabled: boolean
  creditor_id: string
  prenotification_days: number
  rhythms: { value: Rhythm; label: string }[]
  accounts: { id: number; name: string; kind: string; has_iban: boolean }[]
  categories: { id: number; name: string }[]
  current_year: number
  years: { year: number; label: string }[]
  periods: Record<string, PeriodInfo[]>
  org_type: 'club' | 'federation' | 'unit'
  department_label: string
  department_label_plural: string
  department_terms?: DeptTerms
  clubs: { id: number; name: string }[]
  /** Führt die Einheit eigene Mitglieder (Rechnungen an Mitglieder möglich)? */
  keeps_members?: boolean
  /** Untereinheiten, an die Rechnungen gehen können */
  units?: { id: number; name: string }[]
  can_edit: boolean
}

export interface FeeRateRow {
  member_type: number
  name: string
  active: boolean
  amount: string | null
}

export interface AgeRate {
  id: number
  name: string
  member_type: number | null
  member_type_name: string | null
  min_age: number | null
  max_age: number | null
  amount: string | null
  discount_percent: string | null
}

export interface RunSummary {
  counts: Record<InvoiceStatus, number>
  totals: Record<InvoiceStatus, string>
  members: number
  departments: number
  paid: string
  unsent_with_email: number
  without_email: number
}

export interface FeeRun {
  id: number
  year: number
  rhythm: Rhythm
  rhythm_label: string
  period: number
  start_date: string
  end_date: string
  label: string
  invoice_date: string
  due_date: string
  created_at: string
  /** Postversand der Rechnungen ohne E-Mail erledigt (Datum) */
  post_done_at: string | null
  summary: RunSummary
  created?: number
  skipped?: { membership: number; name: string; reason: string }[]
  sent?: number
  failed?: number
  finalized?: number
}

export interface RunPreview {
  label: string
  start: string
  end: string
  exists: boolean
  // Verein
  members?: number
  members_total?: string
  departments?: { id: number; name: string; members: number; total: string }[]
  skipped?: { membership: number; name: string; reason: string }[]
  /** Zahlen für die Prüfliste */
  checks?: { unreachable: number; with_mandate: number; open_change_requests: number }
  // Dachverband
  clubs?: { id: number; name: string; members: number; total: string }[]
  clubs_total?: string
}

export interface InvoiceLine {
  id?: number
  text: string
  detail: string
  amount: string
  vat_rate?: string | null
  membership?: number | null
  member_name?: string | null
  is_fee?: boolean
  is_dunning_fee?: boolean
}

export interface DunningLevel {
  id: number
  level: number
  name: string
  days: number
  fee: string
  text: string
}

export interface Dunning {
  id: number
  level: number
  name: string
  date: string
  due_date: string
  fee: string
  sent_at: string | null
}

export interface DunningProposal extends InvoiceRow {
  days_overdue: number
  next_level: number
  next_level_name: string
  fee: string
}

export interface Payment {
  id: number
  date: string
  amount: string
  method: 'transfer' | 'cash' | 'debit'
  method_label: string
  account_name: string
  booking_id: number
  booking_number: string
}

export interface InvoiceRow {
  id: number
  number: string
  status: InvoiceStatus
  status_label: string
  recipient_kind: 'member' | 'department' | 'club'
  recipient_name: string
  recipient_email: string
  membership: number | null
  department: number | null
  department_name: string | null
  club: number | null
  club_name: string | null
  /** Einheit, die die Rechnung stellt */
  issuer_name: string
  run: number | null
  run_label: string | null
  project: number | null
  project_name: string | null
  date: string
  due_date: string
  subject: string
  total: string
  paid: string
  outstanding: string
  sent_at: string | null
  overdue: boolean
  dunning_level: number
  dunned_at: string | null
}

export interface Invoice extends InvoiceRow {
  recipient_address: string
  note: string
  cancelled_at: string | null
  lines: InvoiceLine[]
  payments: Payment[]
  dunnings: Dunning[]
  vat: { rate: string; gross: string; net: string; vat: string }[]
}

export interface InvoiceFilter {
  status?: string
  lauf?: string
  suche?: string
  ueberfaellig?: boolean
  gemahnt?: boolean
  verein?: string
  veranstaltung?: string
  page?: number
}

export interface InvoiceInput {
  recipient_kind?: 'member' | 'department' | 'club' | 'unit'
  /** Untereinheit als Empfänger (gilt für alle Einheiten gleich) */
  unit?: number | null
  membership?: number | null
  department?: number | null
  club?: number | null
  date?: string
  due_date?: string
  subject?: string
  note?: string
  project?: number | null
  lines?: {
    id?: number | null
    text: string
    detail: string
    amount: string
    vat_rate?: string | null
  }[]
}

export interface BillingOverview {
  sepa_enabled: boolean
  drafts: { count: number; amount: string }
  open: { count: number; amount: string }
  overdue: { count: number; amount: string }
  dunnings_due: number
  debits_ready: number
  debits_pending: { id: number; collection_date: string; total: string }[]
  last_run: { id: number; label: string; created_at: string } | null
  can_edit: boolean
}

const base = (org: number) => `/api/orgs/${org}/billing`

export const billingApi = {
  overview: (org: number) => api.get<BillingOverview>(`${base(org)}/overview/`),
  /** Mitglieder einer Untereinheit als Rechnungsempfänger */
  members: (org: number, term: string) =>
    api.get<PickedMember[]>(`${base(org)}/members/?suche=${encodeURIComponent(term)}`),
  settings: (org: number) => api.get<BillingSettings>(`${base(org)}/settings/`),
  updateSettings: (org: number, data: Partial<BillingSettings>) =>
    api.patch<BillingSettings>(`${base(org)}/settings/`, data),
  fees: (org: number) => api.get<FeeRateRow[]>(`${base(org)}/fees/`),
  saveFees: (org: number, rows: { member_type: number; amount: string | null }[]) =>
    api.put<FeeRateRow[]>(`${base(org)}/fees/`, rows),
  ageRates: (org: number) => api.get<AgeRate[]>(`${base(org)}/age-rates/`),
  createAgeRate: (org: number, data: Partial<AgeRate>) =>
    api.post<AgeRate>(`${base(org)}/age-rates/`, data),
  deleteAgeRate: (org: number, id: number) => api.del(`${base(org)}/age-rates/${id}/`),

  runs: (org: number) => api.get<FeeRun[]>(`${base(org)}/runs/`),
  run: (org: number, id: number) => api.get<FeeRun>(`${base(org)}/runs/${id}/`),
  preview: (org: number, year: number, period: number) =>
    api.post<RunPreview>(`${base(org)}/runs/preview/`, { year, period }),
  createRun: (org: number, data: { year: number; period: number; invoice_date: string }) =>
    api.post<FeeRun>(`${base(org)}/runs/`, data),
  rebuildRun: (org: number, id: number, confirmed = false) =>
    api.post<FeeRun>(`${base(org)}/runs/${id}/rebuild/${confirmed ? '?bestaetigt=1' : ''}`),
  finalizeRun: (org: number, id: number) => api.post<FeeRun>(`${base(org)}/runs/${id}/finalize/`),
  sendRun: (org: number, id: number) => api.post<FeeRun>(`${base(org)}/runs/${id}/send/`),
  postDone: (org: number, id: number, done: boolean) =>
    api.post<FeeRun>(`${base(org)}/runs/${id}/postversand/`, { done }),
  deleteRun: (org: number, id: number) => api.del(`${base(org)}/runs/${id}/`),
  runPdfUrl: (org: number, id: number, which = '') =>
    `${base(org)}/runs/${id}/pdf/${which ? `?nur=${which}` : ''}`,

  invoices: (org: number, f: InvoiceFilter) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(f)) {
      if (v === undefined || v === '' || v === false) continue
      q.set(k, v === true ? '1' : String(v))
    }
    return api.get<Page<InvoiceRow>>(`${base(org)}/invoices/?${q}`)
  },
  invoice: (org: number, id: number) => api.get<Invoice>(`${base(org)}/invoices/${id}/`),
  // Ein Schlüssel je Speichern: eine automatische Wiederholung nach Verbindungsabbruch
  // legt nichts doppelt an und ändert die Posten nicht ein zweites Mal
  createInvoice: (org: number, data: InvoiceInput) =>
    api.post<Invoice>(`${base(org)}/invoices/`, data, newRequestKey()),
  updateInvoice: (org: number, id: number, data: InvoiceInput) =>
    api.patch<Invoice>(`${base(org)}/invoices/${id}/`, data, newRequestKey()),
  deleteInvoice: (org: number, id: number) => api.del(`${base(org)}/invoices/${id}/`),
  finalize: (org: number, id: number) => api.post<Invoice>(`${base(org)}/invoices/${id}/finalize/`),
  cancel: (org: number, id: number) => api.post<Invoice>(`${base(org)}/invoices/${id}/cancel/`),
  send: (org: number, id: number) => api.post<Invoice>(`${base(org)}/invoices/${id}/send/`),
  pdfUrl: (org: number, id: number) => `${base(org)}/invoices/${id}/pdf/`,
  addPayment: (
    org: number,
    id: number,
    data: { date: string; amount?: string; method: string; account: number },
    requestKey?: string,
  ) => api.post<Invoice>(`${base(org)}/invoices/${id}/payments/`, data, requestKey),
  deletePayment: (org: number, id: number) => api.del(`${base(org)}/payments/${id}/`),
  receiptUrl: (org: number, id: number) => `${base(org)}/payments/${id}/receipt/`,

  dunningLevels: (org: number) => api.get<DunningLevel[]>(`${base(org)}/dunning-levels/`),
  createDunningLevel: (org: number, data: Partial<DunningLevel>) =>
    api.post<DunningLevel>(`${base(org)}/dunning-levels/`, data),
  deleteDunningLevel: (org: number, id: number) => api.del(`${base(org)}/dunning-levels/${id}/`),
  dunnings: (org: number) =>
    api.get<{ levels: DunningLevel[]; proposals: DunningProposal[] }>(`${base(org)}/dunnings/`),
  dun: (org: number, invoices: number[], send: boolean) =>
    api.post<{ created: number; sent: number; unsent: number[] }>(`${base(org)}/dunnings/`, {
      invoices,
      send,
    }),
  dunningPdfUrl: (org: number, ids: number[]) => `${base(org)}/dunnings/pdf/?ids=${ids.join(',')}`,

  received: (org: number) =>
    api.get<{ federation: string | null; invoices: Invoice[] }>(`${base(org)}/received/`),
  receivedPdfUrl: (org: number, id: number) => `${base(org)}/received/${id}/pdf/`,
}

export interface CollectiveLine {
  id: number
  number: string
  date: string
  subject: string
  department_name: string
  amount: string
  status: InvoiceStatus
  status_label: string
}

export interface Mandate {
  id: number
  reference: string
  membership: number | null
  club: number | null
  payer_name: string
  holder: string
  iban: string
  iban_masked: string
  bic: string
  signed_on: string
  source: 'paper' | 'online'
  source_label: string
  status: 'active' | 'revoked'
  status_label: string
  revoked_on: string | null
  last_used_on: string | null
  expired: boolean
  created_at: string
}

export interface DebitItem {
  id: number
  invoice: number
  invoice_number: string
  recipient_name: string
  recipient_email: string
  payer: string
  mandate_reference: string
  amount: string
  sequence: 'FRST' | 'RCUR'
  prenotified_at: string | null
  payment: number | null
}

export interface DebitRun {
  id: number
  collection_date: string
  account: number
  account_name: string
  status: 'created' | 'booked' | 'cancelled'
  status_label: string
  total: string
  created_at: string
  booked_at: string | null
  items: DebitItem[]
  /** Was die Datei ungültig macht (Mandat widerrufen, Rechnung bezahlt …) */
  problems?: string[]
  prenotified?: number
  booked?: number
}

export interface DebitProposals {
  creditor_id: string
  creditor_valid?: boolean
  /** aktive Mandate, die bald verfallen */
  expiring_soon?: number
  account: string | null
  account_has_iban: boolean
  earliest: string
  prenotification_days: number
  invoices: (InvoiceRow & {
    mandate: string
    holder: string
    iban_masked: string
    has_email?: boolean
  })[]
}

export const sepaApi = {
  mandates: (org: number, f: { suche?: string; status?: string; page?: number } = {}) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(f)) if (v) q.set(k, String(v))
    return api.get<Page<Mandate>>(`${base(org)}/mandates/?${q}`)
  },
  createMandate: (
    org: number,
    data: {
      membership?: number | null
      club?: number | null
      holder: string
      iban: string
      bic: string
      signed_on: string
    },
  ) => api.post<Mandate>(`${base(org)}/mandates/`, data),
  revokeMandate: (org: number, id: number) =>
    api.post<Mandate>(`${base(org)}/mandates/${id}/revoke/`),
  proposals: (org: number) => api.get<DebitProposals>(`${base(org)}/debits/proposals/`),
  runs: (org: number) => api.get<DebitRun[]>(`${base(org)}/debits/`),
  createRun: (org: number, invoices: number[], collection_date: string) =>
    api.post<DebitRun>(`${base(org)}/debits/`, { invoices, collection_date }),
  bookRun: (org: number, id: number) => api.post<DebitRun>(`${base(org)}/debits/${id}/book/`),
  cancelRun: (org: number, id: number) => api.post<DebitRun>(`${base(org)}/debits/${id}/cancel/`),
  xmlUrl: (org: number, id: number) => `${base(org)}/debits/${id}/xml/`,
  prenotificationsUrl: (org: number, id: number, all = false) =>
    `${base(org)}/debits/${id}/prenotifications/${all ? '?alle=1' : ''}`,
}

export interface PortalMandate {
  available: boolean
  club_name: string
  creditor_id: string
  mandate: Mandate | null
  text: string
}

export const portalBillingApi = {
  mandate: (access: number) => api.get<PortalMandate>(`/api/portal/${access}/mandate/`),
  grantMandate: (
    access: number,
    data: { holder: string; iban: string; bic: string; consent: boolean },
  ) => api.post<PortalMandate>(`/api/portal/${access}/mandate/`, data),
  revokeMandate: (access: number) => api.del(`/api/portal/${access}/mandate/`),
  invoices: (access: number) =>
    api.get<{ invoices: InvoiceRow[]; collective: CollectiveLine[] }>(
      `/api/portal/${access}/invoices/`,
    ),
  pdfUrl: (access: number, id: number) => `/api/portal/${access}/invoices/${id}/pdf/`,
  deptInvoices: (dept: number) => api.get<Invoice[]>(`/api/depts/${dept}/invoices/`),
  deptPdfUrl: (dept: number, id: number) => `/api/depts/${dept}/invoices/${id}/pdf/`,
}
