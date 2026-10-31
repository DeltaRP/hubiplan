// Kleiner fetch-Wrapper: Session-Cookie mitsenden, CSRF-Token setzen, JSON lesen.

export interface ApiResult<T = unknown> {
  status: number
  body: T
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.split('=')[1]) : null
}

async function ensureCsrfToken(): Promise<string> {
  let token = readCookie('csrftoken')
  if (!token) {
    const res = await send('/api/csrf/', { credentials: 'same-origin' }, true)
    const data = parseBody(await res.text()) as { csrfToken?: string }
    token = readCookie('csrftoken') ?? data.csrfToken ?? null
    // Server nicht erreichbar: gleich verständlich melden statt ohne Token weiterzumachen
    if (!token && res.status >= 500) throw new ApiError(res.status, {})
  }
  return token ?? ''
}

/** Wird nach jeder ändernden Anfrage aufgerufen (für Rückgängig). */
export const mutationListeners = new Set<(url: string, status: number, headers: Headers) => void>()

// Anmeldegeneration: Beim Abmelden zählt sie hoch. Antworten auf Anfragen, die vorher
// gestartet wurden, melden sich nicht mehr bei den Zuhörern (Audit 29.10. AUD-FE-S3).
let authGeneration = 0
export function nextAuthGeneration() {
  authGeneration += 1
}
export function currentAuthGeneration() {
  return authGeneration
}

/** Schlüssel für ein Formular: dieselbe Anfrage erneut gesendet wirkt nur einmal. */
export function newRequestKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  const hex = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16))
  hex[12] = '4'
  hex[16] = '89ab'[Math.floor(Math.random() * 4)]
  const h = hex.join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

export async function request<T = unknown>(
  method: Method,
  url: string,
  data?: unknown,
  requestKey?: string,
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') {
    headers['X-CSRFToken'] = await ensureCsrfToken()
  }
  if (requestKey) headers['Idempotency-Key'] = requestKey
  let body: BodyInit | undefined
  if (data instanceof FormData) {
    body = data
  } else if (data !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(data)
  }
  // Lesen und Überschreiben mit denselben Werten darf wiederholt werden, Anlegen nur
  // mit Idempotency-Key (sonst entstünde es womöglich doppelt).
  const retriable = method === 'GET' || method === 'PUT' || method === 'PATCH' || !!requestKey
  const generation = authGeneration
  const res = await send(url, { method, headers, credentials: 'same-origin', body }, retriable)
  if (method !== 'GET' && generation === authGeneration)
    for (const listener of mutationListeners) listener(url, res.status, res.headers)
  return { status: res.status, body: parseBody(await res.text()) as T }
}

/**
 * Wartezeiten in Millisekunden für automatische Wiederholungen, solange der Server
 * kurz nicht erreichbar ist (z. B. während des Ausrollens die Container neu starten).
 * Zusammen etwa 20 Sekunden.
 */
export const retry = { delays: [1000, 2000, 3000, 4000, 5000, 5000] }

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** Fehlerseite eines vorgeschalteten Webservers: Server gerade nicht erreichbar. */
function unreachable(res: Response): boolean {
  if (![502, 503, 504].includes(res.status)) return false
  // Eigene Antworten des Backends sind JSON und werden nicht wiederholt
  return !(res.headers.get('Content-Type') ?? '').includes('json')
}

/**
 * fetch mit verständlicher Meldung, wenn der Server gar nicht antwortet. Mit
 * ``retriable`` wird bei fehlender Verbindung oder Proxy-Fehlerseite (502/503/504)
 * nach kurzer Pause erneut gesendet.
 */
export async function send(url: string, init: RequestInit, retriable = false): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    const last = !retriable || attempt >= retry.delays.length
    let res: Response
    try {
      res = await fetch(url, init)
    } catch {
      if (last) throw new ApiError(0, {})
      await wait(retry.delays[attempt])
      continue
    }
    if (last || !unreachable(res)) return res
    await wait(retry.delays[attempt])
  }
}

/**
 * Antworttext lesen. Nur JSON wird übernommen: Fehlerseiten eines Proxys (z. B.
 * „502 Bad Gateway“ von nginx) sind HTML und dürfen nie roh in einer Meldung landen;
 * dann greift die Meldung zum Statuscode.
 */
