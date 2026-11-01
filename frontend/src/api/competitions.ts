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

export type CompetitionForm = 'rangliste' | 'vogel'

export interface Competition {
  id: number
  title: string
  form: CompetitionForm
  /** false: fremder Wettbewerb (ein anderer richtet aus) */
  own: boolean
  organizer: string
  occasion: string
  discipline: string
  location: string
  date: string
  description: string
  details: Detail[]
  status: CompetitionStatus
  status_label: string
  website: WebsiteMode
  drop_out: boolean
  fixed_order: boolean
  total_shots: number | null
  /** zugeordneter Termin im Kalender */
  event: number | null
  starter_count: number
}

/** Termin im Kalender, wie ihn ein Wettbewerb sieht */
export interface CompetitionEvent {
  id: number
  title: string
  date: string
  /** Beginn (HH:MM); leer bei ganztägigen Terminen */
  time: string | null
  location: string
  unit_name: string
  is_cancelled: boolean
  rsvp_enabled: boolean
  yes_count: number
  /** Titel des Wettbewerbs, dem der Termin schon zugeordnet ist */
  competition?: string | null
}

export interface CalendarAccess {
  on: boolean
  can_create: boolean
}

export type ScoringKind = 'einzel' | 'einheit' | 'mannschaft'
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
  field_size: number | null
}

export interface PrizeSetup {
  id: number
  name: string
  award: string
  sort_order: number
}

export interface CompetitionDetail extends Competition {
  scorings: Scoring[]
  units: { id: number; name: string }[]
  prizes: PrizeSetup[]
  can_manage: boolean
  event_info?: CompetitionEvent | null
  calendar?: CalendarAccess
  /** nur über einen Standzugang */
  stand_access?: { label: string; expires_at: string }
}

export type Presence = '' | 'fehlt' | 'zurueckgezogen'

