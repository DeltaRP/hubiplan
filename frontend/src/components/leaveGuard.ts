// Schutz vor verlorenen Eingaben beim Verlassen eines Formulars innerhalb der App
// (UI-Audit 29.10. NMF-01).
//
// Jedes Autospeichern-Formular meldet sich hier an. Bevor die App woanders hingeht
// (Link, Reiter, Wechsel der Einheit), speichert `confirmLeave()` alles Offene. Geht
// das nicht, fragt ein Dialog: erneut versuchen, weiter bearbeiten oder verwerfen.
// Entwürfe werden bewusst nicht im Browser abgelegt (Mitgliederdaten auf geteilten
// Vereins-PCs).
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { choiceDialog } from './dialog.ts'
import { t } from '../i18n/index.ts'

export type LeaveEntry = {
  /** Gibt es Ungespeichertes (auch nach einem Fehler)? */
  dirty: () => boolean
  /** Speichert alles; true, wenn danach nichts mehr offen ist */
  flush: () => Promise<boolean>
  /** Auf den gespeicherten Stand zurücksetzen */
  discard?: () => void
  /**
   * Formular ohne Autospeichern (Neuaufnahme, Änderungsmeldung, Zuordnung …): Eingaben
   * werden erst mit dem Knopf gespeichert. Beim Verlassen wird gefragt, ob verworfen
   * werden soll (UX-Audit 31.10. W01).
   */
  manual?: boolean
}

const entries = new Set<LeaveEntry>()
let asking: Promise<boolean> | null = null
// Browser-Zurück/Vorwärts: wohin die App gerade zeigt und ob der nächste popstate von uns
// selbst kommt (Rücksprung bzw. bestätigtes Verlassen)
let shownIndex: number | null = null
let popMode: 'restore' | 'pass' | null = null

export function registerLeave(entry: LeaveEntry): () => void {
  entries.add(entry)
  return () => {
    entries.delete(entry)
  }
}

function pending(): LeaveEntry[] {
  return [...entries].filter((e) => !e.manual && e.dirty())
}

function pendingManual(): LeaveEntry[] {
  return [...entries].filter((e) => e.manual && e.dirty())
}

/** Gibt es irgendwo ungespeicherte Eingaben (Autospeichern oder Entwurf)? */
export function hasUnsaved(): boolean {
  return pending().length > 0 || pendingManual().length > 0
}

async function confirmDiscardDrafts(): Promise<boolean> {
  const list = pendingManual()
  if (list.length === 0) return true
  const choice = await choiceDialog({
    title: t('Eingaben verwerfen?'),
    message: t(
      'Deine Eingaben wurden noch nicht gespeichert. Wenn du die Seite verlässt, gehen sie verloren.',
    ),
    choices: [
      { value: 'discard', label: t('Verwerfen'), danger: true },
      { value: 'stay', label: t('Weiter bearbeiten'), primary: true },
    ],
    cancelValue: 'stay',
  })
  if (choice !== 'discard') return false
  for (const e of list) e.discard?.()
  return true
}

async function flushAll(list: LeaveEntry[]): Promise<boolean> {
  const results = await Promise.all(list.map((e) => e.flush().catch(() => false)))
  return results.every(Boolean)
}

/** true: weitergehen; false: bleiben. Fragt nur, wenn das Speichern scheitert. */
export function confirmLeave(): Promise<boolean> {
  if (asking) return asking
  if (!hasUnsaved()) return Promise.resolve(true)
  asking = (async () => {
    try {
      for (;;) {
        if (await flushAll(pending())) return await confirmDiscardDrafts()
        const choice = await choiceDialog({
          title: t('Änderungen noch nicht gespeichert'),
          message:
            t('Deine letzten Änderungen konnten nicht gespeichert werden, z. B. weil die ') +
            t('Verbindung fehlt. Wie möchtest du weitermachen?'),
          choices: [
            { value: 'discard', label: t('Änderungen verwerfen'), danger: true },
            { value: 'stay', label: t('Weiter bearbeiten') },
            { value: 'retry', label: t('Erneut versuchen'), primary: true },
          ],
          cancelValue: 'stay',
        })
        if (choice === 'stay') return false
        if (choice === 'discard') {
          for (const e of pending()) e.discard?.()
          return await confirmDiscardDrafts()
        }
      }
    } finally {
      asking = null
    }
  })()
  return asking
}

/** Speichert alle offenen Formulare ohne Rückfrage; true, wenn danach nichts mehr offen ist. */
export function flushAllForms(): Promise<boolean> {
  return flushAll(pending())
}

