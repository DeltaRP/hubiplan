// Terminkalender: gleiche Schnittstelle für Vorstand, Abteilung und Mitgliederbereich.
import { api } from './client.ts'

export type Visibility = 'public' | 'members' | 'board'
export type Repeat = 'none' | 'weekly' | 'monthly' | 'yearly'

export interface EventCategory {
  id: number
  name: string
  color: string
  is_active?: boolean
}

export interface Occurrence {
  key: string
  event_id: number
  title: string
  starts_at: string
  ends_at: string
  original_start: string
  all_day: boolean
  location: string
  address: string
  category: EventCategory | null
  visibility: Visibility
  is_cancelled: boolean
  note: string
  is_moved: boolean
  is_series: boolean
  changed_at: string | null
  owner: string
  level: 'federation' | 'club' | 'department'
  department_id: number | null
  own: boolean
  can_edit: boolean
  rsvp_enabled: boolean
  /** Nur im Mitgliederbereich: eigene Rückmeldung (null = noch offen) */
  my_response?: ResponseStatus | null
}

export type ResponseStatus = 'yes' | 'no'

export interface MyResponse {
  status: ResponseStatus
  guests: number
  note: string
  source: 'member' | 'board'
  updated_at: string
}

export interface RsvpInfo {
  enabled: boolean
  deadline: string | null
  capacity: number | null
  guests_allowed: boolean
  max_guests: number
  free?: number
  mine?: MyResponse | null
  can_respond?: boolean
  reason?: string
  can_view_list?: boolean
  can_enter?: boolean
  summary?: { yes: number; no: number; guests: number; persons: number }
}

export interface ResponseRow {
  membership_id: number
  name: string
  club_number: string
  departments: string
  status: ResponseStatus | null
  guests: number
  note: string
  source: 'member' | 'board' | null
  updated_at: string | null
}

export interface ResponseList {
  event_id: number
  scope: 'all' | 'department'
  summary: { yes: number; no: number; guests: number; persons: number; open: number }
  capacity: number | null
  items: ResponseRow[]
  open: { membership_id: number; name: string; departments: string }[]
}

export interface EventList {
  from: string
  to: string
  items: Occurrence[]
  can_manage: boolean
  rsvp_allowed?: boolean
  categories: EventCategory[]
}

export interface Attachment {
  id: number
  name: string
  size: number
  content_type: string
  url: string
}

export interface SeriesException {
  original_start: string
  is_cancelled: boolean
  starts_at: string | null
  ends_at: string | null
  note: string
}

export interface EventDetail {
  id: number
  title: string
  description: string
  location: string
  address: string
  category: EventCategory | null
  all_day: boolean
  starts_at: string
  ends_at: string
  visibility: Visibility
  visibility_label: string
  repeat: Repeat
  repeat_label: string
  repeat_interval: number
  repeat_until: string | null
  is_cancelled: boolean
  cancel_note: string
  changed_at: string | null
  owner: string
  level: string
  department_id: number | null
  can_edit: boolean
  attachments: Attachment[]
  exceptions: SeriesException[]
  rsvp: RsvpInfo
  /** Veranstaltungsfinanzen (nur mit Kassenrecht): zugeordnete Veranstaltung */
  project?: { id: number; name: string } | null
  can_link_project?: boolean
  remind_days?: number | null
  reminded_at?: string | null
  /** Weitergabe nach oben/unten: Angabe am Termin, null = Voreinstellung (nur Bearbeiter) */
  share_up?: boolean | null
  share_down?: boolean | null
  share_defaults?: { up: boolean; down: boolean }
}

export interface EventInput {
  title: string
  description: string
  location: string
  address: string
  category: number | null
  all_day: boolean
  starts_at: string
  ends_at: string
  visibility: Visibility
  repeat: Repeat
  repeat_interval: number
  repeat_until: string | null
  is_cancelled: boolean
  cancel_note: string
  rsvp_enabled: boolean
  rsvp_deadline: string | null
  rsvp_capacity: number | null
  rsvp_guests: boolean
  remind_days: number | null
  /** Weitergabe nach oben/unten; null = wie bei der Einheit voreingestellt */
  share_up?: boolean | null
  share_down?: boolean | null
  /** Eingeladene per E-Mail benachrichtigen */
  notify?: boolean
}

/** Voreinstellung, ob die eigenen Termine nach oben bzw. unten weitergegeben werden */
export interface Sharing {
  share_up: boolean
  share_down: boolean
  up_possible: boolean
  down_possible: boolean
  /** false: entscheidet die Einheit darüber (keine eigene Verwaltung des Kalenders) */
  editable: boolean
  /** Untereinheiten direkt darunter, über die dieser Kalender entscheidet */
  units: {
    id: number
    name: string
    share_up: boolean
    share_down: boolean
    has_children: boolean
    /** entscheidet selbst */
    own_admin: boolean
  }[]
}

export interface Publication {
  is_public: boolean
  ics_url: string | null
  json_url: string | null
}

export const VISIBILITY_LABELS: Record<Visibility, string> = {
  public: 'nach außen öffentlich',
  members: 'Mitglieder',
  board: 'nur Vorstand',
}

