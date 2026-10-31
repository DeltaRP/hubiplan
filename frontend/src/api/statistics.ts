// Auswertungen über die Zeit: Mitgliederentwicklung und Finanzentwicklung.
import { api } from './client.ts'

/** Zeitraum der Auswertung; leer = letzte 12 Monate (Standard des Servers). */
export interface RangeQuery {
  von?: string
  bis?: string
  raster?: 'monat' | 'jahr'
}

export interface Bucket {
  start: string
  end: string
  label: string
}

export interface CountSeries {
  id: number | null
  name: string
  values: number[]
}

export interface MemberStats {
  von: string
  bis: string
  raster: 'monat' | 'jahr'
  earliest: string | null
  buckets: (Bucket & { count: number; entries: number; exits: number })[]
  summary: { start: number; end: number; entries: number; exits: number }
  types: CountSeries[]
  groups_title: string
  groups: CountSeries[]
  exit_reasons: { reason: string; label: string; count: number }[]
  ages: {
    groups: string[]
    start_on?: string
    start: number[]
    end: number[]
    start_summary?: AgeSummary
    end_summary?: AgeSummary
  }
}

/** Durchschnittsalter und Standardabweichung der Mitglieder mit Geburtsdatum */
export interface AgeSummary {
  count: number
  mean: number | null
  sd: number | null
}

export interface FinanceStats {
  von: string
  bis: string
  raster: 'monat' | 'jahr'
  earliest: string | null
  previous: { von: string; bis: string }
  buckets: (Bucket & {
    income: string
    expense: string
    result: string
    /** null, solange es noch kein Konto gibt */
    balance: string | null
  })[]
  accounts: {
    id: number
    name: string
    kind_label: string
    is_active: boolean
    start: string | null
    values: (string | null)[]
  }[]
  categories: {
    id: number
    name: string
    income: string
    expense: string
    previous_income: string
    previous_expense: string
  }[]
  summary: {
    income: string
    expense: string
    result: string
    previous_income: string
    previous_expense: string
    previous_result: string
    balance_start: string
    balance_end: string
  }
}

export function rangeQuery(q: RangeQuery): string {
  const p = new URLSearchParams()
  if (q.von) p.set('von', q.von)
  if (q.bis) p.set('bis', q.bis)
  if (q.raster) p.set('raster', q.raster)
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const statsApi = {
  club: (org: number, q: RangeQuery) =>
    api.get<MemberStats>(`/api/orgs/${org}/members/statistics/${rangeQuery(q)}`),
  federation: (org: number, q: RangeQuery) =>
    api.get<MemberStats>(`/api/orgs/${org}/federation/statistics/${rangeQuery(q)}`),
  dept: (dept: number, q: RangeQuery) =>
    api.get<MemberStats>(`/api/depts/${dept}/statistics/${rangeQuery(q)}`),
  finance: (org: number, q: RangeQuery) =>
    api.get<FinanceStats>(`/api/orgs/${org}/finance/statistics/${rangeQuery(q)}`),
}
