// Briefbogen der Einheiten und persönliche Word-Briefvorlagen.
import { api, requestBlob } from './client.ts'

export type LetterheadMode = 'own' | 'inherit'
export type LetterForm = 'a' | 'b'
export type LogoPosition = 'right' | 'left' | 'none'
export type FileFormat = 'dotx' | 'docx'

export const FONTS = ['Arial', 'Calibri', 'Cambria', 'Georgia', 'Times New Roman', 'Verdana']

export interface LetterheadFields {
  mode: LetterheadMode
  form: LetterForm
  logo_position: LogoPosition
  tagline: string
  font: string
  salutation: string
  closing: string
  show_bank: boolean
  account: number | null
  show_email: boolean
  show_phone: boolean
  show_website: boolean
  show_board: boolean
  show_register: boolean
  show_social: boolean
}

export interface LetterheadState {
  organization: { id: number; name: string; type: string }
  letterhead: LetterheadFields & { updated_at: string }
  may_have_own: boolean
  owner: { id: number; name: string; is_self: boolean }
  accounts: { id: number; name: string; iban: string; bank: string }[]
  board: { name: string; role: string }[]
  hints: string[]
}

export type ContactKey = 'unit' | 'role' | 'own_email' | 'own_phone' | 'own_address'

export interface SenderContext {
  key: string
  organization: { id: number; name: string; type: string }
  units: { id: number; name: string; is_self: boolean; contact: { email: string; phone: string } }[]
  functions: { key: string; name: string; contact_email: string }[]
  name: string
  own: { email: string; phone: string; address: string[] }
}

export interface LetterChoice {
  unit: number
  context: string
  function: string
  function_text: string
  title: string
  contacts: ContactKey[]
  with_logo: boolean
  format: FileFormat
  downloaded_at: string | null
}

export type LetterNotice =
  | {
      kind: 'outdated'
      unit: { id: number; name: string }
      context: string
      changes: string[]
    }
  | { kind: 'new'; unit: { id: number; name: string }; context: string; function: string }

export interface MyLetterheads {
  contexts: SenderContext[]
  choices: LetterChoice[]
  notices: LetterNotice[]
}

export interface LetterRequest {
  context: string
  unit: number
  function: string
  function_text: string
  title: string
  contacts: ContactKey[]
  with_logo: boolean
  format: FileFormat
  signature: File | null
}

function form(req: LetterRequest): FormData {
  const data = new FormData()
  data.append('context', req.context)
  data.append('unit', String(req.unit))
  data.append('function', req.function)
  data.append('function_text', req.function_text)
  data.append('title', req.title)
  data.append('contacts', req.contacts.join(','))
  data.append('with_logo', req.with_logo ? 'true' : 'false')
  data.append('format', req.format)
  if (req.signature) data.append('signature', req.signature)
  return data
}

const org = (id: number) => `/api/orgs/${id}/letterhead`

export const letterheadApi = {
  get: (id: number) => api.get<LetterheadState>(`${org(id)}/`),
  update: (id: number, data: Partial<LetterheadFields>) =>
    api.patch<LetterheadState>(`${org(id)}/`, data),
  unit: (id: number, unit: number) => api.get<LetterheadState>(`${org(id)}/units/${unit}/`),
  updateUnit: (id: number, unit: number, data: Partial<LetterheadFields>) =>
    api.patch<LetterheadState>(`${org(id)}/units/${unit}/`, data),
  preview: (id: number, unit?: number | null) =>
    requestBlob('GET', `${org(id)}/preview/${unit ? `?unit=${unit}` : ''}`),
  neutral: (id: number, format: FileFormat, unit?: number | null) =>
    requestBlob('GET', `${org(id)}/download/?type=${format}${unit ? `&unit=${unit}` : ''}`),
  publish: (id: number, folder: number, format: FileFormat, unit?: number | null) =>
    api.post<{ document: number; title: string; created: boolean }>(`${org(id)}/publish/`, {
      folder,
      format,
      unit: unit ?? null,
    }),

  mine: () => api.get<MyLetterheads>('/api/me/letterheads/'),
  myPreview: (req: LetterRequest) => requestBlob('POST', '/api/me/letterheads/preview/', form(req)),
  myDownload: (req: LetterRequest) =>
    requestBlob('POST', '/api/me/letterheads/download/', form(req)),
  dismiss: (unit: number, context: string) =>
    api.post<unknown>('/api/me/letterheads/dismiss/', { unit, context }),
}

/** Dateiname wie vom Server (für den Download aus dem Browser). */
export function letterFileName(unitName: string, format: FileFormat): string {
  const base = `Briefvorlage ${unitName}`
    .replace(/[^\p{L}\p{N}\- ]+/gu, '')
    .trim()
    .replace(/\s+/g, '_')
  return `${base.slice(0, 80)}.${format}`
}
