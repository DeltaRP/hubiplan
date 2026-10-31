// Lernhilfen: Schalter und ausgeblendete Erklärungen des eigenen Kontos, dazu
// „nur einmal pro Seite“ und „immer nur eine Hilfe offen“.
//
// Nur innerhalb der Oberfläche für angemeldete Bearbeitende (Layout). Im
// Mitgliederbereich und auf öffentlichen Seiten fehlt der Provider: dann zeigen
// die Bausteine nichts (Begriffe nur als Wort).
import { DEPT_PERM } from '../api/portal.ts'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from 'react'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { learningApi } from '../api/learning.ts'
import type { LearningData } from '../api/learning.ts'
import { useOptionalOrg } from '../org/OrgContext.tsx'
import type { Feature } from './content.ts'

export interface LearningState {
  /** Hauptschalter (Grundlagen und „?“) */
  enabled: boolean
  hidden: ReadonlySet<string>
  /** vom Server geladen */
  ready: boolean
  /** Einstellung konnte nicht geladen werden (dann wie ausgeschaltet) */
  loadFailed: boolean
  reload: () => void
  setEnabled: (value: boolean) => Promise<void>
  hide: (key: string) => Promise<void>
  show: (key: string) => Promise<void>
  resetHidden: () => Promise<void>
  /** freigeschaltete Funktionen der aktiven Organisation */
  hasFeature: (feature: Feature | undefined) => boolean
  /** welche Hilfe gerade offen ist (nur eine) */
  openId: string | null
  setOpenId: (id: string | null) => void
  registry: PageRegistry
}

const LearningContext = createContext<LearningState | null>(null)

/** Lernhilfen der Seite, oder null (Mitgliederbereich, öffentliche Seiten). */
// oxlint-disable-next-line react/only-export-components
export function useLearning(): LearningState | null {
  return useContext(LearningContext)
}

/** Schaltet die Lernhilfen für einen Bereich ab (z. B. Mitgliederbereich). */
export function NoLearningAids({ children }: { children: ReactNode }) {
  return <LearningContext.Provider value={null}>{children}</LearningContext.Provider>
}

// --- nur beim ersten Vorkommen pro Seite ---

/** Merkt sich je Gruppe, welche Stelle zuerst kam. Leert sich mit jedem Seitenwechsel,
 *  weil die Stellen dabei abgebaut werden. */
// oxlint-disable-next-line react/only-export-components
export class PageRegistry {
  private claims = new Map<string, string[]>()
  private listeners = new Set<() => void>()

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  first(group: string): string | undefined {
    return this.claims.get(group)?.[0]
  }

  claim(group: string, id: string) {
    const list = this.claims.get(group) ?? []
    if (list.includes(id)) return
    this.claims.set(group, [...list, id])
    this.emit()
  }

  release(group: string, id: string) {
    const list = this.claims.get(group)
    if (!list?.includes(id)) return
    const rest = list.filter((x) => x !== id)
    if (rest.length) this.claims.set(group, rest)
    else this.claims.delete(group)
    this.emit()
  }

  private emit() {
    for (const listener of this.listeners) listener()
  }
}

const NO_REGISTRY = new PageRegistry()

/** true, wenn diese Stelle die erste ihrer Gruppe auf der Seite ist. Ohne Gruppe immer true. */
// oxlint-disable-next-line react/only-export-components
export function useFirstOnPage(group: string | null): boolean {
  const id = useId()
  const registry = useLearning()?.registry ?? NO_REGISTRY
  const first = useSyncExternalStore(
    registry.subscribe,
    () => {
      if (!group) return true
      const owner = registry.first(group)
      return owner === undefined || owner === id
    },
    () => true,
  )
  useLayoutEffect(() => {
    if (!group) return
    registry.claim(group, id)
    return () => registry.release(group, id)
  }, [registry, group, id])
  return first
}

// --- Provider ---

