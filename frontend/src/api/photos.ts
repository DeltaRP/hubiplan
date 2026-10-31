// Mitgliederfotos und persönliche Upload-Links.
import { api, parseBody, request, send } from './client.ts'

export interface PhotoVersion {
  url: string
  thumbnail_url: string
  source: 'board' | 'member'
  source_label: string
  uploaded_at: string
}

export interface PhotoState {
  photo: { approved: PhotoVersion | null; pending: PhotoVersion | null }
  photo_consent_at: string | null
  photo_consent_source: '' | 'board' | 'member' | 'app'
}

export interface UploadLink {
  id: number
  state: 'open' | 'used' | 'expired' | 'revoked'
  created_at: string
  expires_at: string
  used_at: string | null
  sent_to: string
  url?: string
}

export interface PublicLinkInfo {
  first_name: string
  organization: string
  imprint_key?: string
  logo_url: string | null
  theme: { primary: string; on_primary: string; accent: string; on_accent: string }
  expires_at: string
  needs_approval: boolean
}

const base = (org: number, member: number) => `/api/orgs/${org}/members/${member}`

export const photoApi = {
  upload: (org: number, member: number, blob: Blob, consent: boolean) => {
    const form = new FormData()
    form.append('file', blob, 'foto.jpg')
    if (consent) form.append('consent', 'true')
    return api.post<PhotoState>(`${base(org, member)}/photo/`, form)
  },
  remove: (org: number, member: number, status: 'approved' | 'pending' = 'approved') =>
    request<PhotoState>('DELETE', `${base(org, member)}/photo/?status=${status}`),
  rotate: (org: number, member: number, direction: 'left' | 'right') =>
    api.post<PhotoState>(`${base(org, member)}/photo/rotate/`, { direction }),
  decide: (org: number, member: number, decision: 'approve' | 'reject') =>
    api.post<PhotoState>(`${base(org, member)}/photo/approve/`, { decision }),
  setConsent: (org: number, member: number, date: string | null) =>
    api.patch<PhotoState>(`${base(org, member)}/photo/consent/`, { photo_consent_at: date }),
  links: (org: number, member: number) =>
    api.get<UploadLink[]>(`${base(org, member)}/photo-links/`),
  createLink: (org: number, member: number, sendEmail: boolean) =>
    api.post<UploadLink>(`${base(org, member)}/photo-links/`, { send_email: sendEmail }),
  revokeLink: (org: number, member: number, id: number) =>
    api.post<UploadLink>(`${base(org, member)}/photo-links/${id}/revoke/`),

  publicInfo: (token: string) => request<PublicLinkInfo>('GET', `/api/public/photo/${token}/`),
  publicUpload: (token: string, blob: Blob) => {
    const form = new FormData()
    form.append('file', blob, 'foto.jpg')
    form.append('consent', 'true')
    return publicPost(token, form)
  },
}

// Die öffentliche Seite braucht kein CSRF-Token (keine Sitzung, der Link ist der Ausweis).
async function publicPost(token: string, form: FormData) {
  const res = await send(`/api/public/photo/${token}/`, {
    method: 'POST',
    body: form,
    credentials: 'omit',
  })
  return { status: res.status, body: parseBody(await res.text()) as Record<string, unknown> }
}
