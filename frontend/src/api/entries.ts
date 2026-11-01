// Meldungen: Ausschreibungen erfassen, Mannschaften und Personen melden, Fassungen.
import type { CalendarAccess, CompetitionEvent } from './competitions.ts'
import { api } from './client.ts'

export type BlockKind = 'mannschaften' | 'personen' | 'zahl' | 'auswahl' | 'text'
export type EntryStatus = 'entwurf' | 'abgegeben' | 'bestaetigt' | 'rueckfrage' | 'zurueckgezogen'
export type Channel = 'brief' | 'email' | 'tabelle' | 'sonstiges' | 'hubiplan'
export type FeePer = 'mannschaft' | 'person' | 'pauschal'
export type ChangesAfterDeadline = 'keine' | 'ersatz' | 'frei'

export const BLOCK_LABELS: Record<BlockKind, string> = {
  mannschaften: 'Mannschaften',
  personen: 'Personenliste',
  zahl: 'Zahl',
  auswahl: 'Auswahl',
  text: 'Text',
}

export const STATUS_LABELS: Record<EntryStatus, string> = {
  entwurf: 'Entwurf',
  abgegeben: 'abgegeben',
  bestaetigt: 'bestätigt',
  rueckfrage: 'Rückfrage',
  zurueckgezogen: 'zurückgezogen',
}

export const CHANNEL_LABELS: Record<Channel, string> = {
  brief: 'Brief (PDF auf dem Briefbogen)',
  email: 'E-Mail an den Veranstalter',
  tabelle: 'Tabelle (Excel/CSV, z. B. für ein Portal)',
  sonstiges: 'sonstiger Weg (nur vermerken)',
  hubiplan: 'in HUBIplan',
}

export interface BlockSettings {
  min_teams?: number
  max_teams?: number
  min_size?: number
  max_size?: number
  substitutes?: number
  positions?: string[]
  min?: number
  max?: number
  options?: string[]
  multiple?: boolean
  multiline?: boolean
}

export interface CallBlock {
  id: number
  kind: BlockKind
  label: string
  help_text: string
  required: boolean
  settings: BlockSettings
  sort_order: number
}

export interface Conditions {
  active?: boolean
  min_age?: number
  max_age?: number
  member_types?: number[]
  units?: number[]
  one_team?: boolean
  guests?: boolean
}

export interface Call {
  id: number
  title: string
  organizer: string
  organizer_address: string
  organizer_email: string
  salutation: string
  description: string
  date: string | null
  location: string
  deadline: string | null
  reference_date: string | null
  person_fields: string[]
  conditions: Conditions
  fee_amount: string | null
  fee_per: FeePer
  changes_after_deadline: ChangesAfterDeadline
  create_competition: boolean
  copied_from: number | null
  event_id: number | null
  /** Ausschreibung an die eigenen Untereinheiten (Schritt 3) */
  internal: boolean
  units: number[]
  strict: boolean
  competition: number | null
  entry_question: string
  unit_counts?: { addressed: number; submitted: number }
  entry_status: EntryStatus | null
  entry_changed: boolean
}

export interface CallDetail extends Call {
  blocks: CallBlock[]
  has_versions: boolean
  /** Termin für die Interessenabfrage (Zusagen) */
  event: CompetitionEvent | null
  calendar: CalendarAccess
}

/** Termin zur Auswahl; ``call``: Titel einer anderen Ausschreibung mit diesem Termin */
export type CallEvent = CompetitionEvent & { call?: string | null }

export interface Interested {
  membership: number
  name: string
  unit_name: string
  birth_year: number | null
  note: string
  taken: boolean
}

/** Mitgliederbereich: wofür das Mitglied gemeldet ist */
export interface MyEntry {
  id: number
  title: string
  organizer: string
  date: string | null
  location: string
  event: number | null
  group: string
  position: string
  substitute: boolean
  confirmed: boolean
}

export interface EntryTeam {
  id: number
  block: number
  name: string
  sort_order: number
}

