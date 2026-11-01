// Hilfsfunktionen und Hooks für Formulare und Datenabruf.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client.ts'
import { registerLeave } from './leaveGuard.ts'
import { locale } from '../i18n/index.ts'

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Der Server ist nicht erreichbar.'
}

/** Lädt Daten und bietet reload() sowie Fehlerstatus. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Läuft gerade eine Abfrage? Mit vorhandenen Daten heißt das „wird aktualisiert“ (NMF-05)
  const [loading, setLoading] = useState(true)
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(loader, deps)
  // Jede Anfrage bekommt eine Nummer; nur die Antwort der neuesten wird übernommen.
  // So überschreibt ein langsames Nachladen nie die Daten einer neueren Abfrage.
  const generation = useRef(0)

  const run = useCallback(async () => {
    const mine = ++generation.current
    setLoading(true)
    try {
      const d = await load()
      if (mine === generation.current) {
        setData(d)
        setError(null)
      }
    } catch (err) {
      if (mine === generation.current) setError(errorMessage(err))
    } finally {
      if (mine === generation.current) setLoading(false)
    }
  }, [load])

  const reload = run

  useEffect(() => {
    void run()
    return () => {
      // Gewollt: Zähler beim Wechsel erhöhen, damit Antworten danach verworfen werden
      // oxlint-disable-next-line react-hooks/exhaustive-deps
      generation.current++
    }
  }, [run])

  return { data, error, reload, setData, loading }
}

/** Formularzustand mit Speichern und Feldfehlern. */
/** Nach dem Neuzeichnen das erste als fehlerhaft markierte Feld fokussieren (WCAG 3.3.1). */
export function focusFirstInvalid(form: Element) {
  setTimeout(() => {
    form.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, 0)
}

export function useForm<T extends object>(initial: T) {
  const [values, setValues] = useState<T>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const set = <K extends keyof T>(key: K, value: T[K]) => setValues((v) => ({ ...v, [key]: value }))

  async function submit(action: () => Promise<unknown>, success = 'Gespeichert.') {
    // Formular merken, aus dem abgeschickt wurde: dort nach Fehlern das erste Feld fokussieren
    const form =
      typeof document !== 'undefined' ? (document.activeElement?.closest('form') ?? null) : null
    setBusy(true)
    setMessage(null)
    setErrors({})
    try {
      const result = await action()
      setMessage({ kind: 'success', text: success })
      return result
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors)
        if (form && Object.keys(err.fieldErrors).length > 0) focusFirstInvalid(form)
      }
      setMessage({ kind: 'error', text: errorMessage(err) })
      return undefined
    } finally {
      setBusy(false)
    }
  }

  return { values, setValues, set, errors, setErrors, message, setMessage, busy, submit }
}

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

type AutoSaveForm<T> = {
  values: T
  setErrors: (fn: (e: Record<string, string>) => Record<string, string>) => void
  /** Wenn vorhanden, bietet der Hook „Änderungen verwerfen“ an. */
  setValues?: (values: T) => void
}

export type AutoSave = {
  state: SaveState
  error: string | null
  /** Speichert alles Offene; true erst, wenn der aktuelle Stand sicher gespeichert ist. */
  flush: () => Promise<boolean>
  /** Setzt die Eingaben auf den zuletzt gespeicherten Stand zurück (nur mit setValues). */
  discard?: () => void
}

/**
 * Autospeichern: sendet geänderte Felder kurz nach der letzten Eingabe.
 *
 * `save` bekommt nur die geänderten Felder (und alle Werte, falls ein Feld nur
 * zusammen mit anderen gespeichert werden kann). Ungültige Eingaben bleiben als
 * Feldfehler stehen und werden mit der nächsten Eingabe erneut versucht. Beim
 * Verlassen der Seite wird noch Offenes sofort gespeichert; solange etwas nicht
 * gespeichert ist (auch nach einem Fehler), warnt der Browser vor dem Schließen.
 *
 * `flush()` wartet auf eine laufende Anfrage und speichert danach den aktuellen
 * Stand. Es liefert erst dann true, wenn wirklich alles gespeichert ist; nach
 * einem Fehler false. „Schließen“ und „Versenden“ dürfen nur bei true weitermachen.
 */
