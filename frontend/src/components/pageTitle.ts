// Seitentitel im Browser-Tab (WCAG 2.4.2, UI-Audit NUI-09).
//
// Layout setzt den Titel aus dem gewählten Bereich. Seiten ohne eigenen Bereich
// (z. B. „Seite nicht gefunden“) melden ihren Titel über usePageTitle; der gilt
// dann vorrangig, solange die Seite zu sehen ist.
import { useEffect, useSyncExternalStore } from 'react'

let override: string | null = null
const listeners = new Set<() => void>()

function setOverride(value: string | null) {
  override = value
  for (const l of listeners) l()
}

export function useTitleOverride(): string | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => override,
  )
}

/** Titel einer Seite ohne eigenen Bereich; ohne Token oder Personendaten. */
export function usePageTitle(title: string) {
  useEffect(() => {
    setOverride(title)
    return () => setOverride(null)
  }, [title])
}

export function formatTitle(...parts: (string | null | undefined)[]): string {
  return [...parts, 'HUBIplan'].filter(Boolean).join(' · ')
}
