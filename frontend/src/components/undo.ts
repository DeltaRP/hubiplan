// Rückgängig und Wiederherstellen.
//
// Jede ändernde Anfrage liefert im Kopf „X-Change-Set“ die Nummer ihres
// Änderungspakets. Lässt es sich zurücknehmen, kommt es auf den Rückgängig-Stapel
// der Organisation. Rückgängig schickt das Paket an den Server; das Ergebnis ist
// wieder ein Paket – dessen Rückgängig ist das Wiederherstellen.
import { useSyncExternalStore } from 'react'
import {
  currentAuthGeneration,
  mutationListeners,
  nextAuthGeneration,
  request,
} from '../api/client.ts'
import type { AuditEntry } from '../api/orgs.ts'
import { alertDialog, confirmDialog } from './dialog.ts'
import { t } from '../i18n/index.ts'

// base: API-Pfad des Bereichs, z. B. /api/orgs/7 oder /api/depts/3
type Entry = { base: string; setId: string; label: string }
export type Notice = {
  id: number
  base: string
  text: string
  action: 'undo' | 'redo' | null
}

type State = {
  undo: Entry[]
  redo: Entry[]
  busy: boolean
  notice: Notice | null
  // Zählt hoch, wenn Rückgängig Daten geändert hat: die Seite lädt dann neu
  version: number
}

const LIMIT = 50
const STORAGE_KEY = 'hubiplan-undo'
const OWNER_KEY = 'hubiplan-undo-user'

// Stapel überstehen das Neuladen der Seite (nur in diesem Browser-Tab)
function loadStacks(): Pick<State, 'undo' | 'redo'> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Pick<State, 'undo' | 'redo'>
      if (Array.isArray(parsed.undo) && Array.isArray(parsed.redo)) return parsed
    }
  } catch {
    // ohne Speicher geht es auch
  }
  return { undo: [], redo: [] }
}

function saveStacks() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ undo: state.undo, redo: state.redo }))
  } catch {
    // ohne Speicher geht es auch
  }
}

let state: State = { ...loadStacks(), busy: false, notice: null, version: 0 }
let noticeId = 0
const listeners = new Set<() => void>()