export const REPEAT_LABELS: Record<Repeat, string> = {
  none: 'einmalig',
  weekly: 'wöchentlich',
  monthly: 'monatlich',
  yearly: 'jährlich',
}

/** Basis-URL eines Kalenders, z. B. `/api/orgs/7/` oder `/api/depts/3/`. */
export type CalendarBase = string

export const calendarBase = {
  org: (id: number) => `/api/orgs/${id}/`,
  dept: (id: number) => `/api/depts/${id}/`,
  portal: (id: number) => `/api/portal/${id}/`,
}

export const eventApi = {
  list: (base: CalendarBase, from: string, to: string) =>
    api.get<EventList>(`${base}events/?from=${from}&to=${to}`),
  upcoming: (base: CalendarBase, from: string, to: string) =>
    api.get<EventList>(`${base}events/?from=${from}&to=${to}&upcoming=1`),
  get: (base: CalendarBase, id: number) => api.get<EventDetail>(`${base}events/${id}/`),
  create: (base: CalendarBase, data: EventInput) => api.post<EventDetail>(`${base}events/`, data),
  update: (base: CalendarBase, id: number, data: Partial<EventInput>) =>
    api.patch<EventDetail>(`${base}events/${id}/`, data),
  remove: (base: CalendarBase, id: number) => api.del(`${base}events/${id}/`),
  setProject: (base: CalendarBase, id: number, data: { project?: number | null; create?: true }) =>
    api.post<EventDetail>(`${base}events/${id}/project/`, data),
  notify: (base: CalendarBase, id: number, kind: 'change' | 'cancel') =>
    api.post(`${base}events/${id}/notify/`, { kind }),
  setOccurrence: (
    base: CalendarBase,
    id: number,
    data: {
      original_start: string
      is_cancelled?: boolean
      starts_at?: string | null
      ends_at?: string | null
      note?: string
    },
  ) => api.put<EventDetail>(`${base}events/${id}/occurrence/`, data),
  resetOccurrence: (base: CalendarBase, id: number, originalStart: string) =>
    api.delWith<EventDetail>(`${base}events/${id}/occurrence/`, { original_start: originalStart }),
  upload: (base: CalendarBase, id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<EventDetail>(`${base}events/${id}/attachments/`, form)
  },
  removeAttachment: (url: string) => api.del(url),
  categories: (base: CalendarBase) => api.get<EventCategory[]>(`${base}events/categories/`),
  createCategory: (base: CalendarBase, data: { name: string; color: string }) =>
    api.post<EventCategory>(`${base}events/categories/`, data),
  updateCategory: (base: CalendarBase, id: number, data: Partial<EventCategory>) =>
    api.patch<EventCategory>(`${base}events/categories/${id}/`, data),
  removeCategory: (base: CalendarBase, id: number) => api.del(`${base}events/categories/${id}/`),
  publication: (base: CalendarBase) => api.get<Publication>(`${base}events/publication/`),
  sharing: (base: CalendarBase) => api.get<Sharing>(`${base}events/sharing/`),
  updateSharing: (
    base: CalendarBase,
    data: Partial<Pick<Sharing, 'share_up' | 'share_down'>> & {
      units?: { id: number; share_up?: boolean; share_down?: boolean }[]
    },
  ) => api.patch<Sharing>(`${base}events/sharing/`, data),
  publish: (base: CalendarBase, isPublic: boolean, renew = false) =>
    api.put<Publication>(`${base}events/publication/`, { is_public: isPublic, renew }),
  programUrl: (base: CalendarBase, year: number) => `${base}events/program/?year=${year}`,
  icsUrl: (base: CalendarBase, id: number) => `${base}events/${id}/ics/`,
  respond: (
    base: CalendarBase,
    id: number,
    data: { status: ResponseStatus; guests: number; note: string },
  ) => api.put<EventDetail>(`${base}events/${id}/response/`, data),
  withdraw: (base: CalendarBase, id: number) =>
    api.delWith<EventDetail>(`${base}events/${id}/response/`, {}),
  responses: (base: CalendarBase, id: number) =>
    api.get<ResponseList>(`${base}events/${id}/responses/`),
  enterResponse: (
    base: CalendarBase,
    id: number,
    data: { membership_id: number; status: ResponseStatus; guests: number; note: string },
  ) => api.put<MyResponse>(`${base}events/${id}/responses/`, data),
  removeResponse: (base: CalendarBase, id: number, membershipId: number) =>
    api.del(`${base}events/${id}/responses/${membershipId}/`),
  exportUrl: (base: CalendarBase, id: number, type: 'xlsx' | 'pdf') =>
    `${base}events/${id}/responses/export/?type=${type}`,
  feed: (base: CalendarBase) => api.get<{ ics_url: string | null }>(`${base}events/feed/`),
  renewFeed: (base: CalendarBase) => api.put<{ ics_url: string | null }>(`${base}events/feed/`, {}),
  removeFeed: (base: CalendarBase) =>
    api.delWith<{ ics_url: string | null }>(`${base}events/feed/`, {}),
}