export function parseBody(text: string): unknown {
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return {}
  }
}

/** Anfrage, deren Antwort eine Datei ist (z. B. PDF oder Word); Fehler wie bei api.*. */
export async function requestBlob(method: Method, url: string, data?: unknown): Promise<Blob> {
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-CSRFToken'] = await ensureCsrfToken()
  let body: BodyInit | undefined
  if (data instanceof FormData) {
    body = data
  } else if (data !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(data)
  }
  const res = await send(
    url,
    { method, headers, credentials: 'same-origin', body },
    method === 'GET',
  )
  if (res.status >= 400) throw new ApiError(res.status, parseBody(await res.text()))
  return res.blob()
}

/** Datei im Browser speichern. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Fehler der REST-API mit lesbarer Meldung und Feldfehlern. */
export class ApiError extends Error {
  status: number
  fieldErrors: Record<string, string>
  body: unknown

  constructor(status: number, body: unknown) {
    const { message, fieldErrors } = parseErrors(status, body)
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
    this.body = body
  }
}

function flatten(value: unknown): string {
  if (Array.isArray(value)) return value.map(flatten).join(' ')
  if (value && typeof value === 'object') return Object.values(value).map(flatten).join(' ')
  return String(value ?? '')
}

function parseErrors(status: number, body: unknown) {
  const fieldErrors: Record<string, string> = {}
  let message = ''
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    for (const [key, value] of Object.entries(body)) {
      if (key === 'detail' || key === 'non_field_errors') message = flatten(value)
      else fieldErrors[key] = flatten(value)
    }
  } else if (Array.isArray(body)) {
    message = flatten(body)
  }
  if (!message) {
    // Die Meldungen selbst nennen: nicht jede Ansicht zeigt das betroffene Feld an.
    const texts = [...new Set(Object.values(fieldErrors).filter(Boolean))]
    if (texts.length) message = texts.join(' ')
    else message = statusMessage(status)
  }
  return { message, fieldErrors }
}

/** Meldung, wenn die Antwort selbst keine lesbare Meldung enthält. */
export function statusMessage(status: number): string {
  if (status === 0)
    return 'Keine Verbindung zum Server. Bitte die Internetverbindung prüfen und es gleich noch einmal versuchen.'
  if (status === 403) return 'Dafür fehlt dir die Berechtigung.'
  if (status === 404) return 'Nicht gefunden.'
  if (status === 413) return 'Die Datei ist zu groß.'
  if (status === 429) return 'Zu viele Versuche. Bitte einen Moment warten.'
  if (status === 502 || status === 503 || status === 504)
    return 'Der Server ist gerade nicht erreichbar, vielleicht wird er neu gestartet. Bitte in einer Minute noch einmal versuchen.'
  if (status >= 500) return 'Serverfehler. Bitte später erneut versuchen.'
  return 'Das hat nicht geklappt.'
}

async function call<T>(method: Method, url: string, data?: unknown, key?: string): Promise<T> {
  const { status, body } = await request<T>(method, url, data, key)
  if (status >= 400) throw new ApiError(status, body)
  return body
}

export const api = {
  get: <T>(url: string) => call<T>('GET', url),
  post: <T>(url: string, data?: unknown, requestKey?: string) =>
    call<T>('POST', url, data, requestKey),
  patch: <T>(url: string, data: unknown, requestKey?: string) =>
    call<T>('PATCH', url, data, requestKey),
  put: <T>(url: string, data: unknown) => call<T>('PUT', url, data),
  del: (url: string) => call<unknown>('DELETE', url),
  delWith: <T>(url: string, data: unknown) => call<T>('DELETE', url, data),
}

/** Eine Seite einer langen Liste (Protokoll, Postausgang). */
export interface Paged<T> {
  count: number
  page: number
  pages: number
  results: T[]
}

/** Suche, Zeitraum, Filter und Seite für lange Listen. */
export interface ListQuery {
  q?: string
  von?: string
  bis?: string
  seite?: number
  [filter: string]: string | number | undefined
}

export function listParams(query: ListQuery = {}): string {
  const q = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '' && !(key === 'seite' && value === 1)) {
      q.set(key, String(value))
    }
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}
