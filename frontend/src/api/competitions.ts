// Wettbewerbe: eigene Schießen mit Einzel- und Zugwertung, Stechen und Auswertung.
import { api } from './client.ts'

export type CompetitionStatus = 'vorbereitung' | 'laeuft' | 'vorlaeufig' | 'endgueltig'
export type WebsiteMode = 'aus' | 'live' | 'abschluss'

export const STATUS_LABELS: Record<CompetitionStatus, string> = {
  vorbereitung: 'Vorbereitung',
  laeuft: 'läuft',
  vorlaeufig: 'vorläufig',
  endgueltig: 'endgültig',
}

export const WEBSITE_LABELS: Record<WebsiteMode, string> = {
  aus: 'nicht auf der Webseite',
  live: 'live während des Wettbewerbs',
  abschluss: 'nach Abschluss',
}

export interface Detail {
  label: string
  value: string
}

export interface Competition {
  id: number
  title: string
  occasion: string
  discipline: string
  location: string
  date: string
  description: string
  details: Detail[]
  status: CompetitionStatus
  status_label: string
  website: WebsiteMode
  starter_count: number
}

export type ScoringKind = 'einzel' | 'einheit'
export type TeamMode = 'beste' | 'summe' | 'durchschnitt'

export interface Scoring {
  id: number
  competition: number
  name: string
  kind: ScoringKind
  sort_order: number
  shots: number | null
  counted_shots: number | null
  max_per_shot: string | null
  unit_label: string
  decimals: number
  higher_better: boolean
  source: number | null
  team_mode: TeamMode
  team_size: number | null
  prize_places: number
  shootoff_shots: number | null
  shootoff_counted: number | null
}

export interface CompetitionDetail extends Competition {
  scorings: Scoring[]
  units: { id: number; name: string }[]
  can_manage: boolean
}

export interface Starter {
  id: number
  name: string
  club: string
  guest: boolean
  membership: number | null
  unit: number | null
  unit_name: string
  number: string
  out_of_competition: boolean
  /** Werte je Wertung (Nummer der Wertung → Wert als Text) */
  values: Record<string, string>
}

export interface MemberChoice {
  membership: number
  name: string
  birth_year: number | null
  unit: number | null
  unit_name: string
}

export interface StandingRow {
  key: string
  place: number | null
  name: string
  value: string | null
  value_text: string
  shootoff?: Record<string, string>
  tie?: boolean
  prize?: boolean
  // Einzel
  starter?: number
  club?: string
  unit?: number | null
  unit_name?: string
  guest?: boolean
  out_of_competition?: boolean
  // Untereinheit
  count?: number
  best?: string
  reason?: string
}

export interface OpenTie {
  keys: string[]
  names: string[]
  place: number
  /** Nr. eines angelegten Stechens, in dem noch Werte fehlen; null: Stechen nötig */
  shootoff: number | null
}

export interface StandingBlock {
  scoring: number
  name: string
  kind: ScoringKind
  rows: StandingRow[]
  open: OpenTie[]
  without_value: { key: string; name: string }[]
}

export interface Stats {
  scoring: number
  count: number
  members: number
  guests: number
  registered: number
  average: string
  max: string
  min: string
  full: number
  per_unit: {
    unit: number
    name: string
    count: number
    members: number
    participation: number | null
    average: string
    best: string
  }[]
}

export interface Standings {
  scorings: StandingBlock[]
  open_shootoffs: number
  stats: Stats | Record<string, never>
  status: CompetitionStatus
}

export interface ShootOffEntry {
  id: number
  key: string
  starter: number | null
  unit: number | null
  membership: number | null
  name: string
  value: string | null
}

export interface ShootOff {
  id: number
  scoring: number
  number: number
  shots: number | null
  counted_shots: number | null
  entries: ShootOffEntry[]
}

/** Eine Eingabe aus dem Standmodus, die (auch ohne Netz) gesammelt und nachgereicht wird. */
export type SyncOp =
  | {
      op: 'starter'
      client_key: string
      membership?: number
      name?: string
      club?: string
      unit?: number | null
    }
  | {
      op: 'starter_update'
      starter: number | string
      unit?: number | null
      number?: string
      out_of_competition?: boolean
    }
  | { op: 'score'; starter: number | string; scoring: number; value: string | null; at: string }