export interface EntryPerson {
  id: number
  block: number
  team: number | null
  membership: number | null
  name: string
  club: string
  guest: boolean
  position: string
  substitute: boolean
  sort_order: number
}

export interface Hint {
  text: string
  block: number | null
  person: number | null
  team: number | null
}

export interface EntryVersion {
  id: number
  number: number
  kind: 'meldung' | 'aenderung' | 'rueckzug'
  kind_label: string
  channel: Channel
  channel_label: string
  sent_to: string
  changes: string[]
  reason: string
  signed_by: string
  signed_function: string
  created_at: string
  shortened: boolean
}

export interface Entry {
  id: number
  call: number
  status: EntryStatus
  status_label: string
  changed: boolean
  note: string
  confirmed_note: string
  question: string
  unit: number | null
  unit_name: string
  competition: number | null
  teams: EntryTeam[]
  persons: EntryPerson[]
  answers: Record<string, unknown>
  hints: Hint[]
  versions: EntryVersion[]
  after_deadline: boolean
  can_pick_members: boolean
  competitions_enabled: boolean
}

export interface Candidate {
  membership: number
  name: string
  first_name: string
  last_name: string
  birth_year: number | null
  unit_name: string
  active: boolean
  taken: boolean
  /** Rückmeldung zum Termin der Ausschreibung */
  response: 'yes' | 'no' | null
}

/** Übersicht des Veranstalters je angeschriebener Untereinheit */
export interface UnitRow {
  unit: number
  name: string
  status: EntryStatus | null
  status_label: string
  changed: boolean
  question: string
  teams: number
  persons: number
  hints: number
  submitted_at: string | null
  contacts: number
}

export interface EntryOptions {
  person_fields: { key: string; label: string }[]
  member_types: { id: number; name: string }[]
  units: { id: number; name: string }[]
  unit_label: string
  signer: string
  functions: string[]
  competitions_enabled: boolean
}

/** Einheit (Nummer) oder fertige Adresse, z. B. Bereich einer Untereinheit
 * (``/api/depts/5/entries/``) oder Meldung einer Untereinheit beim Veranstalter
 * (``/api/orgs/7/entries/units/5/``). */
export type Scope = number | string

const base = (org: Scope) => (typeof org === 'string' ? org : `/api/orgs/${org}/entries/`)
export const unitScope = (org: Scope, unit: number): Scope =>
  `/api/orgs/${org}/entries/units/${unit}/`
export const deptScope = (dept: number): Scope => `/api/depts/${dept}/entries/`
const c = (org: Scope, id: number) => `${base(org)}calls/${id}/`
const e = (org: Scope, id: number) => `${c(org, id)}entry/`

