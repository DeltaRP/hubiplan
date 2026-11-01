// Ämter: heutige und frühere Inhaber der Rollen (jahresgenau), frühere Inhaber ohne Konto.
import { api } from './client.ts'

export interface OfficeHolder {
  id: number
  role: number
  name: string
  person: number | null
  from_year: number
  until_year: number | null
  current: boolean
  /** freier Eintrag eines früheren Inhabers (hier änderbar) */
  former_entry: boolean
  /** freier Name darf auf der Webseite erscheinen (nur mit Häkchen) */
  name_public: boolean
}

export interface Office {
  id: number
  name: string
  unit: number | null
  unit_name: string | null
  in_chronicle: boolean
  /** Vorstandsrolle */
  is_board: boolean
  holders: OfficeHolder[]
}

export interface OfficeEntryInput {
  role: number
  name: string
  person: number | null
  from_year: number | null
  until_year: number | null
  name_public: boolean
}

export interface OfficeImportRow {
  line: number
  role: string
  role_id: number | null
  unit: string
  unit_id: number | null
  name: string
  person_id: number | null
  candidates: { id: number; name: string; birth_year: number | null }[]
  from_year: number | null
  until_year: number | null
  duplicate: boolean
  errors: string[]
}

const base = (org: number) => `/api/orgs/${org}/offices/`

export const officesApi = {
  list: (org: number) => api.get<Office[]>(base(org)),
  create: (org: number, data: OfficeEntryInput) => api.post<OfficeHolder>(base(org), data),
  update: (org: number, id: number, data: OfficeEntryInput) =>
    api.put<OfficeHolder>(`${base(org)}${id}/`, data),
  remove: (org: number, id: number) => api.del(`${base(org)}${id}/`),
  importPreview: (org: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ rows: OfficeImportRow[]; new_roles: string[] }>(
      `${base(org)}import/preview/`,
      form,
    )
  },
  importRows: (
    org: number,
    rows: {
      role: string
      unit_id: number | null
      name: string
      person_id: number | null
      from_year: number
      until_year: number
    }[],
    requestKey?: string,
  ) =>
    api.post<{ created: number; roles_created: string[] }>(
      `${base(org)}import/`,
      { rows },
      requestKey,
    ),
}
