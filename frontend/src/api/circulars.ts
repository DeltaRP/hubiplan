// Rundschreiben: Mails und Serienbriefe an ausgewählte Mitglieder.
import { api } from './client.ts'

/** Zugang: Vorstand einer Organisation oder Abteilungsrolle */
export type CircularBase = { org: number } | { dept: number }

export const circularBase = {
  org: (id: number): CircularBase => ({ org: id }),
  dept: (id: number): CircularBase => ({ dept: id }),
}

export function baseUrl(b: CircularBase): string {
  return 'org' in b ? `/api/orgs/${b.org}/circulars/` : `/api/depts/${b.dept}/circulars/`
}

export type CircularKind = 'info' | 'notice' | 'short'
export type Channel = 'app' | 'mail' | 'letter' | 'portal'
export type CircularAudience = 'members' | 'boards' | 'departments' | 'roles'
export type CircularStatus = 'draft' | 'sending' | 'sent'

export interface CircularFilters {
  member_types?: number[]
  departments?: number[]
  roles?: number[]
  club_roles?: number[]
  role_names?: string[]
  board?: boolean
  age_min?: number | null
  age_max?: number | null
  jubilee_year?: number | null
  clubs?: number[]
  reported?: boolean
  honorary_titles?: number[]
  include?: string[]
  exclude?: string[]
  /** Listen im Modus „nur ausgewählte“; leer heißt dort niemand statt alle. */
  selected?: (
    | 'member_types'
    | 'departments'
    | 'roles'
    | 'clubs'
    | 'honorary_titles'
    | 'role_names'
    | 'club_roles'
  )[]
}

export interface CircularSummary {
  id: number
  subject: string
  kind: CircularKind
  kind_label: string
  audience: CircularAudience
  status: CircularStatus
  status_label: string
  department: { id: number; name: string } | null
  created_by: string
  created_at: string
  updated_at: string
  sent_at: string | null
  sent_by: string
}

export interface CircularAttachment {
  id: number
  name: string
  size: number
  url: string
}

export interface SentCounts {
  app?: number
  mail: number
  portal?: number
  letter: number
  failed: number
  pending: number
  // Mails ohne Ergebnis nach 15 Minuten (z. B. Absturz mitten im Versand)
  unclear?: number
  /** An Mailserver bzw. App übergeben */
  sent?: number
}

export interface Circular extends CircularSummary {
  body: string
  reply_to: string
  via_app: boolean
  also_mail: boolean
  filters: CircularFilters
  /** An einen Verteiler: Empfänger aus dessen Auswahl */
  mailing_list?: number | null
  can_edit: boolean
  attachments: CircularAttachment[]
  counts: SentCounts | null
}

/** Listen der Empfängerauswahl, die „alle“ oder „nur ausgewählte“ kennen. */
export type SelectKey = NonNullable<CircularFilters['selected']>[number]

/** Listen im Modus „nur ausgewählte“ ohne Häkchen: dann geht die Nachricht an niemanden. */
export function emptySelections(filters: CircularFilters): SelectKey[] {
  return (filters.selected ?? []).filter((key) => (filters[key] ?? []).length === 0)
}

export interface CircularOptions {
  org_type: 'club' | 'federation'
  department: { id: number; name: string } | null
  kinds: { value: CircularKind; label: string }[]
  placeholders: { name: string; label: string }[]
  reply_to: string
  max_attachments: number
  max_attachment_mb: number
  max_short_body?: number
  /** Verteiler der Einheit; vorhanden: „An“ zeigt nur sie */
  lists?: { id: number; name: string; audience: CircularAudience }[]
  audiences?: { value: CircularAudience; label: string }[]
  clubs?: { id: number; name: string }[]
  member_types?: { id: number; name: string }[]
  honorary_titles?: { id: number; name: string }[]
  departments?: { id: number; name: string }[]
  roles?: { id: number; name: string; department: string }[]
  role_names?: string[]
  // Rollen des Vereins selbst (Empfängerkreis „roles“)
  club_roles?: { id: number; name: string; is_board: boolean }[]
}

export interface Candidate {
  key: string
  first_name: string
  last_name: string
  club: string
  email: string
  departments?: string[]
  channel: Channel | null
  note?: string
  excluded?: boolean
  included?: boolean
  opted_out?: boolean
  // nur im Versandprotokoll
  status?: string
  status_label?: string
  error?: string
  sent_at?: string | null
}

