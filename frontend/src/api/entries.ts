// Meldungen: Ausschreibungen erfassen, Mannschaften und Personen melden, Fassungen.
import { api } from './client.ts'

export type BlockKind = 'mannschaften' | 'personen' | 'zahl' | 'auswahl' | 'text'
export type EntryStatus = 'entwurf' | 'abgegeben' | 'bestaetigt' | 'zurueckgezogen'
export type Channel = 'brief' | 'email' | 'tabelle' | 'sonstiges'
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
  zurueckgezogen: 'zurückgezogen',
}

export const CHANNEL_LABELS: Record<Channel, string> = {
  brief: 'Brief (PDF auf dem Briefbogen)',
  email: 'E-Mail an den Veranstalter',
  tabelle: 'Tabelle (Excel/CSV, z. B. für ein Portal)',
  sonstiges: 'sonstiger Weg (nur vermerken)',
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
  entry_status: EntryStatus | null
  entry_changed: boolean
}

export interface CallDetail extends Call {
  blocks: CallBlock[]
  has_versions: boolean
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

const base = (org: number) => `/api/orgs/${org}/entries/`
const c = (org: number, id: number) => `${base(org)}calls/${id}/`
const e = (org: number, id: number) => `${c(org, id)}entry/`

export const entriesApi = {
  options: (org: number) => api.get<EntryOptions>(`${base(org)}options/`),
  list: (org: number) => api.get<Call[]>(`${base(org)}calls/`),
  get: (org: number, id: number) => api.get<CallDetail>(c(org, id)),
  create: (org: number, data: Partial<Call> & { template?: string }) =>
    api.post<CallDetail>(`${base(org)}calls/`, data),
  update: (org: number, id: number, data: Partial<Call>) => api.patch<CallDetail>(c(org, id), data),
  remove: (org: number, id: number) => api.del(c(org, id)),
  copy: (org: number, id: number) => api.post<CallDetail>(`${c(org, id)}copy/`, {}),
  addBlock: (org: number, id: number, data: Partial<CallBlock>) =>
    api.post<CallBlock>(`${c(org, id)}blocks/`, data),
  updateBlock: (org: number, id: number, block: number, data: Partial<CallBlock>) =>
    api.patch<CallBlock>(`${c(org, id)}blocks/${block}/`, data),
  removeBlock: (org: number, id: number, block: number) => api.del(`${c(org, id)}blocks/${block}/`),
  candidates: (org: number, id: number, term: string, all = false) =>
    api.get<Candidate[]>(
      `${c(org, id)}candidates/?suche=${encodeURIComponent(term)}${all ? '&alle=1' : ''}`,
    ),
  entry: (org: number, id: number) => api.get<Entry | null>(e(org, id)),
  createEntry: (org: number, id: number) => api.post<Entry>(e(org, id), {}),
  updateEntry: (org: number, id: number, data: { note: string }) =>
    api.patch<Entry>(e(org, id), data),
  discard: (org: number, id: number) => api.del(`${e(org, id)}discard/`),
  addTeam: (org: number, id: number, block: number, name = '') =>
    api.post<Entry>(`${e(org, id)}teams/`, { block, name }),
  updateTeam: (org: number, id: number, team: number, data: Partial<EntryTeam>) =>
    api.patch<Entry>(`${e(org, id)}teams/${team}/`, data),
  removeTeam: (org: number, id: number, team: number) =>
    api.del(`${e(org, id)}teams/${team}/`) as Promise<Entry>,
  addPerson: (
    org: number,
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
    org: number,
    id: number,
    person: number,
    data: Partial<Omit<EntryPerson, 'membership'>> & { membership?: number },
  ) => api.patch<Entry>(`${e(org, id)}persons/${person}/`, data),
  removePerson: (org: number, id: number, person: number) =>
    api.del(`${e(org, id)}persons/${person}/`) as Promise<Entry>,
  answer: (org: number, id: number, block: number, value: unknown) =>
    api.put<Entry>(`${e(org, id)}answers/`, { block, value }),
  submit: (
    org: number,
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
  confirm: (org: number, id: number, note: string) =>
    api.post<Entry>(`${e(org, id)}confirm/`, { note }),
  unconfirm: (org: number, id: number) => api.del(`${e(org, id)}confirm/`) as Promise<Entry>,
  previewUrl: (org: number, id: number, fmt: 'pdf' | 'xlsx' | 'csv') =>
    `${e(org, id)}preview/?als=${fmt}`,
  versionUrl: (org: number, id: number, number: number, fmt: 'pdf' | 'xlsx' | 'csv') =>
    `${e(org, id)}versions/${number}/?als=${fmt}`,
}
