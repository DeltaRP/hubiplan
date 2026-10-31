// Unterpunkte einer Seite (früher Reiter im Inhalt) erscheinen in der Seitenleiste
// unter dem passenden Menüpunkt (Ralf 2026-10-28: Unterpunkte immer in der Seitenleiste;
// UX-Audit 31.10. W09). Seiten rufen weiter <Tabs items={…} /> auf; innerhalb des
// App-Rahmens meldet Tabs die Punkte hier an und zeichnet selbst nichts.
import { createContext, useContext, useLayoutEffect, useId } from 'react'

export interface SubNavItem {
  to: string
  label: string
}

export interface SubNavApi {
  set: (id: string, items: SubNavItem[] | null) => void
}

export const SubNavContext = createContext<SubNavApi | null>(null)

/** Meldet Unterpunkte an; true, wenn die Seitenleiste sie zeigt. */
export function useSubNav(items: SubNavItem[]): boolean {
  const api = useContext(SubNavContext)
  const id = useId()
  const key = JSON.stringify(items)
  useLayoutEffect(() => {
    if (!api) return
    api.set(id, JSON.parse(key) as SubNavItem[])
    return () => api.set(id, null)
  }, [api, id, key])
  return !!api
}

export interface NavNode {
  to: string
  label: string
  /** NavLink nur bei genau diesem Pfad aktiv */
  end: boolean
  children: NavNode[]
}

const covers = (parent: string, path: string) => path === parent || path.startsWith(`${parent}/`)

/**
 * Baut den Baum unter einem Menüpunkt: feste Unterpunkte des Moduls, darunter die
 * angemeldeten Unterpunkte der Seiten. Jede Gruppe hängt am tiefsten vorhandenen Punkt,
 * dessen Pfad ihren ersten Eintrag umfasst (sonst direkt am Modul).
 */
export function buildNavTree(
  modulePath: string,
  fixed: SubNavItem[],
  registered: SubNavItem[][],
): NavNode[] {
  const root: NavNode = { to: modulePath, label: '', end: false, children: [] }
  root.children = fixed.map((c) => ({ ...c, end: c.to === modulePath, children: [] }))
  const groups = registered
    .filter((g) => g.length > 0)
    .sort((a, b) => a[0].to.length - b[0].to.length)
  for (const group of groups) {
    const first = group[0].to
    let anchor = root
    for (;;) {
      // „Übersicht“ hat oft denselben Pfad wie der Elternpunkt und umfasst sonst alles
      const next = anchor.children
        .filter((c) => covers(c.to, first) && (c.to !== anchor.to || c.to === first))
        .sort((a, b) => b.to.length - a.to.length)[0]
      if (!next || next === anchor) break
      anchor = next
    }
    // Gleiche Punkte wie schon vorhanden nicht doppelt zeigen
    const known = new Set(anchor.children.map((c) => c.to))
    if (group.every((g) => known.has(g.to))) continue
    if (anchor === root && root.children.length > 0 && !covers(modulePath, group[0].to)) continue
    // Der Punkt mit dem Pfad des Elternpunkts ist der Elternpunkt selbst (z. B. die Liste
    // unter „Rechnungen“): nicht doppelt zeigen, der Elternpunkt führt dorthin
    const own = anchor === root ? [] : group.filter((g) => g.to !== anchor.to)
    const items = anchor === root ? group : own
    // Unter dem Modul selbst braucht es mindestens zwei Punkte
    if (anchor === root && items.length < 2) continue
    anchor.children = items.map((g) => ({
      ...g,
      end: true,
      children: [],
    }))
  }
  return root.children
}
