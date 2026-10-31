// Zugänge: Abteilungsbereich, Mitgliederbereich, Anmeldelinks, Postausgang.
import { api, listParams, request } from './client.ts'
import type { ListQuery, Paged } from './client.ts'
import type { CatalogModule, EffectiveTheme } from './orgs.ts'
import type { MemberRow, Page } from './members.ts'
import type { DeptTerms } from '../org/terms.ts'
import type { DatePrecision } from '../components/forms.ts'

export interface DeptSummary {
  id: number
  name: string
  display_name?: string
  /** z. B. „Jägerzug › Gruppe 1“ */
  path?: string
  club_id: number
  club_name: string
  club_display_name?: string
  label: string
  terms?: DeptTerms
  date_precision?: DatePrecision
  permissions: string[]
  theme: EffectiveTheme
  events_enabled?: boolean
  imprint_key?: string
}

export interface PortalEntry {
  id: number
  club_id: number
  club_name: string
  club_display_name?: string
  first_name: string
  last_name: string
  date_precision?: DatePrecision
  theme: EffectiveTheme
  events_enabled?: boolean
  terms?: DeptTerms
  imprint_key?: string
}

export interface Contexts {
  departments: DeptSummary[]
  portal: PortalEntry[]
}

export interface AccessInfo {
  email: string
  created_at: string
  last_login: string | null
  login: 'link' | 'password'
}

export interface ContactData {
  email: string
  phone: string
  street: string
  postal_code: string
  city: string
  country: string
}

export interface DeptMember {
  id: number
  last_name: string
  first_name: string
  birth_date: string
  gender?: string
  club_number: string
  member_type: string | null
  entry_date: string | null
  departments: string[]
  contact: ContactData | null
  access?: AccessInfo | null
}

export interface ChangeRequest {
  id: number
  member_id: number
  member_name: string
  data: Record<string, string>
  previous: Record<string, string | null>
  message: string
  status: 'pending' | 'accepted' | 'rejected'
  status_label: string
  response: string
  created_at: string
  decided_at: string | null
}

export interface PortalDetail extends DeptMember {
  status: 'active' | 'former'
  contact_changes_need_approval: boolean
  club: {
    name: string
    street: string
    postal_code: string
    city: string
    email: string
    phone: string
    website: string
  }
  change_requests: ChangeRequest[]
}

export interface DeptRole {
  id: number
  name: string
  permissions: string[]
  holder_count: number
}

export interface Holder {
  id: number
  member_id: number
  member_name: string
  role: number
  role_name: string
  valid_from: string
  valid_until: string | null
}

export interface OutgoingMail {
  id: number
  created_at: string
  organization_name: string | null
  to: string
  reply_to: string
  subject: string
  body: string
  kind: string
  status: 'stored' | 'sent' | 'failed'
  status_label: string
  error: string
  attachments: { index: number; name: string; size: number }[]
}

export const DEPT_PERM = {
  membersView: 'dept.members.view',
  membersEdit: 'dept.members.edit',
  rolesManage: 'dept.roles.manage',
  accessManage: 'dept.access.manage',
  invoicesView: 'dept.invoices.view',
  cardsManage: 'dept.cards.manage',
  export: 'dept.export',
  eventsManage: 'dept.events.manage',
  docsManage: 'dept.docs.manage',
  circularsSend: 'dept.circulars.send',
} as const

export const FIELD_LABELS: Record<string, string> = {
  last_name: 'Name',
  first_name: 'Vorname',
  birth_date: 'Geburtsdatum',
  gender: 'Geschlecht',
  email: 'E-Mail',
  phone: 'Telefon',
  street: 'Straße und Hausnummer',
  postal_code: 'PLZ',
  city: 'Ort',
  country: 'Land',
}

const dept = (id: number) => `/api/depts/${id}`
const org = (id: number) => `/api/orgs/${id}`

