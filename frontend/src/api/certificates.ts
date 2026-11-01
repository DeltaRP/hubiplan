// Wettbewerbe Schritt 6: Urkundenvorlagen, Urkunden und Startkarten.
import { api } from './client.ts'

export interface Signer {
  name: string
  function: string
}

export interface CertificateTemplate {
  id: number
  name: string
  heading: string
  /** Text mit Platzhaltern; „# “ am Zeilenanfang: groß und fett */
  text: string
  landscape: boolean
  show_logo: boolean
  place_line: string
  signers: Signer[]
  has_background: boolean
}

const base = (org: number) => `/api/orgs/${org}/competitions/`
const tpl = (org: number) => `${base(org)}certificate-templates/`

export const certificatesApi = {
  list: (org: number) => api.get<CertificateTemplate[]>(tpl(org)),
  create: (org: number, data: Partial<CertificateTemplate>) =>
    api.post<CertificateTemplate>(tpl(org), data),
  update: (org: number, id: number, data: Partial<CertificateTemplate>) =>
    api.patch<CertificateTemplate>(`${tpl(org)}${id}/`, data),
  remove: (org: number, id: number) => api.del(`${tpl(org)}${id}/`),
  uploadBackground: (org: number, id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<CertificateTemplate>(`${tpl(org)}${id}/background/`, form)
  },
  removeBackground: (org: number, id: number) =>
    api.del(`${tpl(org)}${id}/background/`) as Promise<unknown>,
  previewUrl: (org: number, id: number) => `${tpl(org)}${id}/preview/`,
  certificatesUrl: (
    org: number,
    comp: number,
    opts: { template?: number | null; upTo: number; scoring?: number | null; signature: boolean },
  ) => {
    const q = new URLSearchParams({ bis: String(opts.upTo) })
    if (opts.template) q.set('vorlage', String(opts.template))
    if (opts.scoring) q.set('wertung', String(opts.scoring))
    if (opts.signature) q.set('unterschrift', '1')
    return `${base(org)}${comp}/certificates/?${q}`
  },
  startCardsUrl: (org: number, comp: number, labels: boolean, order: string) =>
    `${base(org)}${comp}/start-cards/?art=${labels ? 'aufkleber' : 'karten'}&sortierung=${order}`,
}
