// Organisationen, Abteilungen, Rollen, Erscheinungsbild, Protokoll, Plattform.
import { api, listParams } from './client.ts'
import type { ListQuery, Paged } from './client.ts'
import type { DeptTerms } from '../org/terms.ts'
import type { DatePrecision } from '../components/forms.ts'

export type OrgType = 'platform' | 'federation' | 'club' | 'unit'

export interface EffectiveTheme {
  primary: string
  on_primary: string
  accent: string
  on_accent: string
  logo_url: string | null
  /** Haupt-, Zweit- und weitere Farben (bis sechs) */
  palette?: PaletteColor[]
  inherited_from: { colors: string | null; logo: string | null }
}

export interface PaletteColor {
  color: string
  on_color: string
  name: string
}

export interface ExtraColor {
  color: string
  name: string
}

/** Kurzname, falls vorhanden, sonst der vollständige Name (für Navigation, Listen, Auswahl). */
export function displayName(x: { name: string; display_name?: string | null }): string {
  return x.display_name || x.name
}

/** Name einer Untereinheit in Auswahlfeldern; tiefere Ebenen mit Pfad („Jägerzug › Gruppe 1“). */
export function unitName(d: {
  name: string
  display_name?: string | null
  depth?: number
  path?: string
}): string {
  return d.depth && d.path ? d.path : displayName(d)
}

export interface OrgSummary {
  id: number
  name: string
  short_name?: string
  display_name?: string
  type: OrgType
  type_label: string
  label?: string
  label_plural?: string
  parent_name: string | null
  parent_display_name?: string | null
  permissions: string[]
  modules: string[]
  department_label: string
  department_label_plural: string
  department_terms?: DeptTerms
  date_precision: DatePrecision
  federation_member_access: 'none' | 'read' | 'write' | null
  theme: EffectiveTheme
  /** SEPA-Lastschrift eingeschaltet (Finanzen › Einstellungen) */
  sepa_enabled?: boolean
  /** Zählprotokoll und Kassenbericht für Feste eingeschaltet (Finanzen › Konten) */
  cash_counts_enabled?: boolean
  /** Rücklagen nach § 62 AO eingeschaltet (Finanzen › Konten) */
  reserves_enabled?: boolean
  /** Oberste Einheit führt auch selbst Mitglieder */
  direct_members?: boolean
  /** Schlüssel der öffentlichen Seiten /impressum/<key> und /datenschutz/<key> */
  imprint_key?: string
  /** Eingetragener Verein (Schalter im Impressum): Registerangaben */
  registered?: boolean
  /** Schalter „steuerbegünstigt mit eigenem Bescheid“: Zuwendungsbestätigungen */
  donations_enabled?: boolean
  /** Ansicht als Rolle: wählbar (eigenes Recht) und gerade gewählte Rolle */
  role_preview?: { available: boolean; active: RolePreviewRole | null }
}

export interface RolePreviewRole {
  id: number
  name: string
}

/** Ansicht als Rolle: Rollen zur Wahl und gerade gewählte Rolle */
export interface RolePreviewState {
  available: boolean
  roles: RolePreviewRole[]
  active: RolePreviewRole | null
}

/** Ansicht als Rolle (nur lesen, nie mehr als die eigenen Rechte) */
export const rolePreviewApi = {
  get: (orgId: number) => api.get<RolePreviewState>(`/api/orgs/${orgId}/ansicht/`),
  start: (orgId: number, role: number) =>
    api.post<RolePreviewState>(`/api/orgs/${orgId}/ansicht/`, { role }),
  stop: (orgId: number) => api.delWith<RolePreviewState>(`/api/orgs/${orgId}/ansicht/`, {}),
}

