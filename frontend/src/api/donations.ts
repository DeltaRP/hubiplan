// Zuwendungsbestätigungen (Spendenbescheinigungen), nur für eingetragene Vereine.
import { api } from './client.ts'
import type { Page } from './members.ts'

export type DonationKind = 'money' | 'fee' | 'goods'
export type GoodsOrigin = '' | 'business' | 'private' | 'unknown'

export interface DonationSettings {
  /** Schalter „steuerbegünstigt mit eigenem Bescheid“ */
  enabled: boolean
  purposes: string
  notice: 'exemption' | 'statute'
  notice_label: string
  tax_office: string
  tax_number: string
  notice_date: string | null
  assessment_period: string
  fees_allowed: boolean
  place: string
  /** bis wann der Bescheid für Bestätigungen reicht */
  valid_until: string | null
  /** was fehlt oder abgelaufen ist; leer = Ausstellen möglich */
  problems: string[]
}

export interface Donation {
  id: number
  date: string
  kind: DonationKind
  kind_label: string
  amount: string
  waiver: boolean
  membership: number | null
  donor_name: string
  donor_address: string
  goods_description: string
  goods_origin: GoodsOrigin
  goods_documents: boolean
  note: string
  booking: number | null
  booking_number: string | null
  statement: number | null
  statement_number: string | null
}

export type DonationInput = Omit<
  Donation,
  'id' | 'kind_label' | 'booking' | 'booking_number' | 'statement' | 'statement_number'
>

export interface DonationStatement {
  id: number
  number: string
  year: number
  kind: 'single' | 'collective'
  kind_label: string
  goods: boolean
  donor_name: string
  donor_address: string
  total: string
  period_from: string
  period_to: string
  issued_on: string
  issued_by_name: string
  signer_name: string
  cancelled_at: string | null
  cancel_reason: string
}

export interface YearEndPreview {
  year: number
  donors: {
    donor_name: string
    count: number
    total: string
    ids: number[]
    /** Grund, warum noch nicht bestätigt werden kann (leer = vollständig) */
    incomplete?: string
  }[]
  problems: string[]
}

const base = (org: number) => `/api/orgs/${org}/finance`

/** Offene (noch nicht bestätigte) Zuwendungen eines Jahres, für die Prüfliste */
export interface DonationCheckData {
  open: number
  without_address: number
  goods_without_documents: number
  goods_open: number
  fees_skipped: number
}

export const donationApi = {
  settings: (org: number) => api.get<DonationSettings>(`${base(org)}/donation-settings/`),
  saveSettings: (org: number, data: Partial<DonationSettings>) =>
    api.put<DonationSettings>(`${base(org)}/donation-settings/`, data),
  list: (org: number, query: { jahr?: number; offen?: boolean; suche?: string; page?: number }) => {
    const p = new URLSearchParams()
    if (query.jahr) p.set('jahr', String(query.jahr))
    if (query.offen) p.set('offen', '1')
    if (query.suche) p.set('suche', query.suche)
    if (query.page) p.set('page', String(query.page))
    return api.get<Page<Donation>>(`${base(org)}/donations/?${p.toString()}`)
  },
  create: (org: number, data: Partial<DonationInput>) =>
    api.post<Donation>(`${base(org)}/donations/`, data),
  update: (org: number, id: number, data: Partial<DonationInput>) =>
    api.patch<Donation>(`${base(org)}/donations/${id}/`, data),
  remove: (org: number, id: number) => api.del(`${base(org)}/donations/${id}/`),
  importBookings: (org: number, year: number) =>
    api.post<{ created: number }>(`${base(org)}/donations/import/`, { year }),
  years: (org: number) => api.get<number[]>(`${base(org)}/donations/years/`),
  /** Zahlen für die Prüfliste vor den Jahresbestätigungen */
  checks: (org: number, year: number) =>
    api.get<DonationCheckData>(`${base(org)}/donations/checks/?jahr=${year}`),
  statementYears: (org: number) => api.get<number[]>(`${base(org)}/donation-statements/years/`),
  yearEnd: (org: number, year: number) =>
    api.get<YearEndPreview>(`${base(org)}/donations/year-end/?jahr=${year}`),
  statements: (org: number, query: { jahr?: number; suche?: string; page?: number }) => {
    const p = new URLSearchParams()
    if (query.jahr) p.set('jahr', String(query.jahr))
    if (query.suche) p.set('suche', query.suche)
    if (query.page) p.set('page', String(query.page))
    return api.get<Page<DonationStatement>>(`${base(org)}/donation-statements/?${p.toString()}`)
  },
  issue: (org: number, donations: number[], signer_name: string) =>
    api.post<DonationStatement>(`${base(org)}/donation-statements/`, { donations, signer_name }),
  issueYearEnd: (org: number, year: number, signer_name: string) =>
    api.post<{ created: number; items: DonationStatement[] }>(
      `${base(org)}/donation-statements/year-end/`,
      { year, signer_name },
    ),
  cancel: (org: number, id: number, reason: string) =>
    api.post<DonationStatement>(`${base(org)}/donation-statements/${id}/cancel/`, { reason }),
  pdfUrl: (org: number, id: number) => `${base(org)}/donation-statements/${id}/pdf/`,
}