export const PRESENCE_LABELS: Record<Presence, string> = {
  '': 'dabei',
  fehlt: 'fehlt kurz',
  zurueckgezogen: 'zurückgezogen',
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
  presence: Presence
  drawn_how: string
  /** Gerätekennung, wenn im Standmodus angelegt (bleibt nach dem Abgleich gleich) */
  key?: string | null
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
  // fremder Wettbewerb
  team?: number
  members?: string[]
  note?: string
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
  field_size?: number | null
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

export interface BirdPrize {
  id: number
  name: string
  sort_order: number
  award: string
  fallen: boolean
  winner: number | null
  winner_name: string
  unit_name: string
  club: string
  number: string
  shot_number: number | null
  shots_for: number | null
  live: boolean
  fallen_at: string | null
}

export interface BirdShot {
  number: number
  starter: number | null
  client_key: string | null
}

export interface BirdState {
  prizes: BirdPrize[]
  order: number[]
  upcoming: number[]
  shots: number
  live_shots: number
  since_last: number
  round: number
  last: {
    number: number
    starter: number | null
    name: string
    client_key: string | null
    hits: number[]
  } | null
  recent: BirdShot[]
  draw: { missing: string[]; duplicates: { number: number; names: string[] }[]; gaps: number[] }
  stats: {
    shots: number
    starters: number
    members: number
    guests: number
    rounds: number | null
    duration_minutes: number | null
    started: string | null
    per_unit: { name: string; count: number }[]
  }
}

export interface Standings {
  scorings: StandingBlock[]
  open_shootoffs: number
  stats: Stats | Record<string, never>
  status: CompetitionStatus
  bird?: BirdState
}

export interface Team {
  id: number
  name: string
  sort_order: number
  members: number[]
}

export interface StandAccessInfo {
  id: number
  label: string
  expires_at: string
  active: boolean
  created_at: string
  token?: string
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
      presence?: Presence
    }
  | { op: 'starter_delete'; starter: number | string }
  | { op: 'score'; starter: number | string; scoring: number; value: string | null; at: string }
  | { op: 'shot'; starter: number | string; hits: number[]; client_key: string; at: string }
  | { op: 'undo'; client_key: string | null }
  | { op: 'draw'; starter: number | string; number: number | null; how: 'hut' | 'digital' }

export interface SyncResult {
  results: ({ ok: true; starter?: number } | { ok: false; error: string })[]
  conflicts: {
    starter: number
    name: string
    scoring?: number
    value?: string
    number?: number
    note?: string
  }[]
  keys: Record<string, number>
  starters: Starter[]
  status: CompetitionStatus
  bird?: BirdState
}

const base = (org: number) => `/api/orgs/${org}/competitions/`
const c = (org: number, id: number) => `${base(org)}${id}/`

export const competitionsApi = {
  list: (org: number) => api.get<Competition[]>(base(org)),
  get: (org: number, id: number) => api.get<CompetitionDetail>(c(org, id)),
  create: (
    org: number,
    data: Partial<Competition> & { template?: string; create_event?: boolean },
  ) => api.post<Competition>(base(org), data),
  eventCandidates: (org: number, search = '') =>
    api.get<CalendarAccess & { events: CompetitionEvent[] }>(
      `${base(org)}event-candidates/${search ? `?suche=${encodeURIComponent(search)}` : ''}`,
    ),
  setEvent: (org: number, id: number, data: { event: number | null } | { create: true }) =>
    api.post<{ event: CompetitionEvent | null; location: string; description: string }>(
      `${c(org, id)}event/`,
      data,
    ),
  startersFromEvent: (org: number, id: number) =>
    api.post<{ added: number; already: number }>(`${c(org, id)}starters/from-event/`, {}),
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
  // Vogelschießen
  bird: (org: number, id: number) => api.get<BirdState>(`${c(org, id)}bird/`),
  addPrize: (org: number, id: number, name: string) =>
    api.post<BirdState>(`${c(org, id)}prizes/`, { name }),
  updatePrize: (
    org: number,
    id: number,
    prize: number,
    data: Partial<{
      name: string
      award: string
      sort_order: number
      winner: number | null
      shot_number: number | null
      shots_for: number | null
    }>,
  ) => api.patch<BirdState>(`${c(org, id)}prizes/${prize}/`, data),
  removePrize: (org: number, id: number, prize: number) => api.del(`${c(org, id)}prizes/${prize}/`),
  draw: (org: number, id: number, starter: number, number: number | null) =>
    api.post<{ number: number; note: string; state: BirdState }>(`${c(org, id)}draw/`, {
      starter,
      number,
    }),
  drawAll: (org: number, id: number) =>
    api.post<{ count: number; state: BirdState }>(`${c(org, id)}draw-all/`, {}),
  // Fremde Wettbewerbe
  teams: (org: number, id: number) => api.get<Team[]>(`${c(org, id)}teams/`),
  addTeam: (org: number, id: number, name = '') => api.post<Team>(`${c(org, id)}teams/`, { name }),
  updateTeam: (org: number, id: number, team: number, data: Partial<Team>) =>
    api.patch<Team>(`${c(org, id)}teams/${team}/`, data),
  removeTeam: (org: number, id: number, team: number) => api.del(`${c(org, id)}teams/${team}/`),
  setPlacing: (
    org: number,
    id: number,
    data: {
      scoring: number
      starter?: number
      team?: number
      place: string
      value: string
      note: string
    },
  ) => api.put<{ place: number | null }>(`${c(org, id)}placings/`, data),
  // Standzugang
  standAccesses: (org: number, id: number) =>
    api.get<StandAccessInfo[]>(`${c(org, id)}stand-access/`),
  createStandAccess: (org: number, id: number, label: string) =>
    api.post<StandAccessInfo>(`${c(org, id)}stand-access/`, { label }),
  revokeStandAccess: (org: number, id: number, access: number) =>
    api.del(`${c(org, id)}stand-access/${access}/`),
}

/** Was der Standmodus vom Server braucht: angemeldet oder über einen Standzugang. */
export interface StandApi {
  /** Schlüssel für den Speicher auf dem Gerät */
  key: string
  get: () => Promise<CompetitionDetail>
  starters: () => Promise<Starter[]>
  members: () => Promise<MemberChoice[]>
  sync: (ops: SyncOp[]) => Promise<SyncResult>
  /** endgültig abschließen (nur angemeldet mit „Wettbewerbe verwalten“, nicht per Standzugang) */
  finish?: () => Promise<unknown>
}

export function orgStandApi(org: number, id: number): StandApi {
  return {
    key: `${org}.${id}`,
    get: () => competitionsApi.get(org, id),
    starters: () => competitionsApi.starters(org, id),
    members: () => competitionsApi.members(org, id),
    sync: (ops) => competitionsApi.sync(org, id, ops),
    finish: () => competitionsApi.setStatus(org, id, 'endgueltig'),
  }
}

export function tokenStandApi(token: string): StandApi {
  const b = `/api/public/stand/${encodeURIComponent(token)}/`
  return {
    key: `zugang.${token.slice(0, 12)}`,
    get: () => api.get<CompetitionDetail>(b),
    starters: () => api.get<Starter[]>(`${b}starters/`),
    members: () => api.get<MemberChoice[]>(`${b}members/`),
    sync: (ops) => api.post<SyncResult>(`${b}sync/`, { ops }),
  }
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