export const entriesApi = {
  options: (org: Scope) => api.get<EntryOptions>(`${base(org)}options/`),
  list: (org: Scope) => api.get<Call[]>(`${base(org)}calls/`),
  get: (org: Scope, id: number) => api.get<CallDetail>(c(org, id)),
  create: (org: Scope, data: Partial<Call> & { template?: string }) =>
    api.post<CallDetail>(`${base(org)}calls/`, data),
  update: (org: Scope, id: number, data: Partial<Call>) => api.patch<CallDetail>(c(org, id), data),
  remove: (org: Scope, id: number) => api.del(c(org, id)),
  copy: (org: Scope, id: number) => api.post<CallDetail>(`${c(org, id)}copy/`, {}),
  addBlock: (org: Scope, id: number, data: Partial<CallBlock>) =>
    api.post<CallBlock>(`${c(org, id)}blocks/`, data),
  updateBlock: (org: Scope, id: number, block: number, data: Partial<CallBlock>) =>
    api.patch<CallBlock>(`${c(org, id)}blocks/${block}/`, data),
  removeBlock: (org: Scope, id: number, block: number) => api.del(`${c(org, id)}blocks/${block}/`),
  eventCandidates: (org: Scope, id: number, search = '') =>
    api.get<CalendarAccess & { events: CallEvent[] }>(
      `${c(org, id)}event-candidates/${search ? `?suche=${encodeURIComponent(search)}` : ''}`,
    ),
  setEvent: (org: Scope, id: number, data: { event: number | null } | { create: true }) =>
    api.post<CallDetail>(`${c(org, id)}event/`, data),
  responses: (org: Scope, id: number) =>
    api.get<{ yes: Interested[]; no_count: number }>(`${c(org, id)}responses/`),
  mine: (access: number) => api.get<MyEntry[]>(`/api/portal/${access}/entries/`),
  candidates: (org: Scope, id: number, term: string, all = false) =>
    api.get<Candidate[]>(
      `${c(org, id)}candidates/?suche=${encodeURIComponent(term)}${all ? '&alle=1' : ''}`,
    ),
  entry: (org: Scope, id: number) => api.get<Entry | null>(e(org, id)),
  createEntry: (org: Scope, id: number) => api.post<Entry>(e(org, id), {}),
  updateEntry: (org: Scope, id: number, data: { note: string }) =>
    api.patch<Entry>(e(org, id), data),
  discard: (org: Scope, id: number) => api.del(`${e(org, id)}discard/`),
  addTeam: (org: Scope, id: number, block: number, name = '') =>
    api.post<Entry>(`${e(org, id)}teams/`, { block, name }),
  updateTeam: (org: Scope, id: number, team: number, data: Partial<EntryTeam>) =>
    api.patch<Entry>(`${e(org, id)}teams/${team}/`, data),
  removeTeam: (org: Scope, id: number, team: number) =>
    api.del(`${e(org, id)}teams/${team}/`) as Promise<Entry>,
  addPerson: (
    org: Scope,
    id: number,
    data: {
      block: number
      team?: number | null
      membership?: number
      name?: string
      club?: string
      position?: string
      substitute?: boolean
    },
  ) => api.post<Entry>(`${e(org, id)}persons/`, data),
  updatePerson: (
    org: Scope,
    id: number,
    person: number,
    data: Partial<Omit<EntryPerson, 'membership'>> & { membership?: number },
  ) => api.patch<Entry>(`${e(org, id)}persons/${person}/`, data),
  removePerson: (org: Scope, id: number, person: number) =>
    api.del(`${e(org, id)}persons/${person}/`) as Promise<Entry>,
  answer: (org: Scope, id: number, block: number, value: unknown) =>
    api.put<Entry>(`${e(org, id)}answers/`, { block, value }),
  submit: (
    org: Scope,
    id: number,
    data: {
      channel: Channel
      email?: string
      sent_to?: string
      function?: string
      withdraw?: boolean
      reason?: string
    },
  ) => api.post<Entry>(`${e(org, id)}submit/`, data),
  returnEntry: (org: Scope, id: number, question: string) =>
    api.post<Entry>(`${e(org, id)}return/`, { question }),
  units: (org: number, id: number) => api.get<UnitRow[]>(`${c(org, id)}units/`),
  remind: (org: number, id: number, units?: number[]) =>
    api.post<{ reminded: string[]; without_contact: string[] }>(`${c(org, id)}remind/`, {
      units,
    }),
  unitsListUrl: (org: number, id: number, fmt: 'xlsx' | 'csv') => `${c(org, id)}list/?als=${fmt}`,
  confirm: (org: Scope, id: number, note: string) =>
    api.post<Entry>(`${e(org, id)}confirm/`, { note }),
  unconfirm: (org: Scope, id: number) => api.del(`${e(org, id)}confirm/`) as Promise<Entry>,
  previewUrl: (org: Scope, id: number, fmt: 'pdf' | 'xlsx' | 'csv') =>
    `${e(org, id)}preview/?als=${fmt}`,
  versionUrl: (org: Scope, id: number, number: number, fmt: 'pdf' | 'xlsx' | 'csv') =>
    `${e(org, id)}versions/${number}/?als=${fmt}`,
}
