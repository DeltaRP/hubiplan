// Hilfe: geladene Einträge, Sichtbarkeit nach Modulen und Rechten, offene Seitenhilfe.
//
// Die Rechte sind die wirksamen der gewählten Einheit. In der Ansicht als Rolle liefert
// der Server dort schon die Schnittmenge, die Hilfe zeigt dann die Hilfe dieser Rolle.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { helpApi } from '../api/help.ts'
import type { OrgHelp } from '../api/help.ts'
import { lang } from '../i18n/index.ts'
import { useOptionalOrg } from '../org/OrgContext.tsx'
import { loadHelp, missingRights, visibleFor } from './content.ts'
import type { HelpEntry } from './content.ts'

export interface HelpState {
  /** null: noch nicht geladen */
  entries: HelpEntry[] | null
  failed: boolean
  load: () => void
  /** sichtbar für diese Person (Modul und Recht) */
  visible: (e: HelpEntry) => boolean
  /** Rechte, die für den Eintrag fehlen (leer: sichtbar oder Modul aus, dann gar nicht zeigen) */
  missing: (e: HelpEntry) => string[]
  panelOpen: boolean
  setPanelOpen: (open: boolean) => void
  /** Angaben der gewählten Einheit (Ansprechpartner, Hinweise, Rechte); null: keine oder lädt */
  org: OrgHelp | null
  orgId: number | null
  setOrg: (data: OrgHelp) => void
  /** abgehakte erste Schritte; null: noch nicht geladen */
  done: Set<string> | null
  toggleDone: (key: string) => void
  /** Ansicht als Rolle: Name der Rolle (Abhaken gesperrt) */
  previewRole: string | null
  /** In der Leiste gewählte Anleitung; gilt nur auf der Seite, auf der sie gewählt wurde */
  panelGuide: { key: string; path: string } | null
  /** Anleitung in der Leiste zeigen (öffnet sie); null: zurück zur Seitenhilfe */
  openGuide: (guide: { key: string; path: string } | null) => void
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
  const orgState = useOptionalOrg()
  const [entries, setEntries] = useState<HelpEntry[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [panelOpen, setPanelOpenRaw] = useState(false)
  const [panelGuide, setPanelGuide] = useState<{ key: string; path: string } | null>(null)
  // Jedes Öffnen beginnt mit der Seitenübersicht
  const setPanelOpen = useCallback((open: boolean) => {
    setPanelGuide(null)
    setPanelOpenRaw(open)
  }, [])
  const openGuide = useCallback((guide: { key: string; path: string } | null) => {
    setPanelGuide(guide)
    if (guide) setPanelOpenRaw(true)
  }, [])
  const [orgData, setOrgData] = useState<{ id: number; data: OrgHelp } | null>(null)
  const [done, setDone] = useState<Set<string> | null>(null)

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

  const active = orgState?.active ?? null
  const dept = active ? null : (orgState?.activeDept ?? null)
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
  const missing = useCallback(
    (e: HelpEntry) => {
      if (!active || active.type === 'platform') return []
      const perms: readonly string[] = active.permissions ?? []
      return missingRights(
        e,
        (m) => (m === 'platform' ? false : !!active.modules?.includes(m)),
        (r) => perms.includes(r),
      )
    },
    [active],
  )

  // Angaben der Einheit und abgehakte Schritte erst laden, wenn jemand die Hilfe nutzt
  const inUse = !!entries
  const activeId = active && active.type !== 'platform' ? active.id : null
  useEffect(() => {
    if (!inUse || activeId === null) return
    let stale = false
    helpApi.org(activeId).then(
      (data) => !stale && setOrgData({ id: activeId, data }),
      () => undefined,
    )
    return () => {
      stale = true
    }
  }, [inUse, activeId])
  useEffect(() => {
    if (!inUse || done) return
    helpApi.done().then(
      (r) => setDone(new Set(r.help_done)),
      () => setDone(new Set()),
    )
  }, [inUse, done])
  const previewRole = active?.role_preview?.active?.name ?? null
  const toggleDone = useCallback(
    (key: string) => {
      if (previewRole || !done) return
      const was = done.has(key)
      const next = new Set(done)
      if (was) next.delete(key)
      else next.add(key)
      setDone(next)
      ;(was ? helpApi.uncheck(key) : helpApi.check(key)).then(
        (r) => setDone(new Set(r.help_done)),
        () => setDone(done),
      )
    },
    [done, previewRole],
  )
  const setOrg = useCallback(
    (data: OrgHelp) => activeId !== null && setOrgData({ id: activeId, data }),
    [activeId],
  )

  // „?“ öffnet und schließt die Seitenhilfe
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return
      e.preventDefault()
      setPanelGuide(null)
      setPanelOpenRaw((o) => !o)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (panelOpen && !entries) fetchEntries()
  }, [panelOpen, entries, fetchEntries])

  const org = orgData && orgData.id === activeId ? orgData.data : null
  const value = useMemo(
    () => ({
      entries,
      failed,
      load,
      visible,
      missing,
      panelOpen,
      setPanelOpen,
      org,
      orgId: activeId,
      setOrg,
      done,
      toggleDone,
      previewRole,
      panelGuide,
      openGuide,
    }),
    [
      entries,
      failed,
      load,
      visible,
      missing,
      panelOpen,
      org,
      activeId,
      setOrg,
      done,
      toggleDone,
      previewRole,
      panelGuide,
      openGuide,
      setPanelOpen,
    ],
  )
  return <HelpContext.Provider value={value}>{children}</HelpContext.Provider>
}
