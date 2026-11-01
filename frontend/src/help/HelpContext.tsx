// Hilfe: geladene Einträge, Sichtbarkeit nach Modulen und Rechten, offene Seitenhilfe.
//
// Die Rechte sind die wirksamen der gewählten Einheit. In der Ansicht als Rolle liefert
// der Server dort schon die Schnittmenge, die Hilfe zeigt dann die Hilfe dieser Rolle.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { lang } from '../i18n/index.ts'
import { useOptionalOrg } from '../org/OrgContext.tsx'
import { loadHelp, visibleFor } from './content.ts'
import type { HelpEntry } from './content.ts'

export interface HelpState {
  /** null: noch nicht geladen */
  entries: HelpEntry[] | null
  failed: boolean
  load: () => void
  /** sichtbar für diese Person (Modul und Recht) */
  visible: (e: HelpEntry) => boolean
  panelOpen: boolean
  setPanelOpen: (open: boolean) => void
}

const HelpContext = createContext<HelpState | null>(null)

// oxlint-disable-next-line react/only-export-components
export function useHelp(): HelpState | null {
  return useContext(HelpContext)
}

/** Ist das Ziel eine Eingabe? Dann ist „?“ ein Zeichen und keine Taste für die Hilfe. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  return (
    el.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) ||
    !!el.closest?.('[contenteditable="true"]')
  )
}

export function HelpProvider({ children }: { children: ReactNode }) {
  const org = useOptionalOrg()
  const [entries, setEntries] = useState<HelpEntry[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)

  const fetchEntries = useCallback(() => {
    loadHelp(lang()).then(
      (list) => {
        setEntries(list)
        setFailed(false)
      },
      () => setFailed(true),
    )
  }, [])
  const load = useCallback(() => {
    setFailed(false)
    fetchEntries()
  }, [fetchEntries])

  const active = org?.active ?? null
  const dept = active ? null : (org?.activeDept ?? null)
  const visible = useCallback(
    (e: HelpEntry) => {
      const perms: readonly string[] = active?.permissions ?? dept?.permissions ?? []
      const isPlatform = active?.type === 'platform'
      return visibleFor(
        e,
        (m) => (m === 'platform' ? isPlatform : !!active?.modules?.includes(m)),
        (r) => (r === 'platform.manage' ? isPlatform : perms.includes(r)),
      )
    },
    [active, dept],
  )

  // „?“ öffnet und schließt die Seitenhilfe
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return
      e.preventDefault()
      setPanelOpen((o) => !o)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (panelOpen && !entries) fetchEntries()
  }, [panelOpen, entries, fetchEntries])

  const value = useMemo(
    () => ({ entries, failed, load, visible, panelOpen, setPanelOpen }),
    [entries, failed, load, visible, panelOpen],
  )
  return <HelpContext.Provider value={value}>{children}</HelpContext.Provider>
}
