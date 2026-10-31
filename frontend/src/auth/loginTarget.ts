/** Ziel nach der Anmeldung: nur eigene Pfade, sonst die Startseite. */
export function loginTarget(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//')) return '/'
  if (from.startsWith('/anmelden')) return '/'
  return from
}

// Ziel über Link-Anmeldung und „Passwort vergessen“ hinweg merken: der Link aus der
// E-Mail öffnet meist einen neuen Tab, daher localStorage, mit Ablauf (UI-Audit NMF-09).
const KEY = 'hubiplan-login-target'
const MAX_AGE = 2 * 60 * 60 * 1000

/** Ziel für die spätere Anmeldung per Link oder nach neuem Passwort merken. */
export function rememberTarget(state: unknown): void {
  const target = loginTarget(state)
  try {
    if (target === '/') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, JSON.stringify({ target, at: Date.now() }))
  } catch {
    // ohne Speicher geht es zur Startseite
  }
}

/** Gemerktes Ziel lesen (geprüft wie loginTarget); `take` löscht es danach. */
export function rememberedTarget(take = false): string {
  try {
    const raw = localStorage.getItem(KEY)
    if (take) localStorage.removeItem(KEY)
    if (!raw) return '/'
    const { target, at } = JSON.parse(raw) as { target?: unknown; at?: unknown }
    if (typeof at !== 'number' || Date.now() - at > MAX_AGE) return '/'
    return loginTarget({ from: target })
  } catch {
    return '/'
  }
}