/** Führt `action` erst aus, wenn alles gespeichert (oder bewusst verworfen) ist. */
export function useGuarded() {
  return useCallback(async (action: () => void) => {
    if (await confirmLeave()) action()
  }, [])
}

function internalTarget(e: MouseEvent): string | null {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
    return null
  const link = (e.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
  if (!link || (link.target && link.target !== '_self') || link.hasAttribute('download'))
    return null
  const url = new URL(link.href, window.location.href)
  // Dateien vom Server (PDF, Word) sind keine Seiten der App
  if (url.origin !== window.location.origin || url.pathname.startsWith('/api/')) return null
  const here = window.location
  if (url.pathname === here.pathname && url.search === here.search) return null
  return url.pathname + url.search + url.hash
}

function historyIndex(): number | null {
  const idx = (window.history.state as { idx?: unknown } | null)?.idx
  return typeof idx === 'number' ? idx : null
}

/**
 * Fängt Klicks auf interne Links und Browser-Zurück/Vorwärts ab, solange ein Formular
 * Ungespeichertes hat (Gesamtaudit 01.11., GA-F02).
 */
export function LeaveGuard() {
  const navigate = useNavigate()
  const location = useLocation()

  // Stelle im Verlauf, auf der die App gerade steht (React-Router merkt sie in state.idx)
  useEffect(() => {
    shownIndex = historyIndex()
  }, [location])

  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      if (popMode === 'restore') {
        // Rücksprung auf die Formularseite: React-Router bekommt davon nichts mit
        popMode = null
        e.stopImmediatePropagation()
        return
      }
      if (popMode === 'pass') {
        popMode = null
        return
      }
      if (!hasUnsaved()) return
      const to = historyIndex()
      const from = shownIndex
      if (to === null || from === null || to === from) return
      e.stopImmediatePropagation()
      const delta = from - to
      popMode = 'restore'
      window.history.go(delta)
      void confirmLeave().then((ok) => {
        if (!ok) return
        popMode = 'pass'
        window.history.go(-delta)
      })
    }
    // Erfassungsphase am Fenster: kommt vor dem popstate-Handler von React-Router
    window.addEventListener('popstate', onPop, true)
    return () => window.removeEventListener('popstate', onPop, true)
  }, [])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!hasUnsaved()) return
      const target = internalTarget(e)
      if (!target) return
      e.preventDefault()
      e.stopPropagation()
      void confirmLeave().then((ok) => ok && navigate(target))
    }
    // Erfassungsphase am Dokument: kommt vor dem Klick-Handler von React-Router
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [navigate])
  return null
}

/**
 * Schützt ein Formular ohne Autospeichern: solange `dirty` true ist, fragt die App vor dem
 * Verlassen (Link, Menü, Wechsel der Einheit) und der Browser vor dem Schließen.
 * `discard` wird aufgerufen, wenn verworfen wird (optional).
 */
export function useDraftGuard(dirty: boolean, discard?: () => void) {
  useEffect(() => {
    if (!dirty) return
    const unregister = registerLeave({
      manual: true,
      dirty: () => true,
      flush: () => Promise.resolve(false),
      discard,
    })
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => {
      unregister()
      window.removeEventListener('beforeunload', warn)
    }
  }, [dirty, discard])
}

/** Fragt vor dem Verwerfen, wenn `dirty`; true = weitermachen (z. B. Abbrechen ausführen). */
export async function confirmDiscard(dirty: boolean): Promise<boolean> {
  if (!dirty) return true
  const choice = await choiceDialog({
    title: t('Eingaben verwerfen?'),
    message: t('Deine Eingaben wurden noch nicht gespeichert und gehen verloren.'),
    choices: [
      { value: 'discard', label: t('Verwerfen'), danger: true },
      { value: 'stay', label: t('Weiter bearbeiten'), primary: true },
    ],
    cancelValue: 'stay',
  })
  return choice === 'discard'
}

/**
 * Merkt sich den Ausgangsstand von `values` und schützt das Formular, sobald etwas
 * geändert wurde. `active = false` schaltet den Schutz ab (z. B. nach dem Speichern).
 * `markSaved()` übernimmt den aktuellen Stand als neuen Ausgangsstand.
 */
export function useChangesGuard(values: unknown, active = true) {
  const current = JSON.stringify(values)
  const [base, setBase] = useState(current)
  const dirty = active && current !== base
  useDraftGuard(dirty)
  const markSaved = useCallback(() => setBase(current), [current])
  return { dirty, markSaved }
}
