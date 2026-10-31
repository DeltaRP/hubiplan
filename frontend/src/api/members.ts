// Mitgliederverwaltung: Liste, Aufnahme, Akte, Mitgliedsarten.
import { api, requestBlob } from './client.ts'
import type { AuditEntry } from './orgs.ts'
import type { DatePrecision } from '../components/forms.ts'

/** Ob eine Mitgliedsart gelöscht werden kann oder nur archiviert, und warum. */
export interface TypeUsage {
  deletable: boolean
  reasons: string[]
  is_archived: boolean
}

export interface MemberType {
  id: number
  name: string
  reported: boolean
  active: boolean
  counts_for_duration: boolean
  is_archived: boolean
  sort_order: number
  in_use: boolean
}

export type HonoraryFeeMode = 'none' | 'free' | 'amount' | 'discount'

/** Ehrung eines Vereins oder Dachverbands (Bezeichnung und Beitragsanpassung). */
export interface HonoraryTitle {
  id: number
  name: string
  /** Mehrzahl für die Webseite, leer = abgeleitet (plural) */
  name_plural?: string
  plural?: string
  fee_mode: HonoraryFeeMode
  fee_amount: string | null
  fee_discount_percent: string | null
  fee_text: string
  is_archived: boolean
  sort_order: number
  /** Inhaber erscheinen auf der Webseite (z. B. Ehrenmitglieder) */
  is_public?: boolean
  /** Nur Jahr der Verleihung statt Zeitraum von–bis */
  year_only?: boolean
  in_use: boolean
  own: boolean
  owner_name: string
}

/** Verliehene Ehrung mit Zeitraum. */
export interface HonoraryAward {
  id: number
  title: number
  title_name: string
  fee_text: string
  owner_name: string
  valid_from: string
  valid_until: string | null
  note: string
  /** Ehrung hat nur ein Jahr der Verleihung */
  year_only?: boolean
}

/** Was die Auswahl eines Mitglieds braucht. */
export interface PickedMember {
  id: number
  first_name: string
  last_name: string
  email?: string
}

/** Geschlecht; leer = keine Angabe. */
export type Gender = '' | 'männlich' | 'weiblich' | 'divers'
export const GENDERS: { value: Gender; label: string }[] = [
  { value: '', label: 'keine Angabe' },
  { value: 'männlich', label: 'männlich' },
  { value: 'weiblich', label: 'weiblich' },
  { value: 'divers', label: 'divers' },
]

