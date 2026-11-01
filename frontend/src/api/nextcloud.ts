// Anmeldung an der Nextcloud mit dem HUBIplan-Konto (Backend: App oidc).
import { api } from './client.ts'

export type NextcloudAudience = 'board' | 'roles' | 'members'

export interface NextcloudClient {
  id: number
  name: string
  base_url: string
  client_id: string
  audience: NextcloudAudience
  require_mfa: boolean
  groups_board: boolean
  groups_roles: boolean
  groups_units: boolean
  groups_members: boolean
  // Je Zeile „E-Mail = Benutzername“ (bisherige Nextcloud-Konten)
  usernames: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
  redirect_uri: string
  discovery_url: string
  // Nur direkt nach Anlegen oder Erneuern
  client_secret?: string
}

export type NextcloudInput = Partial<
  Pick<
    NextcloudClient,
    | 'name'
    | 'base_url'
    | 'audience'
    | 'require_mfa'
    | 'groups_board'
    | 'groups_roles'
    | 'groups_units'
    | 'groups_members'
    | 'usernames'
    | 'is_active'
  >
>

const base = (org: number) => `/api/orgs/${org}/nextcloud/`

export const nextcloudApi = {
  list: (org: number) => api.get<NextcloudClient[]>(base(org)),
  create: (org: number, data: NextcloudInput) => api.post<NextcloudClient>(base(org), data),
  update: (org: number, id: number, data: NextcloudInput) =>
    api.patch<NextcloudClient>(`${base(org)}${id}/`, data),
  remove: (org: number, id: number) => api.del(`${base(org)}${id}/`),
  renewSecret: (org: number, id: number) => api.post<NextcloudClient>(`${base(org)}${id}/secret/`),
}

export interface NextcloudService {
  name: string
  organization: string
  url: string
}

export interface NextcloudDenied {
  detail: string
  redirect?: string
  back?: string
}

export const oidcApi = {
  describe: (query: string) => api.get<NextcloudService>(`/api/oidc/authorize/?${query}`),
  authorize: (params: Record<string, string>) =>
    api.post<{ redirect: string }>('/api/oidc/authorize/', params),
}