export interface RecipientCounts {
  total?: number
  app?: number
  mail: number
  portal?: number
  letter: number
  opted_out?: number
  excluded?: number
  failed?: number
  pending?: number
}

export interface Recipients {
  counts: RecipientCounts
  items: Candidate[]
}

export interface SearchHit {
  key: string
  first_name: string
  last_name: string
  club: string
}

export interface CircularTemplate {
  id: number
  name: string
  kind: CircularKind
  subject: string
  body: string
}

export type CircularChanges = Partial<
  Pick<
    Circular,
    | 'kind'
    | 'audience'
    | 'subject'
    | 'body'
    | 'reply_to'
    | 'via_app'
    | 'also_mail'
    | 'filters'
    | 'mailing_list'
  >
>

export const circularApi = {
  options: (b: CircularBase) => api.get<CircularOptions>(`${baseUrl(b)}options/`),
  list: (b: CircularBase) => api.get<CircularSummary[]>(baseUrl(b)),
  create: (b: CircularBase, data: CircularChanges & { template?: number; copy_of?: number } = {}) =>
    api.post<Circular>(baseUrl(b), data),
  get: (b: CircularBase, id: number) => api.get<Circular>(`${baseUrl(b)}${id}/`),
  update: (b: CircularBase, id: number, data: CircularChanges) =>
    api.patch<Circular>(`${baseUrl(b)}${id}/`, data),
  remove: (b: CircularBase, id: number) => api.del(`${baseUrl(b)}${id}/`),
  recipients: (b: CircularBase, id: number) =>
    api.get<Recipients>(`${baseUrl(b)}${id}/recipients/`),
  search: (b: CircularBase, id: number, q: string) =>
    api.get<SearchHit[]>(`${baseUrl(b)}${id}/search/?suche=${encodeURIComponent(q)}`),
  send: (b: CircularBase, id: number) =>
    api.post<Circular & { sent: Record<Channel, number> }>(`${baseUrl(b)}${id}/send/`),
  test: (b: CircularBase, id: number) => api.post<{ sent_to: string }>(`${baseUrl(b)}${id}/test/`),
  resend: (b: CircularBase, id: number) =>
    api.post<Circular & { resent: number }>(`${baseUrl(b)}${id}/resend/`),
  lettersUrl: (b: CircularBase, id: number, preview = false) =>
    `${baseUrl(b)}${id}/letters/${preview ? '?vorschau=1' : ''}`,
  upload: (b: CircularBase, id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<Circular>(`${baseUrl(b)}${id}/attachments/`, form)
  },
  removeAttachment: (b: CircularBase, id: number, att: number) =>
    api.del(`${baseUrl(b)}${id}/attachments/${att}/`),
  templates: (b: CircularBase) => api.get<CircularTemplate[]>(`${baseUrl(b)}templates/`),
  saveTemplate: (b: CircularBase, data: Omit<CircularTemplate, 'id'>) =>
    api.post<CircularTemplate>(`${baseUrl(b)}templates/`, data),
  removeTemplate: (b: CircularBase, id: number) => api.del(`${baseUrl(b)}templates/${id}/`),
}

export interface ReceivedCircular {
  id: number
  subject: string
  sender: string
  kind_label: string
  sent_at: string
  channel: Channel
  body?: string
  attachments?: CircularAttachment[]
}

export interface OptOutState {
  info_opt_out: boolean
  since?: string | null
}

export const portalCircularApi = {
  list: (access: number) => api.get<ReceivedCircular[]>(`/api/portal/${access}/circulars/`),
  get: (access: number, id: number) =>
    api.get<ReceivedCircular>(`/api/portal/${access}/circulars/${id}/`),
  settings: (access: number) => api.get<OptOutState>(`/api/portal/${access}/circulars/settings/`),
  setOptOut: (access: number, value: boolean) =>
    api.put<OptOutState>(`/api/portal/${access}/circulars/settings/`, { info_opt_out: value }),
}

export interface PublicOptOut {
  club: string
  first_name: string
  info_opt_out: boolean
  imprint_key?: string
}

