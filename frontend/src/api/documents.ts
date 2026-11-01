// Dokumentenablage: Ordner, Dokumente und Fassungen für Vorstand, Abteilung und Mitglieder.
import { api } from './client.ts'

export type DocBase = string

export const docBase = {
  org: (id: number): DocBase => `/api/orgs/${id}/documents/`,
  dept: (id: number): DocBase => `/api/depts/${id}/documents/`,
  portal: (id: number): DocBase => `/api/portal/${id}/documents/`,
}

export type Visibility = 'board' | 'clubs' | 'members' | 'public'

export interface DocVersion {
  id: number
  name: string
  size: number
  content_type: string
  uploaded_at: string
  uploaded_by: string
  url: string
  inline: boolean
}

export interface DocItem {
  id: number
  folder: number
  title: string
  date: string | null
  note: string
  created_at: string
  created_by: string
  current: DocVersion | null
  version_count: number
  versions?: DocVersion[]
  deleted_at?: string
  deleted_by?: string
  folder_name?: string
}

export interface DocFolder {
  id: number
  name: string
  visibility: Visibility
  visibility_label: string
  shared_up: boolean
  documents: DocItem[]
  public_url?: string | null
  /** nur bei Freigaben des Dachverbands */
  from?: string
  /** Mitgliederbereich: Abteilung des Ordners */
  department?: string | null
}

export interface DocOverview {
  folders: DocFolder[]
  can_manage: boolean
  visibilities?: { value: Visibility; label: string }[]
  used_bytes?: number
  /** Ganzer Verein (alle Ablagen) und sein Speicherbudget */
  total_bytes?: number
  budget_bytes?: number
  trash_count?: number
  shared?: DocFolder[]
  /** von unten freigegebene Ordner (Abteilungen bzw. Vereine), nur lesen */
  from_below?: DocFolder[]
  /** Beschriftung der Freigabe nach oben; null = keine höhere Ebene */
  share_up_label?: string | null
  org_kind?: 'club' | 'federation' | 'department'
}

export const docApi = {
  overview: (base: DocBase) => api.get<DocOverview>(base),
  trash: (base: DocBase) => api.get<DocItem[]>(`${base}trash/`),
  createFolder: (base: DocBase, name: string, visibility: Visibility, sharedUp = false) =>
    api.post<DocFolder>(`${base}folders/`, { name, visibility, shared_up: sharedUp }),
  updateFolder: (
    base: DocBase,
    id: number,
    data: { name?: string; visibility?: Visibility; shared_up?: boolean },
  ) => api.patch<DocFolder>(`${base}folders/${id}/`, data),
  deleteFolder: (base: DocBase, id: number) => api.del(`${base}folders/${id}/`),
  upload: (
    base: DocBase,
    folder: number,
    file: File,
    data: { title: string; date?: string; note?: string },
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', data.title)
    if (data.date) form.append('date', data.date)
    if (data.note) form.append('note', data.note)
    return api.post<DocItem>(`${base}folders/${folder}/documents/`, form)
  },
  update: (
    base: DocBase,
    id: number,
    data: { title?: string; date?: string | null; note?: string; folder?: number },
  ) => api.patch<DocItem>(`${base}${id}/`, data),
  addVersion: (base: DocBase, id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<DocItem>(`${base}${id}/versions/`, form)
  },
  removeVersion: (url: string) => api.del(url),
  trashDocument: (base: DocBase, id: number) => api.del(`${base}${id}/`),
  restore: (base: DocBase, id: number) => api.post<DocItem>(`${base}${id}/restore/`),
  purge: (base: DocBase, id: number) => api.del(`${base}${id}/?final=1`),
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024 / 1024).toFixed(1).replace('.', ',')} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}