export function LearningProvider({ children, off }: { children: ReactNode; off?: boolean }) {
  const [data, setData] = useState<LearningData | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  // Offene Hilfe samt Seite: ein Seitenwechsel schließt sie
  const [open, setOpen] = useState<{ id: string; path: string } | null>(null)
  const [registry] = useState(() => new PageRegistry())
  const org = useOptionalOrg()
  const { pathname } = useLocation()

  useEffect(() => {
    let active = true
    learningApi
      .get()
      .then((d) => {
        if (!active) return
        setLoadFailed(false)
        setData(d)
      })
      // Ohne Antwort: wie ausgeschaltet, Abwägungen bleiben sichtbar; Mein Konto
      // zeigt den Ladefehler statt „ausgeschaltet“ (Audit 29.10. NUI-07)
      .catch(() => {
        if (!active) return
        setLoadFailed(true)
        setData((d) => d ?? { learning_aids: false, learning_hidden: [] })
      })
    return () => {
      active = false
    }
  }, [attempt])

  // Beim Drucken alle Hilfen ausschreiben
  useEffect(() => {
    const opened: HTMLDetailsElement[] = []
    const before = () => {
      setOpen(null)
      document.querySelectorAll<HTMLDetailsElement>('details.aid:not([open])').forEach((el) => {
        el.open = true
        opened.push(el)
      })
    }
    const after = () => {
      opened.splice(0).forEach((el) => (el.open = false))
    }
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])

  // Sofort anzeigen, bei Fehler zurücknehmen und den Fehler weitergeben, damit die
  // Oberfläche nichts Gespeichertes behauptet (Audit 29.10. FE-F02)
  const setEnabled = useCallback(async (value: boolean) => {
    setData((d) => (d ? { ...d, learning_aids: value } : d))
    try {
      setData(await learningApi.update({ learning_aids: value }))
    } catch (err) {
      setData((d) => (d ? { ...d, learning_aids: !value } : d))
      throw err
    }
  }, [])
  const hide = useCallback(async (key: string) => {
    setData((d) => (d ? { ...d, learning_hidden: [...d.learning_hidden, key] } : d))
    try {
      const res = await learningApi.hide(key)
      setData((d) => (d ? { ...d, learning_hidden: res.learning_hidden } : d))
    } catch (err) {
      setData((d) =>
        d ? { ...d, learning_hidden: d.learning_hidden.filter((k) => k !== key) } : d,
      )
      throw err
    }
  }, [])
  const show = useCallback(async (key: string) => {
    setData((d) => (d ? { ...d, learning_hidden: d.learning_hidden.filter((k) => k !== key) } : d))
    try {
      const res = await learningApi.show(key)
      setData((d) => (d ? { ...d, learning_hidden: res.learning_hidden } : d))
    } catch (err) {
      setData((d) =>
        d && !d.learning_hidden.includes(key)
          ? { ...d, learning_hidden: [...d.learning_hidden, key] }
          : d,
      )
      throw err
    }
  }, [])
  const resetHidden = useCallback(async () => {
    setData(await learningApi.update({ learning_hidden: [] }))
  }, [])

  const openId = open && open.path === pathname ? open.id : null
  const setOpenId = useCallback(
    (id: string | null) => setOpen(id ? { id, path: pathname } : null),
    [pathname],
  )

  const modules = org?.active?.modules
  const isPlatform = org?.active?.type === 'platform'
  // In einer Untereinheit gelten deren freigeschaltete Bereiche (UI-Audit NUI-08)
  const dept = org?.active ? null : (org?.activeDept ?? null)
  const deptEvents = !!dept?.events_enabled
  const deptBilling = !!dept?.permissions.includes(DEPT_PERM.invoicesView)
  const hasFeature = useCallback(
    (feature: Feature | undefined) => {
      if (!feature) return true
      if (feature === 'platform') return isPlatform
      if (dept) {
        if (feature === 'events') return deptEvents
        if (feature === 'billing') return deptBilling
        return false
      }
      return !!modules?.includes(feature)
    },
    [modules, isPlatform, dept, deptEvents, deptBilling],
  )

  const value = useMemo<LearningState>(
    () => ({
      enabled: !!data?.learning_aids,
      hidden: new Set(data?.learning_hidden ?? []),
      ready: !!data,
      loadFailed,
      reload,
      setEnabled,
      hide,
      show,
      resetHidden,
      hasFeature,
      openId,
      setOpenId,
      registry,
    }),
    [
      data,
      loadFailed,
      reload,
      setEnabled,
      hide,
      show,
      resetHidden,
      hasFeature,
      openId,
      setOpenId,
      registry,
    ],
  )
  return <LearningContext.Provider value={off ? null : value}>{children}</LearningContext.Provider>
}