export function useAutoSave<T extends object>(
  form: AutoSaveForm<T>,
  save: (changes: Partial<T>, values: T) => Promise<unknown>,
  options: { enabled?: boolean; delay?: number; onSaved?: (result: unknown) => void } = {},
): AutoSave {
  const { enabled = true, delay = 700 } = options
  const [state, setState] = useState<SaveState>('idle')
  const [error, setError] = useState<string | null>(null)
  const saved = useRef<T>(form.values)
  const latest = useRef({ values: form.values, save, onSaved: options.onSaved })
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const running = useRef<Promise<boolean> | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    latest.current = { values: form.values, save, onSaved: options.onSaved }
  })

  const changes = useCallback((): Partial<T> => {
    const values = latest.current.values
    const out: Partial<T> = {}
    for (const key of Object.keys(values) as (keyof T)[]) {
      if (JSON.stringify(values[key]) !== JSON.stringify(saved.current[key])) out[key] = values[key]
    }
    return out
  }, [])

  const saveOnce = useCallback(async (): Promise<boolean> => {
    const sent = changes()
    if (Object.keys(sent).length === 0) {
      setState((s) => (s === 'pending' ? 'idle' : s))
      return true
    }
    setState('saving')
    try {
      const result = await latest.current.save(sent, latest.current.values)
      saved.current = { ...saved.current, ...sent }
      form.setErrors((e) => {
        const rest = { ...e }
        for (const key of Object.keys(sent)) delete rest[key]
        return rest
      })
      setError(null)
      setState('saved')
      // Nach dem Verlassen (z. B. Wechsel zu einer anderen Person) nichts mehr anzeigen
      if (mounted.current) latest.current.onSaved?.(result)
      return true
    } catch (err) {
      if (err instanceof ApiError) {
        const fieldErrors = err.fieldErrors
        form.setErrors((e) => ({ ...e, ...fieldErrors }))
      }
      setError(errorMessage(err))
      setState('error')
      return false
    }
    // form.setErrors ist stabil (useState)
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [changes])

  const flush = useCallback(async (): Promise<boolean> => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    // Höchstens ein paar Runden: Eingaben während des Speicherns gleich mitnehmen
    for (let round = 0; round < 3; round++) {
      while (running.current) await running.current
      const run = saveOnce()
      running.current = run
      let ok: boolean
      try {
        ok = await run
      } finally {
        if (running.current === run) running.current = null
      }
      if (!ok) return false
      if (Object.keys(changes()).length === 0) return true
    }
    return Object.keys(changes()).length === 0
  }, [saveOnce, changes])

  useEffect(() => {
    if (!enabled) return
    if (Object.keys(changes()).length === 0) return
    // Nach einem Fehler bleibt die Meldung stehen, bis neu gespeichert wird
    setState((s) => (s === 'error' ? s : 'pending'))
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => void flush(), delay)
  }, [form.values, enabled, delay, changes, flush])

  // Beim Verlassen: Offenes sofort speichern und vor dem Schließen warnen,
  // auch wenn das letzte Speichern fehlgeschlagen ist
  useEffect(() => {
    mounted.current = true
    const warn = (e: BeforeUnloadEvent) => {
      if (timer.current || running.current || Object.keys(changes()).length > 0) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', warn)
    return () => {
      mounted.current = false
      window.removeEventListener('beforeunload', warn)
      if (timer.current || Object.keys(changes()).length > 0) void flush()
    }
  }, [flush, changes])

  const setValues = form.setValues
  const discard = useCallback(() => {
    if (!setValues) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setValues(saved.current)
    form.setErrors(() => ({}))
    setError(null)
    setState('idle')
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [setValues])

  // Navigation in der App wartet aufs Speichern (UI-Audit 29.10. NMF-01)
  useEffect(() => {
    if (!enabled) return
    return registerLeave({
      dirty: () => !!timer.current || !!running.current || Object.keys(changes()).length > 0,
      flush,
      discard: setValues ? discard : undefined,
    })
  }, [enabled, flush, changes, discard, setValues])

  return { state, error, flush, discard: setValues ? discard : undefined }
}

export function formatDate(value: string | null): string {
  if (!value) return '–'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(locale())
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(locale(), { dateStyle: 'short', timeStyle: 'short' })
}

// Genauigkeit für Mitgliedschaften und Jubiläen, je Organisation bzw. Abteilung.
export type DatePrecision = 'day' | 'month' | 'year'

export const DATE_PRECISION_WORD: Record<DatePrecision, string> = {
  day: 'tagesgenau',
  month: 'monatsgenau',
  year: 'jahresgenau',
}

export const DATE_PRECISION_OPTIONS: { value: DatePrecision; label: string }[] = [
  { value: 'day', label: 'tagesgenau (15.03.2001)' },
  { value: 'month', label: 'monatsgenau (03/2001)' },
  { value: 'year', label: 'jahresgenau (2001)' },
]

// Mitgliedschaftsdatum in der eingestellten Genauigkeit: 15.03.2001, 03/2001 oder 2001.
export function formatMemberDate(
  value: string | null | undefined,
  precision: DatePrecision | undefined,
): string {
  if (!value) return '–'
  const m = /^(\d{4})-(\d{2})/.exec(value)
  if (m && precision === 'year') return m[1]
  if (m && precision === 'month') return `${m[2]}/${m[1]}`
  return formatDate(value)
}

// „am 15.03.2026“, „im März 2026“ bzw. „im Jahr 2026“ für Jubiläen.
export function jubileeWhen(value: string, precision: DatePrecision | undefined): string {
  const m = /^(\d{4})-(\d{2})/.exec(value)
  if (m && precision === 'year') return `im Jahr ${m[1]}`
  if (m && precision === 'month') {
    const month = new Date(Number(m[1]), Number(m[2]) - 1, 1).toLocaleDateString(locale(), {
      month: 'long',
    })
    return `im ${month} ${m[1]}`
  }
  return `am ${formatDate(value)}`
}

/**
 * Signal, das beim Verlassen der Komponente abbricht, z. B. für das Warten auf
 * Hintergrund-Jobs. Als Funktion, damit auch nach erneutem Einhängen (StrictMode)
 * immer das aktuelle Signal genutzt wird.
 */
export function useUnmountSignal(): () => AbortSignal | undefined {
  const ref = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    ref.current = controller
    return () => controller.abort()
  }, [])
  return useCallback(() => ref.current?.signal, [])
}
