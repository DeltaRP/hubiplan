// Menü der Webseite als Baum (Ralf 31.10.): Reihenfolge per Ziehen; ein Punkt auf einen
// anderen gezogen wird sein Unterpunkt, nach links herausgezogen wieder Hauptpunkt.
// Pfeiltasten am Griff: ↑ ↓ verschieben, → einrücken, ← ausrücken.
// Bausteine lassen sich umbenennen (Ralf 01.11.): Stift, leer = Standardname.
import { useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import type { MenuItem, MenuNode } from '../../api/website.ts'
import { normalizeMenu, placeOf, put, rowsOf, sameTree, take } from './menuTree.ts'
import type { Place, Tree } from './menuTree.ts'
import { GripIcon } from '../../components/Sortable.tsx'
import { EditIcon, IconButton } from '../../components/icons.tsx'
import { Checkbox } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'

/** Wie weit nach rechts (px) ein Punkt gezogen werden muss, um Unterpunkt zu werden */
const INDENT = 28

export function MenuTree({
  items,
  value,
  blocks,
  names = {},
  onChange,
  onToggle,
  onRename,
  disabled = false,
}: {
  items: MenuItem[]
  value: Tree
  blocks: Record<string, boolean>
  /** Eigene Namen der Bausteine (Schlüssel → Name) */
  names?: Record<string, string>
  onChange: (next: Tree) => void
  onToggle: (block: string, on: boolean) => void
  onRename?: (key: string, name: string) => void
  disabled?: boolean
}) {
  const byKey = new Map(items.map((it) => [it.key, it]))
  const base = normalizeMenu(value, items)
  const [preview, setPreview] = useState<Tree | null>(null)
  const tree = preview ?? base
  const [dragKey, setDragKey] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  const rowEls = useRef(new Map<string, HTMLElement>())
  const handles = useRef(new Map<string, HTMLButtonElement>())
  const drag = useRef<{ key: string; start: Tree; tree: Tree; x0: number } | null>(null)
  const focusAfter = useRef<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)

  useLayoutEffect(() => {
    if (focusAfter.current !== null) {
      handles.current.get(focusAfter.current)?.focus()
      focusAfter.current = null
    }
  })

  /** Standardname eines Punkts (ältere Stände ohne ``default_label``: ``label``) */
  const standard = (it: MenuItem) => it.default_label ?? it.label
  /** Name im Menü: eigener Name (auch noch nicht gespeichert) oder Standard */
  const nameOf = (it: MenuItem) =>
    (it.renamable && names[it.key]?.trim()) || (it.renamable ? standard(it) : it.label)
  const label = (key: string) => {
    const it = byKey.get(key)
    return it ? nameOf(it) : key
  }
  /** Kann ``node`` Unterpunkt werden? (keine Überschrift, keine eigenen Unterpunkte) */
  const nestable = (node: MenuNode) => !byKey.get(node.key)?.heading && node.children.length === 0

  function describe(next: Tree, key: string) {
    const p = placeOf(next, key)
    setAnnounce(
      p.parent === null
        ? t('{x} ist jetzt Hauptpunkt an Stelle {x2}.', { x: label(key), x2: p.index + 1 })
        : t('{x} ist jetzt Unterpunkt von {x2} an Stelle {x3}.', {
            x: label(key),
            x2: label(p.parent),
            x3: p.index + 1,
          }),
    )
  }

  function commit(next: Tree, key: string) {
    setPreview(null)
    if (sameTree(next, base)) return
    onChange(next)
    describe(next, key)
  }

  // --- Ziehen mit Maus oder Finger ---

  function target(d: { key: string; start: Tree; x0: number }, x: number, y: number): Tree {
    const [rest, node] = take(d.start, d.key)
    const rows = rowsOf(rest)
    const canNest = nestable(node)
    // Einrückung wie beim Start plus die Bewegung nach rechts oder links
    const indent = (placeOf(d.start, d.key).parent === null ? 0 : INDENT) + x - d.x0
    const wantChild = indent > INDENT / 2
    // Zeile unter dem Zeiger: in der Mitte eines Hauptpunkts → Unterpunkt davon
    for (const r of rows) {
      const box = rowEls.current.get(r.key)?.getBoundingClientRect()
      if (!box || y < box.top || y > box.bottom) continue
      const band = box.height / 4
      if (canNest && r.depth === 0 && y > box.top + band && y < box.bottom - band) {
        const holder = rest.find((n) => n.key === r.key)!
        return put(rest, node, { parent: r.key, index: holder.children.length })
      }
      break
    }
    // Sonst Lücke zwischen zwei Zeilen
    let gap = 0
    for (const r of rows) {
      const box = rowEls.current.get(r.key)?.getBoundingClientRect()
      if (box && box.top + box.height / 2 < y) gap += 1
    }
    const above = gap > 0 ? rows[gap - 1] : null
    const below = gap < rows.length ? rows[gap] : null
    const topIndex = (key: string) => rest.findIndex((n) => n.key === key)
    if (below && below.depth === 1) {
      if (canNest) {
        const holder = rest.find((n) => n.key === below.parent)!
        const index = holder.children.findIndex((c) => c.key === below.key)
        return put(rest, node, { parent: below.parent, index })
      }
      // Überschrift oder Punkt mit Unterpunkten: hinter die ganze Gruppe
      return put(rest, node, { parent: null, index: topIndex(below.parent!) + 1 })
    }
    if (above && canNest && wantChild) {
      const holderKey = above.parent ?? above.key
      const holder = rest.find((n) => n.key === holderKey)!
      return put(rest, node, { parent: holderKey, index: holder.children.length })
    }
    return put(rest, node, { parent: null, index: below ? topIndex(below.key) : rest.length })
  }

  function onPointerDown(e: PointerEvent<HTMLButtonElement>, key: string) {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    drag.current = { key, start: tree, tree, x0: e.clientX }
    setDragKey(key)
  }

  function onPointerMove(e: PointerEvent<HTMLButtonElement>) {
    const d = drag.current
    if (!d) return
    const next = target(d, e.clientX, e.clientY)
    if (!sameTree(next, d.tree)) {
      d.tree = next
      setPreview(next)
    }
  }

  function onPointerUp() {
    const d = drag.current
    drag.current = null
    setDragKey(null)
    if (d) commit(d.tree, d.key)
  }

  function onPointerCancel() {
    drag.current = null
    setDragKey(null)
    setPreview(null)
  }

  // --- Tastatur ---

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, key: string) {
    const [rest, node] = take(tree, key)
    const p = placeOf(tree, key)
    let place: Place | null = null
    if (p.parent === null) {
      if (e.key === 'ArrowUp' && p.index > 0) place = { parent: null, index: p.index - 1 }
      if (e.key === 'ArrowDown' && p.index < tree.length - 1)
        place = { parent: null, index: p.index + 1 }
      if (e.key === 'ArrowRight' && p.index > 0 && nestable(node)) {
        const holder = rest[p.index - 1]
        place = { parent: holder.key, index: holder.children.length }
      }
    } else {
      const siblings = tree.find((n) => n.key === p.parent)!.children
      const parentIndex = tree.findIndex((n) => n.key === p.parent)
      if (e.key === 'ArrowUp')
        place =
          p.index > 0
            ? { parent: p.parent, index: p.index - 1 }
            : { parent: null, index: parentIndex }
      if (e.key === 'ArrowDown')
        place =
          p.index < siblings.length - 1
            ? { parent: p.parent, index: p.index + 1 }
            : { parent: null, index: parentIndex + 1 }
      if (e.key === 'ArrowLeft') place = { parent: null, index: parentIndex + 1 }
    }
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return
    e.preventDefault()
    if (!place) return
    focusAfter.current = key
    commit(put(rest, node, place), key)
  }

  function row(node: MenuNode, depth: 0 | 1) {
    const item = byKey.get(node.key)
    if (!item) return null
    const name = nameOf(item)
    const renamed = Boolean(item.renamable && names[item.key]?.trim())
    const hint = renamed
      ? [t('Standard: {x}', { x: standard(item) }), item.hint].filter(Boolean).join(' · ')
      : item.hint
    const content = item.toggle ? (
      <Checkbox
        label={name}
        hint={hint}
        checked={blocks[item.toggle] ?? true}
        disabled={disabled}
        onChange={(on) => onToggle(item.toggle!, on)}
      />
    ) : (
      <span className={item.heading ? 'menu-tree-heading' : undefined}>
        {name}
        {hint && <span className="muted small"> · {hint}</span>}
      </span>
    )
    const canRename = Boolean(item.renamable && onRename && !disabled)
    const rename = canRename && editing === node.key && (
      <input
        className="menu-tree-name"
        autoFocus
        maxLength={60}
        value={names[item.key] ?? ''}
        placeholder={standard(item)}
        aria-label={t('Eigener Name für {x} (leer: Standardname)', { x: standard(item) })}
        onChange={(e) => onRename!(item.key, e.target.value)}
        onBlur={() => setEditing(null)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === 'Escape') {
            e.preventDefault()
            setEditing(null)
          }
        }}
      />
    )
    return (
      <li
        key={node.key}
        className={[
          'menu-tree-row',
          depth === 1 ? 'menu-tree-child' : '',
          dragKey === node.key ? 'sortable-dragging' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        ref={(el) => {
          if (el) rowEls.current.set(node.key, el)
          else rowEls.current.delete(node.key)
        }}
      >
        {!disabled && (
          <button
            type="button"
            className="drag-handle"
            ref={(el) => {
              if (el) handles.current.set(node.key, el)
              else handles.current.delete(node.key)
            }}
            aria-label={t('{label} verschieben', { label: item.label })}
            aria-roledescription={t('Griff zum Verschieben')}
            title={t(
              'Ziehen zum Verschieben; auf einen anderen Punkt ziehen macht ihn zum Unterpunkt (oder Pfeiltasten)',
            )}
            onPointerDown={(e) => onPointerDown(e, node.key)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerCancel}
            onKeyDown={(e) => onKeyDown(e, node.key)}
          >
            <GripIcon />
          </button>
        )}
        <div className="sortable-label">
          {content}
          {rename}
        </div>
        {canRename && (
          <IconButton
            label={t('{x} umbenennen', { x: name })}
            icon={<EditIcon />}
            aria-pressed={editing === node.key}
            onClick={() => setEditing(editing === node.key ? null : node.key)}
          />
        )}
      </li>
    )
  }

  return (
    <>
      <p className="muted small sort-hint">
        {t('Reihenfolge des Menüs: am Griff')} <GripIcon />{' '}
        {t(
          'ziehen. Ziehst du einen Punkt auf einen anderen, wird er sein Unterpunkt; ziehst du einen Unterpunkt nach links heraus, wird er wieder Hauptpunkt. Mit der Tastatur: Griff anklicken, ↑ ↓ verschieben, → einrücken, ← ausrücken.',
        )}
      </p>
      <ul className="sortable-list menu-tree" aria-label={t('Menü der Webseite')}>
        {tree.flatMap((n) => [row(n, 0), ...n.children.map((c) => row(c, 1))])}
      </ul>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>
    </>
  )
}