function update(patch: Partial<State>) {
  state = { ...state, ...patch }
  if ('undo' in patch || 'redo' in patch) saveStacks()
  for (const l of listeners) l()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function baseOf(url: string): string | null {
  const m = /\/api\/(orgs|depts)\/(\d+)\//.exec(url)
  return m ? `/api/${m[1]}/${m[2]}` : null
}

const KIND_TEXT: Record<string, string> = {
  create: t('Angelegt.'),
  delete: t('Gelöscht.'),
  'create,delete': t('Gespeichert.'),
}

/** Merkt sich eine ändernde Anfrage (aufgerufen vom API-Client). */
export function noteChange(url: string, status: number, headers: Headers) {
  const setId = headers.get('X-Change-Set')
  const base = baseOf(url)
  if (!setId || base === null || status >= 400 || url.includes('/changes/')) return
  if (headers.get('X-Change-Undoable') !== '1') return
  const kind = headers.get('X-Change-Kind') ?? 'update'
  let label = t('Änderung')
  try {
    label = decodeURIComponent(headers.get('X-Change-Label') ?? '') || label
  } catch {
    // unlesbare Beschreibung: Standardtext
  }
  const undo = [...state.undo, { base, setId, label }].slice(-LIMIT)
  const redo = state.redo.filter((e) => e.base !== base)
  // Bei Anlegen und Löschen kurz einblenden; Ändern zeigt das Formular selbst an
  const text = KIND_TEXT[kind]
  update({
    undo,
    redo,
    notice: text ? { id: ++noticeId, base, text, action: 'undo' } : state.notice,
  })
}

mutationListeners.add(noteChange)

type UndoResponse = {
  change_set?: string
  detail?: string
  problems?: string[]
  can_force?: boolean
}

/** Schickt ein Paket an den Server. Liefert das neue Paket oder null. */
async function revert(base: string, setId: string): Promise<string | null> {
  const url = `${base}/changes/${setId}/undo/`
  let res = await request<UndoResponse>('POST', url, {})
  if (res.status === 409 && res.body.can_force) {
    const ok = await confirmDialog({
      title: t('Trotzdem zurücknehmen?'),
      message: t('{x} Dabei gehen diese späteren Änderungen verloren.', {
        x: (res.body.problems ?? []).join(' '),
      }),
      confirmLabel: t('Trotzdem zurücknehmen'),
    })
    if (!ok) return null
    res = await request<UndoResponse>('POST', url, { force: true })
  }
  if (res.status >= 400) {
    const problems = res.body.problems?.join(' ')
    await alertDialog({
      title: t('Das lässt sich nicht zurücknehmen'),
      message: problems || res.body.detail || t('Das hat nicht geklappt.'),
    })
    return null
  }
  return res.body.change_set ?? null
}

function lastIndex(list: Entry[], base: string): number {
  for (let i = list.length - 1; i >= 0; i--) if (list[i].base === base) return i
  return -1
}

/** Nimmt die letzten `steps` Schritte zurück (ältere zuletzt). */
export async function undo(base: string, steps = 1) {
  await walk(base, steps, 'undo')
}

/** Stellt die letzten `steps` zurückgenommenen Schritte wieder her. */
export async function redo(base: string, steps = 1) {
  await walk(base, steps, 'redo')
}

async function walk(base: string, steps: number, direction: 'undo' | 'redo') {
  if (state.busy) return
  update({ busy: true, notice: null })
  // Abgemeldet, während die Antwort unterwegs war: nichts mehr in die Schritte schreiben
  // (sonst stünden Bezeichnungen des alten Benutzers wieder im Tab; Audit 31.10.b, C-D02)
  const generation = currentAuthGeneration()
  const stale = () => generation !== currentAuthGeneration()
  let done = 0
  try {
    for (let n = 0; n < steps; n++) {
      const from = direction === 'undo' ? state.undo : state.redo
      const i = lastIndex(from, base)
      if (i < 0) break
      const entry = from[i]
      // Erst nach Erfolg vom einen auf den anderen Stapel: Bei Fehler, Netzausfall
      // oder abgebrochener Rückfrage bleibt der Schritt zum erneuten Versuch stehen.
      let next: string | null
      try {
        next = await revert(base, entry.setId)
      } catch {
        if (stale()) return
        await alertDialog({
          title: t('Das hat nicht geklappt'),
          message: t('Der Server ist nicht erreichbar. Bitte später erneut versuchen.'),
        })
        break
      }
      if (stale()) return
      if (!next) break
      const moved = { base, setId: next, label: entry.label }
      const without = (list: Entry[]) => list.filter((e) => e !== entry)
      update(
        direction === 'undo'
          ? { undo: without(state.undo), redo: [...state.redo, moved] }
          : { redo: without(state.redo), undo: [...without(state.undo), moved].slice(-LIMIT) },
      )
      done++
    }
  } finally {
    if (!stale()) finishWalk(base, direction, done)
  }
}

function finishWalk(base: string, direction: 'undo' | 'redo', done: number) {
  const text =
    direction === 'undo'
      ? done > 1
        ? t('{done} Schritte rückgängig gemacht.', { done })
        : t('Rückgängig gemacht.')
      : done > 1
        ? t('{done} Schritte wiederhergestellt.', { done })
        : t('Wiederhergestellt.')
  update({
    busy: false,
    ...(done > 0
      ? {
          version: state.version + 1,
          notice: {
            id: ++noticeId,
            base,
            text,
            action: direction === 'undo' ? ('redo' as const) : ('undo' as const),
          },
        }
      : {}),
  })
}

/** Rückgängig aus dem Änderungsprotokoll (auch ältere Änderungen). */
export async function undoFromLog(base: string, setId: string): Promise<boolean> {
  if (state.busy) return false
  update({ busy: true })
  const generation = currentAuthGeneration()
  try {
    const next = await revert(base, setId)
    if (generation !== currentAuthGeneration()) return false
    if (!next) return false
    update({
      undo: [...state.undo, { base, setId: next, label: t('Rückgängig aus dem Protokoll') }].slice(
        -LIMIT,
      ),
      version: state.version + 1,
      notice: { id: ++noticeId, base, text: t('Rückgängig gemacht.'), action: null },
    })
    return true
  } finally {
    if (generation === currentAuthGeneration()) update({ busy: false })
  }
}

export function dismissNotice() {
  update({ notice: null })
}

// Gemerkte Listenzustände mit Suchbegriffen (Namen, E-Mails)
const LIST_PREFIXES = ['hubiplan.mitgliederliste.', 'hubiplan.abteilungsliste.']

/** Gemerkte Suchen und Seiten der Listen löschen (Gesamtaudit 01.11., GA-S07). */
export function clearListStates() {
  try {
    const keys: string[] = []
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i)
      if (key && LIST_PREFIXES.some((p) => key.startsWith(p))) keys.push(key)
    }
    for (const key of keys) sessionStorage.removeItem(key)
  } catch {
    // ohne Speicher geht es auch
  }
}

