// Anbindung an die allauth-Headless-API (Anmeldung, 2FA, Abmeldung).
// Doku der Endpunkte: http://localhost:8000/_allauth/openapi.html
import { ApiError, request } from './client.ts'

const BASE = '/_allauth/browser/v1'

export interface User {
  id: number
  email: string
  display: string
  // Noch mit dem ausgegebenen Startpasswort angemeldet: erst eigenes Passwort festlegen
  must_change_password?: boolean
  // Pflicht-2FA: bis dahin einrichten, danach ruhen Rollenverwaltung, Exporte und Kasse
  mfa_required_by?: string
  mfa_overdue?: boolean
}

interface Flow {
  id: string
  is_pending?: boolean
}

interface AuthBody {
  status: number
  data?: { user?: User; flows?: Flow[] }
  meta?: { is_authenticated?: boolean }
  errors?: { message: string; param?: string }[]
}

export type LoginResult =
  { kind: 'ok'; user: User } | { kind: 'mfa' } | { kind: 'error'; message: string }

function errorMessage(body: AuthBody, fallback: string): string {
  return body.errors?.map((e) => e.message).join(' ') || fallback
}

function pendingFlow(body: AuthBody): string | undefined {
  return body.data?.flows?.find((f) => f.is_pending)?.id
}

function toLoginResult(status: number, body: AuthBody, fallback: string): LoginResult {
  if (status === 200 && body.data?.user) return { kind: 'ok', user: body.data.user }
  if (status === 401 && pendingFlow(body) === 'mfa_authenticate') return { kind: 'mfa' }
  if (status === 429) return { kind: 'error', message: 'Zu viele Versuche. Bitte später erneut.' }
  return { kind: 'error', message: errorMessage(body, fallback) }
}

export async function getSession(): Promise<User | null> {
  const { status, body } = await request<AuthBody>('GET', `${BASE}/auth/session`)
  return status === 200 && body.data?.user ? body.data.user : null
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const { status, body } = await request<AuthBody>('POST', `${BASE}/auth/login`, {
    email,
    password,
  })
  return toLoginResult(status, body, 'Anmeldung fehlgeschlagen.')
}

export async function authenticateMfa(code: string): Promise<LoginResult> {
  const { status, body } = await request<AuthBody>('POST', `${BASE}/auth/2fa/authenticate`, {
    code,
  })
  return toLoginResult(status, body, 'Der Code ist ungültig.')
}

export async function logout(): Promise<void> {
  const { status, body } = await request('DELETE', `${BASE}/auth/session`)
  // allauth antwortet nach erfolgreicher Abmeldung mit 401 (keine Sitzung mehr)
  if (status !== 401 && status !== 200) throw new ApiError(status, body)
}

// --- 2FA verwalten ---

export type TotpState = { active: true } | { active: false; secret: string; totpUrl: string }

export async function getTotp(): Promise<TotpState> {
  const { status, body } = await request<{ meta?: { secret: string; totp_url: string } }>(
    'GET',
    `${BASE}/account/authenticators/totp`,
  )
  if (status === 200) return { active: true }
  // 404 heißt „noch nicht eingerichtet“; alles andere ist ein Fehler, kein „inaktiv“
  if (status !== 404) throw new ApiError(status, body)
  return { active: false, secret: body.meta?.secret ?? '', totpUrl: body.meta?.totp_url ?? '' }
}

export type ChangeResult =
  { kind: 'ok' } | { kind: 'reauthenticate' } | { kind: 'error'; message: string }

async function securityChange(
  method: 'POST' | 'DELETE',
  url: string,
  data?: unknown,
): Promise<ChangeResult> {
  const { status, body } = await request<AuthBody>(method, url, data)
  if (status === 200) return { kind: 'ok' }
  // Für Sicherheitsänderungen verlangt allauth eine frische Passwortbestätigung.
  if (status === 401) return { kind: 'reauthenticate' }
  return { kind: 'error', message: errorMessage(body, 'Das hat nicht geklappt.') }
}

export function activateTotp(code: string): Promise<ChangeResult> {
  return securityChange('POST', `${BASE}/account/authenticators/totp`, { code })
}

export function deactivateTotp(): Promise<ChangeResult> {
  return securityChange('DELETE', `${BASE}/account/authenticators/totp`)
}

export async function reauthenticate(password: string): Promise<ChangeResult> {
  const { status, body } = await request<AuthBody>('POST', `${BASE}/auth/reauthenticate`, {
    password,
  })
  if (status === 200) return { kind: 'ok' }
  return { kind: 'error', message: errorMessage(body, 'Passwort ist falsch.') }
}

export async function getRecoveryCodes(): Promise<string[]> {
  const { status, body } = await request<{ data?: { unused_codes?: string[] } }>(
    'GET',
    `${BASE}/account/authenticators/recovery-codes`,
  )
  // Fehler nicht als „keine Codes“ ausgeben (Gesamtaudit 30.10., WEB-F01)
  if (status !== 200) throw new ApiError(status, body)
  return body.data?.unused_codes ?? []
}
