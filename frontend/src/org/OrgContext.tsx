import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { orgApi } from '../api/orgs.ts'
import type { OrgSummary } from '../api/orgs.ts'
import { portalApi } from '../api/portal.ts'
import type { DeptSummary, PortalEntry } from '../api/portal.ts'
import { useAuth } from '../auth/AuthContext.tsx'
import { applyTheme } from '../theme/theme.ts'
import type { DatePrecision } from '../components/forms.ts'

const STORAGE_KEY = 'hubiplan.aktiveOrganisation'

// Ein Arbeitsbereich ist eine Organisation (Vorstand), eine Abteilung
// (Abteilungsrolle) oder der eigene Mitgliederbereich.
// Schlüssel: "7" (Organisation), "d:3" (Abteilung), "p:5" (Mitgliederbereich).

interface OrgState {
  orgs: OrgSummary[]
  departments: DeptSummary[]
  portal: PortalEntry[]
  activeKey: string | null
  active: OrgSummary | null
  activeDept: DeptSummary | null
  activePortal: PortalEntry | null
  loading: boolean
  select: (key: number | string) => void
  refresh: () => Promise<void>
  can: (permission: string) => boolean
}

const OrgContext = createContext<OrgState | null>(null)

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function store(key: string) {
  try {
    localStorage.setItem(STORAGE_KEY, key)
  } catch {
    // ohne Speicher geht es auch
  }
}

interface Loaded {
  userId: number
  orgs: OrgSummary[]
  departments: DeptSummary[]
  portal: PortalEntry[]
}

async function loadAll(userId: number): Promise<Loaded> {
  const [orgs, contexts] = await Promise.all([
    orgApi.mine(),
    portalApi.contexts().catch(() => ({ departments: [], portal: [] })),
  ])
  return { userId, orgs, departments: contexts.departments, portal: contexts.portal }
}

export function OrgProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  // Liste merkt sich, für welchen Benutzer sie geladen wurde – nach einem
  // Benutzerwechsel erscheinen so nie kurz die Organisationen des vorherigen.
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [activeKey, setActiveKey] = useState<string | null>(readStored)
  const userId = user?.id ?? null

  const refresh = useCallback(async () => {
    if (userId === null) return
    setLoaded(await loadAll(userId))
  }, [userId])

  useEffect(() => {
    if (userId === null) return
    let alive = true
    loadAll(userId)
      .then((data) => alive && setLoaded(data))
      .catch(() => alive && setLoaded({ userId, orgs: [], departments: [], portal: [] }))
    return () => {
      alive = false
    }
  }, [userId])

  const loading = userId !== null && loaded?.userId !== userId
  const current = useMemo(
    () =>
      loaded && loaded.userId === userId
        ? loaded
        : {
            orgs: [] as OrgSummary[],
            departments: [] as DeptSummary[],
            portal: [] as PortalEntry[],
          },
    [loaded, userId],
  )

  // Gespeicherten Bereich nur nehmen, wenn er noch erlaubt ist
  const resolved = useMemo(() => {
    const { orgs, departments, portal } = current
    const key = activeKey ?? ''
    if (key.startsWith('d:')) {
      const d = departments.find((x) => `d:${x.id}` === key)
      if (d) return { key, org: null, dept: d, portal: null }
    } else if (key.startsWith('p:')) {
      const p = portal.find((x) => `p:${x.id}` === key)
      if (p) return { key, org: null, dept: null, portal: p }
    } else {
      const o = orgs.find((x) => String(x.id) === key)
      if (o) return { key, org: o, dept: null, portal: null }
    }
    if (orgs[0]) return { key: String(orgs[0].id), org: orgs[0], dept: null, portal: null }
    if (departments[0])
      return { key: `d:${departments[0].id}`, org: null, dept: departments[0], portal: null }
    if (portal[0]) return { key: `p:${portal[0].id}`, org: null, dept: null, portal: portal[0] }
    return { key: null, org: null, dept: null, portal: null }
  }, [current, activeKey])

  useEffect(() => {
    const theme = resolved.org?.theme ?? resolved.dept?.theme ?? resolved.portal?.theme ?? null
    applyTheme(theme)
  }, [resolved])

  const select = useCallback((key: number | string) => {
    const k = String(key)
    setActiveKey(k)
    store(k)
  }, [])

  const active = resolved.org
  const can = useCallback(
    (permission: string) => !!active && active.permissions.includes(permission),
    [active],
  )

  const value = useMemo(
    () => ({
      orgs: current.orgs,
      departments: current.departments,
      portal: current.portal,
      activeKey: resolved.key,
      active,
      activeDept: resolved.dept,
      activePortal: resolved.portal,
      loading,
      select,
      refresh,
      can,
    }),
    [current, resolved, active, loading, select, refresh, can],
  )
  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>
}

/** Wie useOrg, aber ohne Fehler außerhalb des OrgProviders (dann null). */
// oxlint-disable-next-line react/only-export-components
export function useOptionalOrg(): OrgState | null {
  return useContext(OrgContext)
}

// oxlint-disable-next-line react/only-export-components
export function useOrg(): OrgState {
  const ctx = useContext(OrgContext)
  if (!ctx) throw new Error('useOrg muss innerhalb von OrgProvider genutzt werden.')
  return ctx
}

/** Aktive Organisation; nur in Seiten verwenden, die eine voraussetzen. */
// oxlint-disable-next-line react/only-export-components
export function useActiveOrg(): OrgSummary {
  const { active } = useOrg()
  if (!active) throw new Error('Keine aktive Organisation.')
  return active
}

/** Aktive Abteilung; nur im Abteilungsbereich verwenden. */
// oxlint-disable-next-line react/only-export-components
export function useActiveDept(): DeptSummary {
  const { activeDept } = useOrg()
  if (!activeDept) throw new Error('Keine aktive Abteilung.')
  return activeDept
}

// Genauigkeit für Mitgliedschaftsdaten im aktiven Arbeitsbereich.
// oxlint-disable-next-line react/only-export-components
export function useDatePrecision(): DatePrecision {
  const { active, activeDept, activePortal } = useOrg()
  return (
    activeDept?.date_precision ?? activePortal?.date_precision ?? active?.date_precision ?? 'day'
  )
}
