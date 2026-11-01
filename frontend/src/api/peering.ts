// Verbund: Kopplung von Einheiten über mehrere HUBIplan-Instanzen.
import { api } from './client.ts'

export interface PacketChoice {
  key: string
  label: string
  personal: string
  levels: { value: string; label: string }[]
  value: string | null
}

export interface PacketReceived {
  key: string
  label: string
  personal: string
  value: string | null
}

export type CouplingState =
  'requested' | 'pending' | 'active' | 'paused' | 'moving' | 'ended' | 'moved'

export interface PeeringMessage {
  direction: 'out' | 'in'
  seq: number
  kind: string
  persons: number
  state: string
  state_label: string
  attempts: number
  last_error: string
  created_at: string
  done_at: string | null
}

export interface Coupling {
  id: number
  direction: 'parent' | 'child'
  state: CouplingState
  state_label: string
  remote: {
    id: number
    name: string
    logo_url: string | null
    base_url: string
    country: string
    fingerprint: string
  }
  send: PacketChoice[]
  receive: PacketReceived[]
  last_sync_at: string | null
  last_contact_at: string | null
  last_error: string
  error_since: string | null
  queued: number
  received: Received
  invoices: CouplingInvoice[]
  register: RegisterInfo | null
  transfers: RemoteTransfer[]
  /** Wegen fehlender Rechte ausgeblendet: Namen (Mitglieder ansehen), Rechnungen */
  hidden?: ('names' | 'invoices')[]
  options: { circulars_auto?: boolean }
  // Angekündigter Umzug der Gegenstelle (nur im Zustand „moving“)
  move: {
    from: string
    base_url: string
    fingerprint: string
    country: string
    at: string | null
  } | null
  // Notfallwechsel der Schlüssel der Gegenstelle, wartet auf Bestätigung
  keys: { fingerprint: string; at: string | null } | null
  keys_changed_at: string | null
  // Gegenseite möchte mehr senden, als hier angenommen ist
  wants_more: {
    key: string
    label: string
    level: string
    level_label: string
    accepted: string | null
    accepted_label: string
    personal: string
  }[]
  circulars: {
    id: number
    subject: string
    status: 'forwarded' | 'draft' | 'sent' | 'discarded'
    status_label: string
    report: { mail?: number; sent?: number; failed?: number; letter?: number }
    circular_id: number | null
    created_at: string
  }[]
  created_at: string
  activated_at: string | null
  ended_at: string | null
  messages?: PeeringMessage[]
}

export interface Received {
  board?: { roles: { role: string; email: string; holders: { name: string }[] }[] }
  statute?: { valid_from: string; note: string; name: string; download_url?: string }
  events?: number
  members?: {
    level: string
    on: string
    total: number
    counts: { kind: 'active' | 'passive'; birth: string; n: number }[]
  }
  results?: { competitions: ReceivedCompetition[] }
}

/** Endgültige Ergebnisse eines Wettbewerbs der Einheit darüber (Paket „Ergebnisse“) */
export interface ReceivedCompetition {
  uid: string
  title: string
  date: string
  location: string
  scorings: {
    name: string
    kind: string
    field: number | null
    rows: { place: number | null; name: string; value: string; own: boolean }[]
  }[]
}

export interface RemoteTransfer {
  id: number
  role: 'from' | 'to'
  status: 'pending' | 'accepted' | 'rejected' | 'cancelled' | 'failed'
  status_label: string
  name: string
  to_unit: string
  entry_date: string | null
  member_type_name: string
  message: string
  response: string
  created_at: string
  decided_at: string | null
  member_id: number | null
}

export interface RegisterInfo {
  counts: Record<'active' | 'unclear' | 'withdrawn', number>
  unclear: {
    id: number
    last_name: string
    first_name: string
    birth_date: string | null
    candidates: {
      id: number
      name: string
      birth_date: string
      member_number: number | null
      units: string[]
    }[]
  }[]
  conflicts: { id: number; name: string; active_elsewhere: string }[]
  /** Vom Verein gemeldete Änderung an einer Person, die auch woanders Mitglied ist */
  corrections?: {
    id: number
    name: string
    current: Partial<Record<'last_name' | 'first_name' | 'birth_date', string>>
    proposed: Partial<Record<'last_name' | 'first_name' | 'birth_date', string>>
  }[]
}

export interface CouplingInvoice {
  id: number
  incoming: boolean
  number: string
  subject: string
  date: string | null
  due_date: string | null
  total: string
  status: 'open' | 'cancelled'
  status_label: string
  paid: string | null
  settled: boolean
  paid_reported_on: string | null
  booking_id: number | null
  lines: { text: string; detail: string; amount: string }[]
  bank: { holder?: string; iban?: string; bic?: string; bank_name?: string }
  invoice_id: number | null
  download_url: string | null
}