export interface MemberRow {
  id: number
  last_name: string
  first_name: string
  birth_date: string
  /** nach der Löschfrist: nur das Jahr ist bekannt */
  birth_year_only?: boolean
  gender: Gender
  club_number: string
  member_number: number | null
  member_type: string | null
  status: 'active' | 'former'
  entry_date: string | null
  exit_date: string | null
  departments: string[]
  honorary_titles: string[]
  photo_url: string | null
  email: string
  phone: string
  street: string
  postal_code: string
  city: string
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface Contact {
  email: string
  phone: string
  street: string
  postal_code: string
  city: string
  country: string
}

export interface Period {
  id: number
  entry_date: string
  exit_date: string | null
  exit_reason: string
  exit_reason_label: string
  note: string
}

export interface TypeAssignment {
  id: number
  member_type: number
  member_type_name: string
  active: boolean
  reported: boolean
  valid_from: string
  valid_until: string | null
}

export interface DepartmentMembership {
  id: number
  department: number
  department_name: string
  valid_from: string
  valid_until: string | null
}

export interface DepartmentRoleHolder {
  id: number
  role: number
  role_name: string
  department_name: string
  valid_from: string
  valid_until: string | null
}

export interface MemberDetail {
  id: number
  person_id: number
  last_name: string
  first_name: string
  birth_date: string
  birth_year_only?: boolean
  gender: Gender
  club_number: string
  pays_fee_self: boolean
  info_opt_out_at: string | null
  /** fern geführt: Stammdaten pflegt eine ausgegliederte Untereinheit (Verbund) */
  managed_by?: { id: number; name: string } | null
  contact: Contact | null
  contact_shared: boolean
  status: 'active' | 'former'
  current_type: TypeAssignment | null
  periods: Period[]
  type_history: TypeAssignment[]
  departments: DepartmentMembership[]
  department_roles: DepartmentRoleHolder[]
  /** eigene Verleihungen; im Verein zusätzlich die des Dachverbands (nur lesen) */
  honorary_titles: { own: HonoraryAward[]; federation?: HonoraryAward[] }
  board_roles: { id: number; role_name: string; valid_from: string; valid_until: string | null }[]
  federation: {
    name: string
    is_member: boolean
    member_number: number | null
    entry_date: string | null
    entry_date_manual: boolean
    /** Dachverband auf einer anderen Instanz (Verbund) */
    remote?: boolean
  } | null
  exit_reasons: { value: string; label: string }[]
  purged: boolean
  purge_due: string | null
  photo: import('./photos.ts').PhotoState['photo']
  photo_consent_at: string | null
  photo_consent_source: '' | 'board' | 'member' | 'app'
  other_memberships: { club: string; entry_date: string; exit_date: string | null }[] | null
  duration: {
    club: DurationInfo
    federation: (DurationInfo & { rule: string }) | null
  }
}

export interface DurationInfo {
  days: number
  years: number
  precision?: DatePrecision
  next: { years: number; date: string } | null
}

export interface Transfer {
  id: number
  person_name: string
  birth_date: string
  from_org_name: string
  to_org_name: string
  member_type_name: string
  entry_date: string
  message: string
  status: 'pending' | 'accepted' | 'rejected' | 'cancelled'
  status_label: string
  decision: string
  decision_label: string
  response: string
  created_at: string
  decided_at: string | null
  direction: 'incoming' | 'outgoing'
}

export interface Duplicate {
  id: number
  last_name: string
  first_name: string
  birth_date: string
  member_number: number | null
  clubs: string[] | null
  already_member_here: boolean
}

export interface ListParams {
  suche?: string
  status?: string
  art?: string
  geschlecht?: string
  abteilung?: string
  ehrentitel?: string
  sortierung?: string
  page?: number
  page_size?: number
}

const base = (org: number) => `/api/orgs/${org}`

const awardBase = (org: number, member: number, federation: boolean) =>
  `${base(org)}/${federation ? 'federation/' : ''}members/${member}/honorary-titles/`

function query(params: Record<string, unknown>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  return q.toString()
}

export const memberApi = {
  types: (org: number) => api.get<MemberType[]>(`${base(org)}/member-types/`),
  createType: (org: number, data: Partial<MemberType>) =>
    api.post<MemberType>(`${base(org)}/member-types/`, data),
  updateType: (org: number, id: number, data: Partial<MemberType>) =>
    api.patch<MemberType>(`${base(org)}/member-types/${id}/`, data),
  deleteType: (org: number, id: number) => api.del(`${base(org)}/member-types/${id}/`),
  reorderTypes: (org: number, ids: number[]) =>
    api.post(`${base(org)}/member-types/reorder/`, { ids }),
  typeUsage: (org: number, id: number) =>
    api.get<TypeUsage>(`${base(org)}/member-types/${id}/usage/`),
  archiveType: (org: number, id: number) =>
    api.post<MemberType>(`${base(org)}/member-types/${id}/archive/`),
  restoreType: (org: number, id: number) =>
    api.post<MemberType>(`${base(org)}/member-types/${id}/restore/`),

  /** Ehrungen; ``all`` im Verein auch die des Dachverbands */
  honoraryTitles: (org: number, all = false) =>
    api.get<HonoraryTitle[]>(`${base(org)}/honorary-titles/${all ? '?alle=1' : ''}`),
  createHonoraryTitle: (org: number, data: Partial<HonoraryTitle>) =>
    api.post<HonoraryTitle>(`${base(org)}/honorary-titles/`, data),
  updateHonoraryTitle: (org: number, id: number, data: Partial<HonoraryTitle>) =>
    api.patch<HonoraryTitle>(`${base(org)}/honorary-titles/${id}/`, data),
  deleteHonoraryTitle: (org: number, id: number) => api.del(`${base(org)}/honorary-titles/${id}/`),
  reorderHonoraryTitles: (org: number, ids: number[]) =>
    api.post(`${base(org)}/honorary-titles/reorder/`, { ids }),
  honoraryTitleUsage: (org: number, id: number) =>
    api.get<TypeUsage>(`${base(org)}/honorary-titles/${id}/usage/`),
  archiveHonoraryTitle: (org: number, id: number) =>
    api.post<HonoraryTitle>(`${base(org)}/honorary-titles/${id}/archive/`),
  restoreHonoraryTitle: (org: number, id: number) =>
    api.post<HonoraryTitle>(`${base(org)}/honorary-titles/${id}/restore/`),

  /** Verleihungen an einem Mitglied; ``federation`` = Dachverband verleiht eigene Ehrungen */
  awards: (org: number, member: number, federation = false) =>
    api.get<HonoraryAward[]>(awardBase(org, member, federation)),
  addAward: (
    org: number,
    member: number,
    data: { title: number; valid_from: string; valid_until?: string | null; note?: string },
    federation = false,
  ) => api.post<HonoraryAward>(awardBase(org, member, federation), data),
  updateAward: (
    org: number,
    member: number,
    id: number,
    data: Partial<HonoraryAward>,
    federation = false,
  ) => api.patch<HonoraryAward>(`${awardBase(org, member, federation)}${id}/`, data),
  deleteAward: (org: number, member: number, id: number, federation = false) =>
    api.del(`${awardBase(org, member, federation)}${id}/`),

  list: (org: number, params: ListParams) =>
    api.get<Page<MemberRow>>(`${base(org)}/members/?${query({ ...params })}`),
  duplicates: (org: number, name: string, vorname: string, geburtsdatum: string) =>
    api.get<Duplicate[]>(
      `${base(org)}/members/duplicates/?${query({ name, vorname, geburtsdatum })}`,
    ),
  admit: (org: number, data: Record<string, unknown>, requestKey?: string) =>
    api.post<MemberDetail>(`${base(org)}/members/admit/`, data, requestKey),

  detail: (org: number, id: number) => api.get<MemberDetail>(`${base(org)}/members/${id}/`),
  update: (org: number, id: number, data: Record<string, unknown>) =>
    api.patch<MemberDetail>(`${base(org)}/members/${id}/`, data),
  history: (org: number, id: number) =>
    api.get<AuditEntry[]>(`${base(org)}/members/${id}/history/`),
  setFederationEntry: (org: number, id: number, date: string | null) =>
    api.patch<MemberDetail>(`${base(org)}/members/${id}/federation/`, { manual_entry_date: date }),

  addPeriod: (org: number, id: number, data: Partial<Period> & { member_type?: number | null }) =>
    api.post<Period>(`${base(org)}/members/${id}/periods/`, data),
  deletePeriod: (org: number, id: number, period: number) =>
    api.del(`${base(org)}/members/${id}/periods/${period}/`),

  addDepartment: (org: number, id: number, data: { department: number; valid_from: string }) =>
    api.post<DepartmentMembership>(`${base(org)}/members/${id}/departments/`, data),
  endDepartment: (org: number, id: number, dm: number, valid_until: string) =>
    api.patch(`${base(org)}/members/${id}/departments/${dm}/`, { valid_until }),
  addDepartmentRole: (org: number, id: number, data: { role: number; valid_from: string }) =>
    api.post<DepartmentRoleHolder>(`${base(org)}/members/${id}/department-roles/`, data),
  endDepartmentRole: (org: number, id: number, holder: number, valid_until: string) =>
    api.patch(`${base(org)}/members/${id}/department-roles/${holder}/`, { valid_until }),

  changeType: (org: number, id: number, member_type: number, valid_from: string) =>
    api.post<MemberDetail>(`${base(org)}/members/${id}/change-type/`, { member_type, valid_from }),
  exit: (
    org: number,
    id: number,
    data: { exit_date: string; exit_reason: string; note?: string },
  ) => api.post<MemberDetail>(`${base(org)}/members/${id}/exit/`, data),
  reentry: (org: number, id: number, data: Record<string, unknown>) =>
    api.post<MemberDetail>(`${base(org)}/members/${id}/reentry/`, data),
  /** Auskunft für dieses Mitglied als ZIP (Art. 15 DSGVO). */
  disclosure: (org: number, id: number) =>
    requestBlob('GET', `${base(org)}/members/${id}/auskunft/`),
  /** Daten eines ehemaligen Mitglieds auf Verlangen vor Ablauf der Löschfrist löschen. */
  erase: (org: number, id: number) => api.post<MemberDetail>(`${base(org)}/members/${id}/erase/`),

  transfers: (org: number) => api.get<Transfer[]>(`${base(org)}/transfers/`),
  createTransfer: (org: number, data: Record<string, unknown>) =>
    api.post<Transfer>(`${base(org)}/transfers/`, data),
  decideTransfer: (
    org: number,
    id: number,
    data: { decision: string; member_type?: number; response?: string },
  ) => api.post<Transfer>(`${base(org)}/transfers/${id}/decide/`, data),
  cancelTransfer: (org: number, id: number) =>
    api.post<Transfer>(`${base(org)}/transfers/${id}/cancel/`),
}

export function todayIso(): string {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