export const publicOptOutApi = {
  get: (token: string) => api.get<PublicOptOut>(`/api/public/circulars/optout/${token}/`),
  set: (token: string, value: boolean) =>
    api.post<PublicOptOut>(`/api/public/circulars/optout/${token}/`, { info_opt_out: value }),
}

export const receivedApi = {
  list: (org: number) => api.get<ReceivedCircular[]>(`/api/orgs/${org}/circulars/received/`),
  get: (org: number, id: number) =>
    api.get<ReceivedCircular>(`/api/orgs/${org}/circulars/received/${id}/`),
}

/** Versandweg in Worten */
export const channelLabel: Record<Channel, string> = {
  app: 'App',
  mail: 'E-Mail',
  letter: 'Brief',
  portal: 'nur Mitgliederbereich',
}

// --- Mailverteiler: Rundschreiben aus dem eigenen Mailprogramm ---

export type MailingListMode = 'confirm' | 'draft' | 'direct'

export interface InboundEntry {
  id: number
  received_at: string
  sender: string
  subject: string
  status: 'rejected' | 'waiting' | 'draft' | 'sent' | 'failed'
  status_label: string
  reason: string
  circular_id: number | null
  /** nur beim Probe-Eingang */
  confirm_url?: string
}

export interface MailingList {
  id: number
  name: string
  local_part: string
  address: string
  /** Weitere Adressen (Teil vor dem @) und die vollen Adressen dazu */
  aliases: string[]
  alias_addresses: string[]
  mode: MailingListMode
  mode_label: string
  is_active: boolean
  department: { id: number; name: string } | null
  pattern_id: number
  kind: CircularKind
  kind_label: string
  audience: CircularAudience
  /** Jeder darf schreiben, auch ohne Konto (ohne Bestätigung) */
  open_senders?: boolean
  /** Ausgewählte Absender (Konto-IDs); leer: alle mit dem Recht */
  senders: number[]
  /** nur in der Einzelansicht: wer das Recht hat und ausgewählt werden kann */
  sender_options?: { id: number; name: string; email: string }[]
  last_inbound: InboundEntry | null
  /** nur in der Übersicht: Zahl der Empfänger nach der aktuellen Auswahl */
  recipients?: number
}

export interface MailingListSettings {
  /** Domain der Verteiler-Adressen (leer: nicht eingerichtet) */
  domain: string
  /** Sammelpostfach eingerichtet: echte Mails kommen an */
  receiving: boolean
  /** Probe-Eingang aus der Oberfläche möglich */
  simulation: boolean
}

export type MailingListChanges = Partial<
  Pick<
    MailingList,
    'name' | 'local_part' | 'aliases' | 'mode' | 'is_active' | 'open_senders' | 'senders'
  >
>

export const mailingListApi = {
  list: (b: CircularBase) =>
    api.get<{ settings: MailingListSettings; items: MailingList[] }>(`${baseUrl(b)}lists/`),
  create: (b: CircularBase, data: MailingListChanges) =>
    api.post<MailingList>(`${baseUrl(b)}lists/`, data),
  get: (b: CircularBase, id: number) => api.get<MailingList>(`${baseUrl(b)}lists/${id}/`),
  update: (b: CircularBase, id: number, data: MailingListChanges) =>
    api.patch<MailingList>(`${baseUrl(b)}lists/${id}/`, data),
  remove: (b: CircularBase, id: number) => api.del(`${baseUrl(b)}lists/${id}/`),
  inbound: (b: CircularBase, id: number) =>
    api.get<InboundEntry[]>(`${baseUrl(b)}lists/${id}/inbound/`),
  probe: (b: CircularBase, id: number, data: { subject: string; body: string }) =>
    api.post<InboundEntry>(`${baseUrl(b)}lists/${id}/probe/`, data),
}

export interface PublicConfirm {
  status: InboundEntry['status']
  status_label: string
  subject: string
  list: string
  address: string
  organization: string
  body: string
  attachments: string[]
  counts: RecipientCounts | SentCounts | null
}

export const publicConfirmApi = {
  get: (token: string) => api.get<PublicConfirm>(`/api/public/circulars/confirm/${token}/`),
  act: (token: string, action: 'send' | 'discard') =>
    api.post<PublicConfirm>(`/api/public/circulars/confirm/${token}/`, { action }),
}