export interface PeeringOverview {
  enabled: boolean
  can_offer: boolean
  can_join: boolean
  instance: { base_url: string; fingerprint: string } | null
  couplings: Coupling[]
}

export interface PeeringPreview {
  remote: {
    name: string
    base_url: string
    country: string
    fingerprint: string
    /** obere Seite: Dachverband oder Verein (ferne Untereinheit, Schritt 8) */
    kind?: 'club' | 'federation'
  }
  send: PacketChoice[]
  receive: { key: string; label: string; personal: string }[]
}

export interface InstanceKeys {
  fingerprint: string
  created: string
  rotated_at: string | null
  previous_until: string | null
  emergency: boolean
  next_rotation: string | null
  peers: { base_url: string; knows_current: boolean }[]
}

export interface PendingPeerKeys {
  id: number
  base_url: string
  fingerprint: string
  at: string | null
  units: string[]
}

export interface PlatformPeering {
  enabled: boolean
  instance: { instance_id: string; base_url: string; fingerprint: string }
  keys: InstanceKeys
  pending_keys: PendingPeerKeys[]
  couplings: {
    id: number
    local: string
    remote: string
    base_url: string
    direction: string
    state: CouplingState
    state_label: string
    last_contact_at: string | null
    last_error: string
  }[]
}

export type Levels = Record<string, string>

const base = (org: number) => `/api/orgs/${org}/peering/`

export interface SsoFinished {
  purpose: SsoPurpose
  next?: string
  mfa_required?: boolean
  user?: { id: number; email: string; display: string }
}

export interface SpinOff {
  id: number
  unit: { id: number; name: string }
  way: 'keep' | 'move'
  way_label: string
  cutoff: string
  state: 'prepared' | 'requested' | 'done' | 'cancelled'
  state_label: string
  export_job: { id: number; status: string; has_file: boolean } | null
  coupling: number | null
  code_expires_at: string | null
  created_at: string
  done_at: string | null
  exited_at?: string | null
  exited_count?: number
}

export interface SpinOffExitCandidate {
  id: number
  name: string
  /** zugleich in diesen anderen Untereinheiten */
  also_in: string[]
}

export interface SpinOffs {
  checklist: Record<'keep' | 'move', { key: string; label: string }[]>
  spin_offs: SpinOff[]
}

export interface SpinOffInput {
  unit: number
  way: 'keep' | 'move'
  cutoff: string
  checklist: Record<string, boolean>
  with_files: boolean
}