export interface OrgDetail {
  id: number
  type: OrgType
  type_label: string
  parent_name: string | null
  name: string
  short_name?: string
  display_name?: string
  /** Dachverband: Artikel und Genitiv seines Namens in Texten der Vereine */
  name_gender?: 'f' | 'm' | 'n'
  name_genitive?: string
  /** Bezeichnung der Einheit selbst (z. B. „Verein“) */
  label?: string
  label_plural?: string
  label_gender?: 'f' | 'm' | 'n'
  label_genitive?: string
  label_en?: string
  label_plural_en?: string
  founding_year: number | null
  street: string
  postal_code: string
  city: string
  country: string
  contact_source: 'own' | 'role'
  contact_role: number | null
  contact_email: string
  contact_phone: string
  website: string
  contact_effective: {
    source: 'own' | 'role'
    role: string | null
    holder: string | null
    email: string
    phone: string
    website: string
  }
  department_label: string
  department_label_plural: string
  department_label_gender: 'f' | 'm' | 'n'
  department_label_genitive: string
  department_label_en?: string
  department_label_plural_en?: string
  department_terms?: DeptTerms
  allow_multiple_departments: boolean
  /** Oberste Einheit führt auch selbst Mitglieder */
  direct_members?: boolean
  /** führt eigene Mitglieder (Mitgliederliste, Mitgliedsarten, Ein-/Austritt) */
  keeps_members?: boolean
  /** Schalter „führt eigene Mitglieder“ lässt sich ändern (nur oberste Einheiten) */
  can_switch_members?: boolean
  photo_approval_required: boolean
  jubilee_years: number[]
  /** Jubiläumsstufen für Einheiten (aus dem Gründungsjahr) */
  unit_jubilee_years?: number[]
  federation_duration_rule: 'all_reported' | 'active_reported'
  date_precision: DatePrecision
  member_portal_enabled: boolean
  department_access_enabled: boolean
  contact_changes_need_approval: boolean
  fiscal_start_month: number
  fiscal_start_day: number
  fiscal_label: string
  logo_url: string | null
}

export interface ThemeSettings {
  primary_color: string
  accent_color: string
  primary_color_name: string
  accent_color_name: string
  extra_colors: ExtraColor[]
  logo_url: string | null
  effective: EffectiveTheme
}

export interface DepartmentRoleHolderInfo {
  /** Zuordnung (zum Beenden) */
  id: number
  membership: number
  name: string
  valid_from: string
}

export interface DepartmentRole {
  id: number
  department: number
  name: string
  position: number
  permissions: string[]
  /** Inhaber stehen in der Fußzeile der Briefvorlage */
  on_letterhead?: boolean
  /** Funktionsadresse (z. B. zugfuehrer@…), wählbar in der Briefvorlage */
  contact_email?: string
  /** Inhaber erscheinen auf der Webseite (Unterseite der Untereinheit) */
  on_website?: boolean
  /** Aktuelle Inhaber; leer ohne Recht auf die Mitgliederliste */
  holders: DepartmentRoleHolderInfo[]
}

export interface Department {
  id: number
  /** übergeordnete Untereinheit; leer: direkt unter der Einheit */
  parent_unit?: number | null
  /** 0: direkt unter der Einheit */
  depth?: number
  /** z. B. „Jägerzug › Gruppe 1“ */
  path?: string
  name: string
  short_name?: string
  display_name?: string
  /** freiwillig */
  founding_year: number | null
  /** eigene Homepage (optional) */
  website?: string
  /** Homepage auf der Seite der Einheit auf der Vereinswebseite verlinken */
  website_on_site?: boolean
  /** Vorschaubild der Homepage (von dort geholt oder selbst hochgeladen) */
  website_image_url?: string | null
  /** Vorschaubild selbst hochgeladen */
  website_image_custom?: boolean
  sort_order: number
  is_active: boolean
  /** leer: wie der Verein */
  date_precision: DatePrecision | ''
  fiscal_start_month: number
  fiscal_start_day: number
  primary_color: string
  accent_color: string
  logo_url: string | null
  roles: DepartmentRole[]
  effective_theme: EffectiveTheme
  /** heute zugeordnete Mitglieder */
  member_count?: number
  /** eigene Bezeichnung (folgt der Vorgabe der übergeordneten Einheit) */
  label?: string
  label_plural?: string
  label_gender?: 'f' | 'm' | 'n'
  label_en?: string
  label_plural_en?: string
  /** Bezeichnung der eigenen Untereinheiten */
  department_label?: string
  department_label_plural?: string
  department_label_gender?: 'f' | 'm' | 'n'
  department_label_genitive?: string
  department_label_en?: string
  department_label_plural_en?: string
  /** Formen für Texte über die eigenen Untereinheiten */
  child_terms?: Record<string, string>
  /** eigener Arbeitsbereich mit eigener Kasse und eigenen Rollen */
  own_workspace?: boolean
  /** Rolleninhaber bekommen Zugänge mit Rechten; aus: von oben verwaltet, Rollen = Ämter */
  self_managed?: boolean
  /** eigene Webseite (nur mit eigenem Arbeitsbereich) */
  own_website?: boolean
  /** Mitglieder (auch der Einheiten darunter) zahlen keinen Vereinsbeitrag */
  fee_exempt?: boolean
  /** liegt auf einer anderen Instanz (Verbund, nur Anzeige) */
  is_remote?: boolean
}

