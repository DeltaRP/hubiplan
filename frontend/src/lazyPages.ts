// Seiten erst beim ersten Aufruf laden (eigene JS-Dateien je Bereich). So braucht
// die Anmeldung und jede öffentliche Seite nicht das ganze Programm.
import { lazy } from 'react'
import type { ComponentType } from 'react'

type Module = Record<string, unknown>
type Loader = () => Promise<Module>
const loaders: Loader[] = []
const loaded = new Map<Loader, Module>()

async function fetchModule(load: Loader): Promise<Module> {
  const module = await load()
  loaded.set(load, module)
  return module
}

export function lazyPage<P extends object = object>(load: Loader, name: string): ComponentType<P> {
  loaders.push(load)
  const pick = (module: Module) => ({ default: module[name] as ComponentType<P> })
  return lazy(() => {
    const module = loaded.get(load)
    // Schon geladen: sofort liefern, ohne kurz „Lädt …“ zu zeigen
    if (module)
      return {
        then: (resolve: (m: ReturnType<typeof pick>) => void) => resolve(pick(module)),
      } as Promise<ReturnType<typeof pick>>
    return fetchModule(load).then(pick)
  })
}

/** Alle Seiten vorab laden (Tests; nach der Anmeldung im Hintergrund). */
export function preloadPages(): Promise<unknown> {
  return Promise.all(loaders.map(fetchModule))
}

/** Seiten nach der Anmeldung schonend vorladen: einzeln, nur wenn der Browser Zeit hat,
 * nicht bei „Datensparen“ oder sehr langsamem Netz (Gesamtaudit 30.10., WEB-P01).
 * Gibt eine Funktion zum Abbrechen zurück. */
export function preloadPagesGently(): () => void {
  const nav = navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string }
  }
  if (nav.connection?.saveData || /(^|-)2g$/.test(nav.connection?.effectiveType ?? '')) {
    return () => undefined
  }
  let stopped = false
  let index = 0
  const idle: (cb: () => void) => void =
    typeof window.requestIdleCallback === 'function'
      ? (cb) => window.requestIdleCallback(cb, { timeout: 5000 })
      : (cb) => window.setTimeout(cb, 200)
  const next = () => {
    if (stopped || index >= loaders.length) return
    const load = loaders[index++]
    fetchModule(load)
      .catch(() => undefined)
      .finally(() => idle(next))
  }
  idle(next)
  return () => {
    stopped = true
  }
}
