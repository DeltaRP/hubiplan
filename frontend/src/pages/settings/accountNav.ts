// Mein Konto: Unterpunkte in der Seitenleiste (wie bei „Mitglieder“).
export const ACCOUNT_PATH = '/mein-konto'

export const ACCOUNT_SECTIONS = [
  { to: '/mein-konto', label: 'Profil' },
  { to: '/mein-konto/anmeldung', label: 'Anmeldung & Sicherheit' },
  { to: '/mein-konto/app', label: 'App & andere Instanzen' },
  { to: '/mein-konto/briefvorlage', label: 'Briefvorlage & Unterschrift' },
] as const

/** Gehört der Pfad zu „Mein Konto“? */
export function isAccountPath(pathname: string): boolean {
  return pathname === ACCOUNT_PATH || pathname.startsWith(`${ACCOUNT_PATH}/`)
}

/** Name des Unterpunkts zum Pfad, sonst null */
export function accountSectionLabel(pathname: string): string | null {
  return ACCOUNT_SECTIONS.find((s) => s.to === pathname)?.label ?? null
}