/** Beim Abmelden: Schritte (mit Namen aus den Daten) nicht für den nächsten Benutzer stehen lassen. */
export function clearUndo() {
  // Noch laufende Anfragen des alten Benutzers legen danach keine Schritte mehr an
  nextAuthGeneration()
  resetUndo()
  clearListStates()
  try {
    sessionStorage.removeItem(STORAGE_KEY)
    sessionStorage.removeItem(OWNER_KEY)
  } catch {
    // ohne Speicher geht es auch
  }
}

/** Schritte gehören zu einem Benutzer: Meldet sich ein anderer im Tab an, fängt er leer an. */
export function bindUndoToUser(userId: number | null) {
  if (userId === null) return
  try {
    const owner = sessionStorage.getItem(OWNER_KEY)
    if (owner !== String(userId)) {
      // Auch Schritte ohne Besitzer verwerfen: Sie können vom vorherigen Benutzer stammen
      resetUndo()
      clearListStates()
      sessionStorage.setItem(OWNER_KEY, String(userId))
    }
  } catch {
    // ohne Speicher geht es auch
  }
}

/** Nur für Tests. */
export function resetUndo() {
  state = { undo: [], redo: [], busy: false, notice: null, version: 0 }
  saveStacks()
  for (const l of listeners) l()
}

export function useUndo(base: string | null) {
  const s = useSyncExternalStore(subscribe, () => state)
  return {
    canUndo: base !== null && !s.busy && lastIndex(s.undo, base) >= 0,
    canRedo: base !== null && !s.busy && lastIndex(s.redo, base) >= 0,
    busy: s.busy,
    notice: s.notice && s.notice.base === base ? s.notice : null,
    version: s.version,
    // Neueste zuerst
    undoList: base === null ? [] : s.undo.filter((e) => e.base === base).reverse(),
    redoList: base === null ? [] : s.redo.filter((e) => e.base === base).reverse(),
  }
}

/** Pro Änderungspaket nur am ersten Eintrag einen Knopf zeigen. */
export function firstOfSet(entries: AuditEntry[]): Set<number> {
  const seen = new Set<string>()
  const first = new Set<number>()
  for (const e of entries) {
    const id = e.undo?.change_set
    if (id && !seen.has(id)) {
      seen.add(id)
      first.add(e.id)
    }
  }
  return first
}

/** Gleiche aufeinanderfolgende Schritte (z. B. Autospeichern im selben Formular)
 *  zu einer Zeile zusammenfassen; ein Klick nimmt die ganze Gruppe zurück. */
export function groupSteps(list: { setId: string; label: string }[], max = 15) {
  const groups: { key: string; label: string; count: number; upTo: number }[] = []
  for (const [i, e] of list.entries()) {
    const last = groups[groups.length - 1]
    if (last && last.label === e.label) {
      last.count += 1
      last.upTo = i + 1
    } else if (groups.length < max) {
      groups.push({ key: e.setId, label: e.label, count: 1, upTo: i + 1 })
    } else {
      break
    }
  }
  return groups
}