export interface Role {
  id: number
  name: string
  description: string
  permissions: string[]
  is_board: boolean
  /** Inhaber erscheinen im Impressum als Vertretungsberechtigte */
  represents?: boolean
  /** Inhaber stehen zusätzlich in der Fußzeile der Briefvorlage */
  on_letterhead?: boolean
  /** Funktionsadresse (z. B. kassierer@…), wählbar in der Briefvorlage */
  contact_email?: string
  /** Inhaber erscheinen auf der Webseite (Vorstand und Ansprechpartner) */
  on_website?: boolean
  /** Stelle in der Liste (per Ziehen, gilt auch für die Webseite) */
  position?: number
  /** Heutige und frühere Inhaber erscheinen auf der Webseite unter Geschichte › Ämter */
  in_chronicle?: boolean
  assignment_count: number
}

export type SocialKind =
  | 'facebook'
  | 'instagram'
  | 'youtube'
  | 'tiktok'
  | 'x'
  | 'mastodon'
  | 'bluesky'
  | 'threads'
  | 'whatsapp'
  | 'linkedin'
  | 'other'

export const SOCIAL_KINDS: { value: SocialKind; label: string }[] = [
  { value: 'facebook', label: 'Facebook' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'x', label: 'X' },
  { value: 'mastodon', label: 'Mastodon' },
  { value: 'bluesky', label: 'Bluesky' },
  { value: 'threads', label: 'Threads' },
  { value: 'whatsapp', label: 'WhatsApp-Kanal' },
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'other', label: 'Sonstiges' },
]

/** Social-Media-Kanal einer Einheit */
export interface SocialLink {
  id: number
  kind: SocialKind
  kind_label: string
  url: string
  /** Anzeigename, z. B. @hubertus1920 */
  label: string
  display: string
  position: number
}

export interface Assignment {
  id: number
  user_email: string
  user_name: string
  person_name: string | null
  /** Mitgliedsakte der Person in dieser Einheit (Mitgliedschaft), falls zugeordnet */
  member_record?: { id: number; first_name: string; last_name: string } | null
  role: number
  role_name: string
  valid_from: string
  valid_until: string | null
  is_active: boolean
  invited?: boolean
  new_account?: boolean
  has_mfa?: boolean
}

export interface AuditEntry {
  id: number
  timestamp: string
  user_email: string
  /** Herkunft, z. B. „App (Pixel 8)“; leer = Browser oder System */
  via?: string
  action: 'create' | 'update' | 'delete'
  action_label: string
  object_type: string
  object_repr: string
  changes: Record<string, [unknown, unknown]>
  /** Rückgängig aus dem Protokoll (fehlt bei älteren Einträgen und nach 30 Tagen). */
  undo?: {
    change_set: string
    state: 'possible' | 'done' | 'blocked'
    reason: string
    is_undo: boolean
  } | null
}

export interface CatalogModule {
  id: string
  label: string
  permissions: { code: string; label: string }[]
}

export interface PlatformOrg {
  id: number
  /** technische Art; folgt aus Lage und „führt eigene Mitglieder“ */
  type: 'federation' | 'club'
  type_label: string
  /** führt eigene Mitglieder (Mitgliederliste, Mitgliedsarten, Ein-/Austritt) */
  keeps_members?: boolean
  /** Schalter lässt sich ändern (nur oberste Einheiten) */
  can_switch_members?: boolean
  federation: number | null
  federation_name: string | null
  name: string
  short_name?: string
  display_name?: string
  /** Bezeichnung der Einheit selbst (z. B. „Verein“) */
  label?: string
  label_plural?: string
  label_gender?: 'f' | 'm' | 'n'
  label_genitive?: string
  label_en?: string
  label_plural_en?: string
  founding_year: number | null
  street: string
  postal_code: string
  city: string
  country: string
  contact_email: string
  contact_phone: string
  website: string
  federation_member_access: 'none' | 'read' | 'write'
  federation_show_former_memberships: boolean
  enabled_modules: string[]
  tax_areas_enabled: boolean
  is_active: boolean
  club_count: number
  logo_url: string | null
}

/** Verein aus Sicht seines Dachverbands */
export interface FederationClub {
  id: number
  name: string
  short_name: string
  display_name: string
  /** Bezeichnung ihrer Untereinheiten (pflegt sie selbst) */
  department_label_plural?: string
  /** Baum darunter, nur zum Ansehen */
  units?: { id: number; name: string; depth: number }[]
  founding_year: number | null
  street: string
  postal_code: string
  city: string
  country: string
  contact_email: string
  contact_phone: string
  website: string
  is_active: boolean
  logo_url: string | null
}

