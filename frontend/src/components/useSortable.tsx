// Reihenfolge per Ziehen (Ralf 31.10.: keine Zahlenfelder für Reihenfolgen mehr).
// Ein Griff je Zeile: mit Maus oder Finger ziehen, oder mit den Pfeiltasten verschieben.
// Die neue Reihenfolge wird sofort gespeichert; die Liste zeigt sie schon während des Ziehens.
import { useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react'
import { errorMessage } from './forms.ts'
import { Alert } from './ui.tsx'
import { GripIcon } from './Sortable.tsx'

export interface SortableOptions<T> {
  items: T[]
  id: (item: T) => number
  label: (item: T) => string
  /** Speichert die neue Reihenfolge (alle Nummern der Liste) */
  onReorder: (ids: number[]) => Promise<unknown>
  /** aus: keine Griffe (z. B. nur lesen) */
  enabled?: boolean
}

function move(order: number[], pk: number, to: number): number[] {
  const rest = order.filter((x) => x !== pk)
  rest.splice(Math.max(0, Math.min(to, rest.length)), 0, pk)
  return rest
}

const same = (a: number[], b: number[]) => a.length === b.length && a.every((x, i) => x === b[i])

export function useSortable<T>({
  items,
  id,
  label,
  onReorder,
  enabled = true,
}: SortableOptions<T>) {
  const base = items.map(id)
  const baseKey = base.join(',')
  // Vorschau gilt nur für den Stand, aus dem sie entstand; neue Daten vom Server ersetzen sie
  const [draft, setDraft] = useState<{ key: string; order: number[] } | null>(null)
  const preview = draft && draft.key === baseKey ? draft.order : null
  const setPreview = (order: number[] | null) =>
    setDraft(order === null ? null : { key: baseKey, order })
  const [dragId, setDragId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  const rows = useRef(new Map<number, HTMLElement>())
  const handles = useRef(new Map<number, HTMLButtonElement>())
  const drag = useRef<{ id: number; order: number[]; start: number[] } | null>(null)
  const focusAfter = useRef<number | null>(null)

  // Pfeiltasten: Fokus bleibt auf dem Griff der verschobenen Zeile
  useLayoutEffect(() => {
    if (focusAfter.current !== null) {
      handles.current.get(focusAfter.current)?.focus()
      focusAfter.current = null
    }
  })

  const order = preview ?? base
  const byId = new Map(items.map((it) => [id(it), it]))
  const ordered = order.map((pk) => byId.get(pk)).filter((x): x is T => x !== undefined)
  const active = enabled && items.length > 1

  async function commit(next: number[], pk: number) {
    setPreview(next)
    setError(null)
    const item = byId.get(pk)
    try {
      await onReorder(next)
      if (item)
        setAnnounce(
          `${label(item)} steht jetzt an Stelle ${next.indexOf(pk) + 1} von ${next.length}.`,
        )
    } catch (err) {
      setPreview(null)
      setError(errorMessage(err))
    }
  }

  function onPointerDown(e: PointerEvent<HTMLButtonElement>, pk: number) {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    drag.current = { id: pk, order, start: order }
    setDragId(pk)
  }

  function onPointerMove(e: PointerEvent<HTMLButtonElement>) {
    const d = drag.current
    if (!d) return
    // Stelle: hinter allen anderen Zeilen, deren Mitte über dem Zeiger liegt
    let to = 0
    for (const pk of d.order) {
      if (pk === d.id) continue
      const box = rows.current.get(pk)?.getBoundingClientRect()
      if (box && box.top + box.height / 2 < e.clientY) to += 1
    }
    const next = move(d.order, d.id, to)
    if (!same(next, d.order)) {
      d.order = next
      setPreview(next)
    }
  }

  function onPointerUp() {
    const d = drag.current
    drag.current = null
    setDragId(null)
    if (d && !same(d.order, d.start)) void commit(d.order, d.id)
  }

  function onPointerCancel() {
    const d = drag.current
    drag.current = null
    setDragId(null)
    if (d) setPreview(same(d.start, base) ? null : d.start)
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, pk: number) {
    const at = order.indexOf(pk)
    const to =
      e.key === 'ArrowUp'
        ? at - 1
        : e.key === 'ArrowDown'
          ? at + 1
          : e.key === 'Home'
            ? 0
            : e.key === 'End'
              ? order.length - 1
              : null
    if (to === null) return
    e.preventDefault()
    if (to < 0 || to >= order.length || to === at) return
    focusAfter.current = pk
    void commit(move(order, pk, to), pk)
  }

  function rowProps(item: T) {
    const pk = id(item)
    return {
      ref: (el: HTMLElement | null) => {
        if (el) rows.current.set(pk, el)
        else rows.current.delete(pk)
      },
      className: dragId === pk ? 'sortable-dragging' : undefined,
    }
  }

  function handle(item: T): ReactNode {
    if (!active) return null
    const pk = id(item)
    return (
      <button
        type="button"
        className="drag-handle"
        ref={(el) => {
          if (el) handles.current.set(pk, el)
          else handles.current.delete(pk)
        }}
        aria-label={`${label(item)} verschieben`}
        aria-roledescription="Griff zum Verschieben"
        title="Ziehen zum Verschieben (oder Pfeiltasten)"
        onPointerDown={(e) => onPointerDown(e, pk)}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onKeyDown={(e) => onKeyDown(e, pk)}
      >
        <GripIcon />
      </button>
    )
  }

  const status = (
    <>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
    </>
  )

  return { ordered, active, rowProps, handle, status }
}
