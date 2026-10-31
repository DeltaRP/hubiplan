// Mitgliedsausweis mit QR-Code.
import { api, request } from './client.ts'

export type CardAction = 'create' | 'renew' | 'revoke' | 'restore'

export interface CardInfo {
  state: 'none' | 'active' | 'revoked'
  url?: string
  issued_at?: string
  revoked_at?: string | null
  /** QR-Code als data:-URL (SVG) */
  qr?: string
}

export interface PublicCard {
  imprint_key?: string
  first_name: string
  last_name: string
  status: 'active' | 'future' | 'inactive'
  status_label: string
  member_type: string | null
  club: string
  club_label?: string
  federation: string | null
  federation_label?: string | null
  department_label: string
  departments: string[]
  photo_url: string | null
  logo_url: string | null
  theme: { primary: string; on_primary: string; accent: string; on_accent: string }
  checked_at: string
}

function query(params: Record<string, string | number | undefined | null> = {}) {
  const q = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()
  return q ? `?${q}` : ''
}

export const cardApi = {
  get: (base: string) => api.get<CardInfo>(`${base}/card/`),
  act: (base: string, action: CardAction) => api.post<CardInfo>(`${base}/card/`, { action }),
  orgPdfUrl: (org: number, params?: Record<string, string | number | undefined | null>) =>
    `/api/orgs/${org}/cards/pdf/${query(params)}`,
  deptPdfUrl: (dept: number, params?: Record<string, string | number | undefined | null>) =>
    `/api/depts/${dept}/cards/pdf/${query(params)}`,
  portal: (access: number) => api.get<CardInfo>(`/api/portal/${access}/card/`),
  portalPdfUrl: (access: number) => `/api/portal/${access}/card/pdf/`,
  publicCard: (token: string) =>
    request<PublicCard>('GET', `/api/public/card/${encodeURIComponent(token)}/`),
}

/** Basis-URL der Mitgliedsakte im Verein bzw. in der Abteilung. */
export const cardBase = {
  org: (org: number, member: number) => `/api/orgs/${org}/members/${member}`,
  dept: (dept: number, member: number) => `/api/depts/${dept}/members/${member}`,
}
