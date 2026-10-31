// Vollständiger Export und Import aus einer Exportdatei (Datenübernahme).
import { api } from './client.ts'

export interface Candidate {
  id: number
  name: string
  birth_date: string
  member_number: number | null
  clubs: { name: string; current: boolean }[]
  member_here: boolean
}

export interface Duplicate {
  person: number
  name: string
  birth_date: string
  candidates: Candidate[]
  choice: string
  fixed: boolean
}

export interface ImportPreview {
  /** unit: Untereinheit wird auf der Plattform eigene Einheit (Verbund, Schritt 8b) */
  kind: 'organization' | 'department' | 'unit'
  type: 'federation' | 'club' | 'department'
  name: string
  source: { type?: string; name?: string }
  exported_at: string | null
  with_files: boolean
  summary: Record<string, number>
  /** Anzahl je Datenklasse (Umzugsbericht) */
  classes?: Record<string, number>
  /** Bewusst nicht mitgenommen */
  not_included?: string[]
  errors: string[]
  error_count: number
  warnings: string[]
  warning_count: number
  duplicates: Duplicate[]
  users: { total: number; existing: number; new: number }
}

export interface TransferJob {
  id: number
  direction: 'export' | 'import'
  kind: 'organization' | 'department'
  status: 'pending' | 'running' | 'checked' | 'done' | 'failed'
  status_label: string
  with_files: boolean
  file_name: string
  size: number
  has_file: boolean
  summary: Record<string, unknown>
  preview: ImportPreview | Record<string, never>
  decisions: { persons?: Record<string, string> }
  options: { name?: string; invite?: boolean; board_email?: string }
  error: string
  subject: { id: number; name: string } | null
  department: { id: number; name: string } | null
  result_organization: { id: number; name: string } | null
  created_by: string | null
  created_at: string
  finished_at: string | null
  expires_at: string
}

export interface ImportOptions {
  name?: string
  invite?: boolean
  board_email?: string
  street?: string
  postal_code?: string
  city?: string
  persons?: Record<string, string>
}

/** Basis-URL: Organisation, Abteilung oder Plattform. */
export type TransferBase = { org: number } | { dept: number } | { platform: true }

function base(b: TransferBase): string {
  if ('org' in b) return `/api/orgs/${b.org}/datatransfer`
  if ('dept' in b) return `/api/depts/${b.dept}/datatransfer`
  return '/api/platform/datatransfer'
}

export const transferApi = {
  exports: (b: TransferBase) => api.get<TransferJob[]>(`${base(b)}/exports/`),
  exportJob: (b: TransferBase, id: number) => api.get<TransferJob>(`${base(b)}/exports/${id}/`),
  startExport: (
    b: TransferBase,
    data: { kind?: string; department?: number; organization?: number; with_files: boolean },
  ) => api.post<TransferJob>(`${base(b)}/exports/`, data),
  downloadUrl: (b: TransferBase, id: number) => `${base(b)}/exports/${id}/download/`,
  imports: (b: TransferBase) => api.get<TransferJob[]>(`${base(b)}/imports/`),
  importJob: (b: TransferBase, id: number) => api.get<TransferJob>(`${base(b)}/imports/${id}/`),
  upload: (b: TransferBase, file: File, options: ImportOptions) => {
    const form = new FormData()
    form.append('file', file)
    if (options.name) form.append('name', options.name)
    if (options.invite) form.append('invite', 'true')
    if (options.board_email) form.append('board_email', options.board_email)
    for (const key of ['street', 'postal_code', 'city'] as const) {
      const value = options[key]
      if (value) form.append(key, value)
    }
    return api.post<TransferJob>(`${base(b)}/imports/`, form)
  },
  recheck: (b: TransferBase, id: number, options: ImportOptions) =>
    api.patch<TransferJob>(`${base(b)}/imports/${id}/`, options),
  run: (b: TransferBase, id: number) => api.post<TransferJob>(`${base(b)}/imports/${id}/run/`),
  createClub: (fed: number, data: Record<string, unknown>) =>
    api.post<{ id: number; name: string; invited: number }>(
      `/api/orgs/${fed}/federation/clubs/new/`,
      data,
    ),
}
