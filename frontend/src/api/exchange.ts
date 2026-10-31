// Import und Export (Meilenstein 5).
import { api } from './client.ts'

export interface ColumnOption {
  key: string
  label: string
}

export interface ExportJob {
  id: number
  kind: 'members' | 'jubilees' | 'federation_members'
  file_format: 'xlsx' | 'pdf'
  columns: string[]
  filters: Record<string, unknown>
  orientation: 'portrait' | 'landscape'
  title: string
  status: 'pending' | 'running' | 'done' | 'failed'
  status_label: string
  file_name: string
  row_count: number
  error: string
  created_at: string
  /** Datei wird danach gelöscht (7 Tage ab Fertigstellung) */
  keep_until?: string | null
}

export interface ExportTemplate {
  id: number
  name: string
  kind: string
  columns: string[]
  filters: Record<string, unknown>
  file_format: string
  orientation: string
}

export interface ImportTarget {
  key: string
  label: string
  value_mapped: boolean
}

export interface PreviewRow {
  rows: number[]
  name: string
  birth_date: string | null
  periods: number
  status: 'ok' | 'error' | 'duplicate'
  messages: string[]
}

export interface ImportJob {
  id: number
  file_name: string
  status: 'uploaded' | 'validating' | 'validated' | 'importing' | 'imported' | 'undone' | 'failed'
  status_label: string
  headers: string[]
  sample: unknown[][]
  row_count: number
  mapping: Record<string, string>
  value_mapping: Record<string, Record<string, string>>
  options: { link_duplicates?: boolean }
  preview: PreviewRow[]
  counts: Record<string, number>
  error: string
  created_at: string
  imported_at: string | null
  /** Datei, Vorschau und „Rückgängig“ nach 30 Tagen gelöscht */
  purged_at: string | null
  /** Protokoll und Rücknahme bleiben bis dahin (30 Tage ab dem letzten Schritt) */
  keep_until?: string | null
  has_error_file: boolean
  undo_blockers: string[]
}

export interface ImportTemplate {
  id: number
  name: string
  mapping: Record<string, string>
  value_mapping: Record<string, Record<string, string>>
}

const base = (org: number) => `/api/orgs/${org}`

export const exchangeApi = {
  columns: (org: number) => api.get<Record<string, ColumnOption[]>>(`${base(org)}/export-columns/`),
  startExport: (org: number, data: Partial<ExportJob>) =>
    api.post<ExportJob>(`${base(org)}/exports/`, data),
  exportJob: (org: number, id: number) => api.get<ExportJob>(`${base(org)}/exports/${id}/`),
  downloadUrl: (org: number, id: number) => `${base(org)}/exports/${id}/download/`,
  exportTemplates: (org: number) => api.get<ExportTemplate[]>(`${base(org)}/export-templates/`),
  saveExportTemplate: (org: number, data: Partial<ExportTemplate>) =>
    api.post<ExportTemplate>(`${base(org)}/export-templates/`, data),
  deleteExportTemplate: (org: number, id: number) =>
    api.del(`${base(org)}/export-templates/${id}/`),

  targets: (org: number) => api.get<ImportTarget[]>(`${base(org)}/import-targets/`),
  imports: (org: number) => api.get<ImportJob[]>(`${base(org)}/imports/`),
  upload: (org: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<ImportJob>(`${base(org)}/imports/`, form)
  },
  importJob: (org: number, id: number) => api.get<ImportJob>(`${base(org)}/imports/${id}/`),
  configure: (org: number, id: number, data: Partial<ImportJob>) =>
    api.patch<ImportJob>(`${base(org)}/imports/${id}/`, data),
  values: (org: number, id: number, target: string) =>
    api.get<string[]>(`${base(org)}/imports/${id}/values/?ziel=${target}`),
  validate: (org: number, id: number) =>
    api.post<ImportJob>(`${base(org)}/imports/${id}/validate/`),
  run: (org: number, id: number) => api.post<ImportJob>(`${base(org)}/imports/${id}/run/`),
  undo: (org: number, id: number) => api.post<ImportJob>(`${base(org)}/imports/${id}/undo/`),
  errorFileUrl: (org: number, id: number) => `${base(org)}/imports/${id}/errors/`,
  importTemplates: (org: number) => api.get<ImportTemplate[]>(`${base(org)}/import-templates/`),
  saveImportTemplate: (org: number, data: Partial<ImportTemplate>) =>
    api.post<ImportTemplate>(`${base(org)}/import-templates/`, data),
}

/** Wartet abbrechbar, bis `ms` vergangen sind oder `signal` abbricht. */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve()
    const timer = setTimeout(done, ms)
    function done() {
      clearTimeout(timer)
      signal?.removeEventListener('abort', done)
      resolve()
    }
    signal?.addEventListener('abort', done)
  })
}

/**
 * Wartet, bis ein Hintergrund-Job fertig ist. Fragt zuerst jede Sekunde nach, dann
 * seltener (bis alle 5 s), pausiert in einem verborgenen Tab und hört auf, sobald
 * `signal` abbricht (z. B. weil die Seite verlassen wurde). Gibt den zuletzt
 * bekannten Stand zurück.
 */
export async function waitFor<T extends { status: string }>(
  load: () => Promise<T>,
  running: string[],
  timeoutMs = 120000,
  signal?: AbortSignal,
): Promise<T> {
  const start = Date.now()
  let delay = 1000
  let job = await load()
  while (running.includes(job.status) && Date.now() - start < timeoutMs) {
    await sleep(delay, signal)
    if (signal?.aborted) break
    if (typeof document !== 'undefined' && document.hidden) continue
    job = await load()
    delay = Math.min(5000, Math.round(delay * 1.5))
  }
  return job
}