export interface PlatformSettings {
  person_data_mode: 'shared' | 'per_club'
  deletion_period_months: number
  peering_enabled: boolean
  peering_allowed_hosts: string
  peering_login: boolean
}

const org = (id: number) => `/api/orgs/${id}`

export const orgApi = {
  mine: () => api.get<OrgSummary[]>('/api/me/organizations/'),
  catalog: (type: OrgType | 'department', orgId?: number) =>
    api.get<CatalogModule[]>(`/api/permissions/?org_type=${type}${orgId ? `&org=${orgId}` : ''}`),

  detail: (id: number) => api.get<OrgDetail>(`${org(id)}/`),
  update: (id: number, data: Partial<OrgDetail>) => api.patch<OrgDetail>(`${org(id)}/`, data),

  theme: (id: number) => api.get<ThemeSettings>(`${org(id)}/theme/`),
  updateTheme: (id: number, data: Partial<ThemeSettings>) =>
    api.patch<ThemeSettings>(`${org(id)}/theme/`, data),
  uploadLogo: (url: string, file: File, removeBackground = false) => {
    const form = new FormData()
    form.append('logo', file)
    if (removeBackground) form.append('remove_background', 'true')
    return api.post<{ logo_url: string }>(url, form)
  },
  logoUrl: (id: number) => `${org(id)}/logo/`,
  departmentLogoUrl: (id: number, dep: number) => `${org(id)}/departments/${dep}/logo/`,
  departmentHomepageImageUrl: (id: number, dep: number) =>
    `${org(id)}/departments/${dep}/homepage-image/`,
  uploadHomepageImage: (url: string, file: File) => {
    const form = new FormData()
    form.append('image', file)
    return api.post<{ website_image_url: string }>(url, form)
  },

  departments: (id: number) => api.get<Department[]>(`${org(id)}/departments/`),
  createDepartment: (id: number, data: Partial<Department>) =>
    api.post<Department>(`${org(id)}/departments/`, data),
  updateDepartment: (id: number, dep: number, data: Partial<Department>) =>
    api.patch<Department>(`${org(id)}/departments/${dep}/`, data),
  deleteDepartment: (id: number, dep: number) => api.del(`${org(id)}/departments/${dep}/`),
  /** Reihenfolge der Untereinheiten unter `parent` (null: oberste Ebene) */
  reorderDepartments: (id: number, parent: number | null, ids: number[]) =>
    api.post(`${org(id)}/departments/reorder/`, { parent, ids }),
  reorderDepartmentRoles: (id: number, department: number, ids: number[]) =>
    api.post(`${org(id)}/department-roles/reorder/`, { department, ids }),
  setupUnitManager: (id: number, department: number, member: number) =>
    api.post<UnitManagerResult>(`${org(id)}/departments/${department}/manager/`, { member }),
  createDepartmentRole: (id: number, department: number, data: Partial<DepartmentRole>) =>
    api.post<DepartmentRole>(`${org(id)}/department-roles/`, { ...data, department }),
  updateDepartmentRole: (id: number, role: number, data: Partial<DepartmentRole>) =>
    api.patch<DepartmentRole>(`${org(id)}/department-roles/${role}/`, data),
  deleteDepartmentRole: (id: number, role: number) =>
    api.del(`${org(id)}/department-roles/${role}/`),

  /** Dachverband: seine Vereine */
  clubs: (id: number) => api.get<FederationClub[]>(`${org(id)}/clubs/`),
  updateClub: (id: number, club: number, data: Partial<FederationClub>) =>
    api.patch<FederationClub>(`${org(id)}/clubs/${club}/`, data),

  socialLinks: (id: number) => api.get<SocialLink[]>(`${org(id)}/social-links/`),
  createSocialLink: (id: number, data: Partial<SocialLink>) =>
    api.post<SocialLink>(`${org(id)}/social-links/`, data),
  updateSocialLink: (id: number, link: number, data: Partial<SocialLink>) =>
    api.patch<SocialLink>(`${org(id)}/social-links/${link}/`, data),
  deleteSocialLink: (id: number, link: number) => api.del(`${org(id)}/social-links/${link}/`),

  roles: (id: number) => api.get<Role[]>(`${org(id)}/roles/`),
  createRole: (id: number, data: Partial<Role>) => api.post<Role>(`${org(id)}/roles/`, data),
  updateRole: (id: number, role: number, data: Partial<Role>) =>
    api.patch<Role>(`${org(id)}/roles/${role}/`, data),
  deleteRole: (id: number, role: number) => api.del(`${org(id)}/roles/${role}/`),
  reorderRoles: (id: number, ids: number[]) => api.post(`${org(id)}/roles/reorder/`, { ids }),

  assignments: (id: number) => api.get<Assignment[]>(`${org(id)}/assignments/`),
  createAssignment: (
    id: number,
    data: {
      email: string
      role: number
      valid_from?: string
      valid_until?: string | null
      member?: number | null
    },
  ) => api.post<Assignment>(`${org(id)}/assignments/`, data),
  resetMfa: (id: number, a: number) =>
    api.post<{ reset: boolean }>(`/api/orgs/${id}/assignments/${a}/reset-mfa/`, {}),
  updateAssignment: (
    id: number,
    a: number,
    data: Partial<Pick<Assignment, 'valid_from' | 'valid_until'>> & { member?: number | null },
  ) => api.patch<Assignment>(`${org(id)}/assignments/${a}/`, data),
  deleteAssignment: (id: number, a: number) => api.del(`${org(id)}/assignments/${a}/`),

  openTasks: (id: number) => api.get<{ items: OpenTask[] }>(`${org(id)}/open-tasks/`),
  audit: (id: number, query: ListQuery = {}) =>
    api.get<Paged<AuditEntry>>(`${org(id)}/audit/${listParams(query)}`),
  auditChain: (id: number) => api.get<{ check: AuditChainCheck | null }>(`${org(id)}/audit/kette/`),
  checkAuditChain: (id: number) =>
    api.post<{ check: AuditChainCheck }>(`${org(id)}/audit/kette/`, {}),
}