export const peeringApi = {
  spinOffs: (org: number) => api.get<SpinOffs>(`${base(org)}spin-offs/`),
  prepareSpinOff: (org: number, data: SpinOffInput) =>
    api.post<SpinOff>(`${base(org)}spin-offs/`, data),
  cancelSpinOff: (org: number, id: number) =>
    api.post<SpinOff>(`${base(org)}spin-offs/${id}/cancel/`),
  spinOffExitPreview: (org: number, id: number) =>
    api.get<{ members: SpinOffExitCandidate[] }>(`${base(org)}spin-offs/${id}/exit/`),
  spinOffExit: (org: number, id: number, exclude: number[]) =>
    api.post<SpinOff>(`${base(org)}spin-offs/${id}/exit/`, { exclude }),
  overview: (org: number) => api.get<PeeringOverview>(base(org)),
  createCode: (org: number) => api.post<{ code: string; expires_at: string }>(`${base(org)}codes/`),
  inspect: (org: number, code: string) =>
    api.post<PeeringPreview>(`${base(org)}inspect/`, { code }),
  join: (org: number, code: string, packets: Levels) =>
    api.post<Coupling>(`${base(org)}couplings/`, { code, packets }),
  detail: (org: number, id: number) => api.get<Coupling>(`${base(org)}couplings/${id}/`),
  setPackets: (org: number, id: number, packets: Levels) =>
    api.patch<Coupling>(`${base(org)}couplings/${id}/`, { packets }),
  setOptions: (org: number, id: number, options: { circulars_auto: boolean }) =>
    api.patch<Coupling>(`${base(org)}couplings/${id}/`, { options }),
  action: (
    org: number,
    id: number,
    action: 'accept' | 'decline' | 'pause' | 'resume' | 'sync' | 'move-decline',
    packets?: Levels,
  ) => api.post<Coupling>(`${base(org)}couplings/${id}/${action}/`, packets ? { packets } : {}),
  confirmMove: (org: number, id: number, fingerprint: string) =>
    api.post<Coupling>(`${base(org)}couplings/${id}/move-confirm/`, { fingerprint }),
  decideMore: (org: number, id: number, key: string, accept: boolean) =>
    api.post<Coupling>(`${base(org)}couplings/${id}/${accept ? 'more-accept' : 'more-decline'}/`, {
      key,
    }),
  end: (org: number, id: number) => api.del(`${base(org)}couplings/${id}/`),
  resolve: (org: number, id: number, member: number, person: number | null) =>
    api.post<Coupling>(`${base(org)}couplings/${id}/members/${member}/resolve/`, { person }),
  decideCorrection: (org: number, id: number, member: number, apply: boolean) =>
    api.post<Coupling>(`${base(org)}couplings/${id}/members/${member}/resolve/`, {
      correction: apply ? 'apply' : 'discard',
    }),
  requestTransfer: (
    org: number,
    id: number,
    data: {
      last_name: string
      first_name: string
      birth_date: string
      member_type: number
      entry_date: string
      message: string
    },
  ) => api.post<Coupling>(`${base(org)}couplings/${id}/transfers/`, data),
  decideTransfer: (
    org: number,
    id: number,
    transfer: number,
    data: { decision: 'exit' | 'change_type' | 'reject'; member_type?: number; response?: string },
  ) => api.post<Coupling>(`${base(org)}couplings/${id}/transfers/${transfer}/decide/`, data),
  reportPaid: (
    org: number,
    id: number,
    invoice: number,
    data: { date: string; account?: number; category?: number },
  ) => api.post<CouplingInvoice>(`${base(org)}couplings/${id}/invoices/${invoice}/paid/`, data),
  moveInspect: (org: number, base_url: string) =>
    api.post<{ base_url: string; fingerprint: string }>(`${base(org)}move/`, { base_url }),
  move: (org: number, base_url: string, fingerprint: string) =>
    api.post<{ done: number; failed: string[] }>(`${base(org)}move/`, { base_url, fingerprint }),
  platform: () => api.get<PlatformPeering>('/api/platform/peering/'),
  peerKeys: (peer: number, action: 'confirm' | 'decline', fingerprint = '') =>
    api.post<{ pending_keys: PendingPeerKeys[] }>(`/api/platform/peering/peers/${peer}/keys/`, {
      action,
      fingerprint,
    }),
  rotateKeys: (mode: 'planned' | 'emergency', confirm: string) =>
    api.post<InstanceKeys>('/api/platform/peering/keys/', { mode, confirm }),
}

/** Freigaben als Wert je Paket (nur eingeschaltete). */
export function levelsOf(choices: PacketChoice[]): Levels {
  const out: Levels = {}
  for (const c of choices) if (c.value) out[c.key] = c.value
  return out
}

// --- Anmelden über eine gekoppelte Instanz (Schritt 7) ---

export interface SsoInstance {
  instance_id: string
  base_url: string
}

export interface SsoAccount {
  login_enabled: boolean
  links: {
    id: number
    base_url: string
    email: string
    created_at: string
    last_used_at: string | null
  }[]
  linkable: SsoInstance[]
  accounts: { id: number; base_url: string; url: string; last_used_at: string | null }[]
}

export type SsoPurpose = 'login' | 'link'

export const ssoApi = {
  choices: () => api.get<SsoInstance[]>('/api/peering/sso/choices/'),
  start: (idp: string, purpose: SsoPurpose, next = '/') =>
    api.post<{ url: string }>('/api/peering/sso/start/', { idp, purpose, next }),
  finish: (token: string) => api.post<SsoFinished>('/api/peering/sso/finish/', { token }),
  // Konten mit Rollen: eigener Code dieser Instanz als zweiter Schritt
  finishCode: (code: string) => api.post<SsoFinished>('/api/peering/sso/finish/', { code }),
  describe: (rp: string) =>
    api.get<{ base_url: string; fingerprint: string; linked: boolean }>(
      `/api/peering/sso/describe/?rp=${encodeURIComponent(rp)}`,
    ),
  issue: (
    rp: string,
    state: string,
    purpose: string,
    confirm?: { password: string; code?: string },
  ) => api.post<{ url: string }>('/api/peering/sso/issue/', { rp, state, purpose, ...confirm }),
  account: () => api.get<SsoAccount>('/api/peering/sso/account/'),
  unlink: (id: number) => api.del(`/api/peering/sso/links/${id}/`),
  forget: (id: number) => api.del(`/api/peering/sso/accounts/${id}/`),
}

/** Zur Seite einer anderen Instanz wechseln (eigene Funktion, damit Tests sie ersetzen können). */
export const leaveTo = {
  go: (url: string) => window.location.assign(url),
}