export interface SyncResult {
  results: ({ ok: true; starter?: number } | { ok: false; error: string })[]
  conflicts: { starter: number; name: string; scoring: number; value: string }[]
  keys: Record<string, number>
  starters: Starter[]
}

const base = (org: number) => `/api/orgs/${org}/competitions/`
const c = (org: number, id: number) => `${base(org)}${id}/`

export const competitionsApi = {
  list: (org: number) => api.get<Competition[]>(base(org)),
  get: (org: number, id: number) => api.get<CompetitionDetail>(c(org, id)),
  create: (org: number, data: Partial<Competition> & { template?: string }) =>
    api.post<Competition>(base(org), data),
  update: (org: number, id: number, data: Partial<Competition>) =>
    api.patch<Competition>(c(org, id), data),
  remove: (org: number, id: number) => api.del(c(org, id)),
  copy: (org: number, id: number) => api.post<{ id: number }>(`${c(org, id)}copy/`, {}),
  setStatus: (org: number, id: number, status: CompetitionStatus) =>
    api.post<{ status: CompetitionStatus; status_label: string }>(`${c(org, id)}status/`, {
      status,
    }),
  createScoring: (org: number, id: number, data: Partial<Scoring>) =>
    api.post<Scoring>(`${c(org, id)}scorings/`, data),
  updateScoring: (org: number, id: number, scoring: number, data: Partial<Scoring>) =>
    api.patch<Scoring>(`${c(org, id)}scorings/${scoring}/`, data),
  removeScoring: (org: number, id: number, scoring: number) =>
    api.del(`${c(org, id)}scorings/${scoring}/`),
  starters: (org: number, id: number) => api.get<Starter[]>(`${c(org, id)}starters/`),
  addStarter: (
    org: number,
    id: number,
    data: { membership?: number; name?: string; club?: string; unit?: number | null },
  ) => api.post<Starter>(`${c(org, id)}starters/`, data),
  updateStarter: (org: number, id: number, starter: number, data: Partial<Starter>) =>
    api.patch<Starter>(`${c(org, id)}starters/${starter}/`, data),
  removeStarter: (org: number, id: number, starter: number) =>
    api.del(`${c(org, id)}starters/${starter}/`),
  setScore: (org: number, id: number, starter: number, scoring: number, value: string | null) =>
    api.put<{ value: string | null }>(`${c(org, id)}scores/`, { starter, scoring, value }),
  members: (org: number, id: number) => api.get<MemberChoice[]>(`${c(org, id)}members/`),
  unitMembers: (org: number, id: number, unit: number) =>
    api.get<{ membership: number; name: string }[]>(`${c(org, id)}unit-members/?unit=${unit}`),
  standings: (org: number, id: number) => api.get<Standings>(`${c(org, id)}standings/`),
  shootoffs: (org: number, id: number) => api.get<ShootOff[]>(`${c(org, id)}shootoffs/`),
  createShootoff: (org: number, id: number, scoring: number, keys: string[]) =>
    api.post<ShootOff>(`${c(org, id)}shootoffs/`, { scoring, keys }),
  removeShootoff: (org: number, id: number, so: number) => api.del(`${c(org, id)}shootoffs/${so}/`),
  updateShootoffEntry: (
    org: number,
    id: number,
    entry: number,
    data: { value?: string | null; membership?: number | null; name?: string },
  ) => api.patch<ShootOff>(`${c(org, id)}shootoff-entries/${entry}/`, data),
  sync: (org: number, id: number, ops: SyncOp[]) =>
    api.post<SyncResult>(`${c(org, id)}sync/`, { ops }),
  exportUrl: (org: number, id: number, query: string) => `${c(org, id)}export/?${query}`,
}

/** Wert im Format der Wertung anzeigen (Komma statt Punkt, ohne überflüssige Nullen). */
export function showValue(raw: string | null | undefined, decimals = 0): string {
  if (raw === null || raw === undefined || raw === '') return ''
  const n = Number(raw)
  if (!Number.isFinite(n)) return raw
  return n.toFixed(decimals).replace('.', ',')
}

/** Suche, die „muel“ auch „Müller“ finden lässt. */
export function foldName(text: string): string {
  return text
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
}