export const portalApi = {
  contexts: () => api.get<Contexts>('/api/me/contexts/'),

  // Abteilungsbereich
  deptMembers: (id: number, params: { suche?: string; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (params.suche) q.set('suche', params.suche)
    q.set('page', String(params.page ?? 1))
    if (params.page_size) q.set('page_size', String(params.page_size))
    return api.get<Page<MemberRow>>(`${dept(id)}/members/?${q}`)
  },
  deptMember: (id: number, member: number) => api.get<DeptMember>(`${dept(id)}/members/${member}/`),
  updateDeptMember: (id: number, member: number, data: Record<string, string>) =>
    api.patch<DeptMember>(`${dept(id)}/members/${member}/`, data),
  sendDeptAccess: (id: number, member: number, transfer = false) =>
    api.post<{ access: AccessInfo; sent: 'link' | 'password' }>(
      `${dept(id)}/members/${member}/access/`,
      { transfer },
    ),
  removeDeptAccess: (id: number, member: number) =>
    api.del(`${dept(id)}/members/${member}/access/`),
  deptRoles: (id: number) =>
    api.get<{ roles: DeptRole[]; catalog: CatalogModule[] }>(`${dept(id)}/roles/`),
  createDeptRole: (id: number, data: { name: string; permissions: string[] }) =>
    api.post<DeptRole>(`${dept(id)}/roles/`, data),
  updateDeptRole: (id: number, role: number, data: Partial<DeptRole>) =>
    api.patch<DeptRole>(`${dept(id)}/roles/${role}/`, data),
  deleteDeptRole: (id: number, role: number) => api.del(`${dept(id)}/roles/${role}/`),
  reorderDeptRoles: (id: number, ids: number[]) => api.post(`${dept(id)}/roles/reorder/`, { ids }),
  holders: (id: number) => api.get<Holder[]>(`${dept(id)}/holders/`),
  addHolder: (id: number, data: { member: number; role: number; valid_from?: string }) =>
    api.post<Holder>(`${dept(id)}/holders/`, data),
  endHolder: (id: number, holder: number) => api.post<Holder>(`${dept(id)}/holders/${holder}/end/`),

  // Mitgliederbereich
  portal: (access: number) => api.get<PortalDetail>(`/api/portal/${access}/`),
  requestChange: (access: number, data: Record<string, string>) =>
    api.post<{ applied: Record<string, string>; request: ChangeRequest | null }>(
      `/api/portal/${access}/change-requests/`,
      data,
    ),

  // Vereinsseite
  memberAccess: (orgId: number, member: number) =>
    api.get<{
      access: AccessInfo | null
      portal_enabled: boolean
      department_access_enabled: boolean
    }>(`${org(orgId)}/members/${member}/access/`),
  sendMemberAccess: (orgId: number, member: number, transfer = false) =>
    api.post<{ access: AccessInfo; sent: 'link' | 'password' }>(
      `${org(orgId)}/members/${member}/access/`,
      { transfer },
    ),
  removeMemberAccess: (orgId: number, member: number) =>
    api.del(`${org(orgId)}/members/${member}/access/`),
  changeRequests: (orgId: number, status = 'pending') =>
    api.get<ChangeRequest[]>(`${org(orgId)}/change-requests/?status=${status}`),
  decide: (orgId: number, id: number, accept: boolean, response = '', overwrite = false) =>
    api.post<ChangeRequest>(`${org(orgId)}/change-requests/${id}/decide/`, {
      accept,
      response,
      overwrite,
    }),

  // Postausgang
  outbox: (orgId: number, query: ListQuery = {}) =>
    api.get<Paged<OutgoingMail>>(`${org(orgId)}/outbox/${listParams(query)}`),
  outboxAttachmentUrl: (orgId: number, mail: number, index: number) =>
    `${org(orgId)}/outbox/${mail}/attachments/${index}/`,
  platformOutbox: (query: ListQuery = {}) =>
    api.get<Paged<OutgoingMail>>(`/api/platform/outbox/${listParams(query)}`),
  platformAttachmentUrl: (mail: number, index: number) =>
    `/api/platform/outbox/${mail}/attachments/${index}/`,
}

// Anmeldelinks (ohne Anmeldung)
export async function requestLoginLink(email: string): Promise<string> {
  const { status, body } = await request<{ detail?: string }>('POST', '/api/public/login-link/', {
    email,
  })
  if (status === 429) throw new Error('Zu viele Versuche. Bitte später erneut.')
  if (status >= 400) throw new Error('Bitte eine gültige E-Mail-Adresse angeben.')
  return body.detail ?? 'Wenn ein Zugang besteht, ist ein Anmeldelink unterwegs.'
}

export async function redeemLoginLink(
  token: string,
): Promise<
  | { ok: true; user: { id: number; email: string; display: string } }
  | { ok: false; message: string }
> {
  const { status, body } = await request<{
    id: number
    email: string
    display: string
    detail?: string
  }>('POST', `/api/public/login-link/${token}/`)
  if (status === 200) return { ok: true, user: body }
  return { ok: false, message: body.detail ?? 'Der Link ist ungültig oder abgelaufen.' }
}
