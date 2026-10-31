// Satzung, Beitragsordnung, Gründungsurkunde: Fassungen hochladen, auflisten, löschen und öffentlich freigeben.
import { api } from './client.ts'

/** statute = Satzung; optional je Einheit: fee_rules = Beitragsordnung, founding_deed = Gründungsurkunde */
export type StatuteKind = 'statute' | 'fee_rules' | 'founding_deed'

export interface StatuteVersion {
  id: number
  valid_from: string
  note: string
  name: string
  size: number
  uploaded_at: string
  uploaded_by: string
  is_current: boolean
  url: string
}

export interface StatutePublication {
  is_public: boolean
  pdf_url: string | null
  info_url: string | null
}

export interface StatuteData {
  versions: StatuteVersion[]
  publication: StatutePublication
  can_manage: boolean
}

const base = (org: number) => `/api/orgs/${org}/statutes/`
const query = (dept?: number, kind: StatuteKind = 'statute') => {
  const params = new URLSearchParams()
  if (dept) params.set('department', String(dept))
  if (kind !== 'statute') params.set('kind', kind)
  const text = params.toString()
  return text ? `?${text}` : ''
}

export const statuteApi = {
  list: (org: number, dept?: number, kind: StatuteKind = 'statute') =>
    api.get<StatuteData>(`${base(org)}${query(dept, kind)}`),
  upload: (
    org: number,
    file: File,
    validFrom: string,
    note: string,
    dept?: number,
    kind: StatuteKind = 'statute',
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('valid_from', validFrom)
    form.append('note', note)
    if (kind !== 'statute') form.append('kind', kind)
    if (dept) form.append('department', String(dept))
    return api.post<StatuteData>(base(org), form)
  },
  remove: (org: number, id: number) => api.del(`${base(org)}${id}/`),
  publish: (org: number, isPublic: boolean, dept?: number, kind: StatuteKind = 'statute') =>
    api.put<StatutePublication>(`${base(org)}publication/`, {
      is_public: isPublic,
      ...(kind !== 'statute' ? { kind } : {}),
      ...(dept ? { department: dept } : {}),
    }),
}
