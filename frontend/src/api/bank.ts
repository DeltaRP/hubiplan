// Kontoauszüge (CAMT.053): einlesen, Umsätze zuordnen und buchen.
import { api } from './client.ts'
import type { Page } from './members.ts'

export interface BalanceCheck {
  bank: string
  book: string
  difference: string
  ok: boolean
}

export interface BankStatement {
  id: number
  account: number
  account_name: string
  file_name: string
  reference: string
  date_from: string | null
  date_to: string | null
  opening_balance: string | null
  closing_balance: string | null
  line_count: number
  duplicate_count: number
  open_count: number
  balance: BalanceCheck | null
  created_at: string
}

export type BankLineStatus = 'open' | 'done' | 'ignored'
export type Suggestion = '' | 'invoice' | 'debit_run' | 'booked' | 'return'

export interface BankLine {
  id: number
  statement: number
  account: number
  date: string
  amount: string
  credit: boolean
  name: string
  iban: string
  purpose: string
  return_code: string
  batch_count: number
  /** Einzelposten einer Sammelbuchung, wie sie im Auszug stehen */
  details: { amount: string; name: string; iban: string; purpose: string; end_to_end: string }[]
  status: BankLineStatus
  status_label: string
  suggestion: Suggestion
  suggestion_label: string
  /** Vorschlag beruht auf einer Referenz; sonst nur nach Betrag und Datum („bitte prüfen“) */
  suggestion_sure: boolean
  suggested: {
    invoice?: { id: number; number: string; recipient: string; outstanding: string }
    run?: { id: number; date: string; total: string }
    booking?: { id: number; number: string; text: string }
    membership?: { id: number; name: string }
  }
  booking: number | null
  booking_number: string | null
}

export type AssignInput =
  | { action: 'suggestion' | 'ignore' | 'reopen' }
  | { action: 'invoice'; invoice: number }
  | {
      action: 'booking'
      category: number
      membership?: number | null
      project?: number | null
      text?: string
    }

const base = (org: number) => `/api/orgs/${org}/finance`

export const bankApi = {
  statements: (org: number, page = 1) =>
    api.get<Page<BankStatement>>(
      `${base(org)}/bank-statements/?page_size=50${page > 1 ? `&page=${page}` : ''}`,
    ),
  upload: (org: number, file: File, account?: number | null) => {
    const form = new FormData()
    form.append('file', file)
    if (account) form.append('account', String(account))
    return api.post<{ lines: number; duplicates: number; statements: BankStatement[] }>(
      `${base(org)}/bank-statements/`,
      form,
    )
  },
  removeStatement: (org: number, id: number) => api.del(`${base(org)}/bank-statements/${id}/`),
  lines: (
    org: number,
    query: { auszug?: number; status?: BankLineStatus | ''; page?: number; size?: number },
  ) => {
    const p = new URLSearchParams({ page_size: String(query.size ?? 1000) })
    if (query.page && query.page > 1) p.set('page', String(query.page))
    if (query.auszug) p.set('auszug', String(query.auszug))
    if (query.status) p.set('status', query.status)
    return api.get<Page<BankLine>>(`${base(org)}/bank-lines/?${p.toString()}`)
  },
  assign: (org: number, id: number, data: AssignInput) =>
    api.post<BankLine>(`${base(org)}/bank-lines/${id}/assign/`, data),
  applySuggestions: (org: number, statement?: number) =>
    api.post<{ done: number; failed: string[] }>(
      `${base(org)}/bank-lines/apply-suggestions/`,
      statement ? { statement } : {},
    ),
}