/** Prüfung der verketteten Protokolleinträge (Prüfsummen). */
export interface AuditChainCheck {
  checked_at: string
  ok: boolean
  entries: number
  cleared: number
  head_seq: number | null
  head_hash: string
  problems: string[]
}

export const platformApi = {
  orgs: () => api.get<PlatformOrg[]>('/api/platform/orgs/'),
  create: (data: Partial<PlatformOrg>) => api.post<PlatformOrg>('/api/platform/orgs/', data),
  update: (id: number, data: Partial<PlatformOrg>) =>
    api.patch<PlatformOrg>(`/api/platform/orgs/${id}/`, data),
  addBoard: (id: number, email: string) =>
    api.post<{ email: string; role: string; invited: boolean; new_account: boolean }>(
      `/api/platform/orgs/${id}/board/`,
      { email },
    ),
  settings: () => api.get<PlatformSettings>('/api/platform/settings/'),
  updateSettings: (data: Partial<PlatformSettings>) =>
    api.patch<PlatformSettings>('/api/platform/settings/', data),
}

/** Vorgang, der eine Entscheidung braucht (Startseite „Offene Aufgaben“) */
export interface OpenTask {
  kind: 'change_request' | 'transfer' | 'photo' | 'event'
  kind_label: string
  title: string
  detail: string
  created_at: string
  link: string
}

export const PERM = {
  membersView: 'members.view',
  membersEdit: 'members.edit',
  photosManage: 'photos.manage',
  orgEdit: 'org.edit',
  auditView: 'audit.view',
  rolesManage: 'roles.manage',
  rolesPreview: 'roles.preview',
  themeEdit: 'theme.edit',
  exportRun: 'export.run',
  platformManage: 'platform.manage',
  financeView: 'finance.view',
  financeEdit: 'finance.edit',
  billingView: 'billing.view',
  billingEdit: 'billing.edit',
  cardsManage: 'cards.manage',
  dataExport: 'data.export',
  clubsManage: 'clubs.manage',
  eventsManage: 'events.manage',
  docsView: 'docs.view',
  docsManage: 'docs.manage',
  circularsSend: 'circulars.send',
  websiteManage: 'website.manage',
  websiteContent: 'website.content',
  peeringManage: 'peering.manage',
  competitionsManage: 'competitions.manage',
  competitionsResults: 'competitions.results',
  entriesSubmit: 'entries.submit',
  entriesManage: 'entries.manage',
} as const

/** Ergebnis von „Verwalter einrichten“ für eine Untereinheit. */
export interface UnitManagerResult {
  email: string
  role: string
  workspace_role: string | null
  mail: 'link' | 'password' | 'invitation' | 'none'
}
