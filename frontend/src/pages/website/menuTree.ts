// Reine Hilfen für den Menübaum (MenuTree.tsx); gleiche Regeln wie website/menu.py.
import type { MenuNode, MenuItem } from '../../api/website.ts'
import { t } from '../../i18n/index.ts'

export type Tree = MenuNode[]

/** Wie im Backend (website/menu.py): Unbekanntes weg, Fehlendes an den Standardplatz. */
export function normalizeMenu(value: Tree, items: MenuItem[]): Tree {
  const known = new Map(items.map((it, i) => [it.key, { ...it, order: i }]))
  const seen = new Set<string>()
  const tree: Tree = []
  for (const node of value) {
    if (!known.has(node.key) || seen.has(node.key)) continue
    seen.add(node.key)
    const children: Tree = []
    for (const c of node.children ?? []) {
      if (known.has(c.key) && !seen.has(c.key) && !known.get(c.key)!.heading) {
        seen.add(c.key)
        children.push({ key: c.key, children: [] })
      }
    }
    tree.push({ key: node.key, children })
  }
  for (const [key, item] of known) {
    if (seen.has(key)) continue
    seen.add(key)
    const holder = item.parent ? tree.find((n) => n.key === item.parent) : undefined
    const order = (k: string) => known.get(k)?.order ?? 0
    if (holder) {
      const at = holder.children.findIndex((c) => order(c.key) > item.order)
      holder.children.splice(at < 0 ? holder.children.length : at, 0, { key, children: [] })
      continue
    }
    let at = 0
    tree.forEach((n, i) => {
      if (order(n.key) < item.order) at = i + 1
    })
    tree.splice(at, 0, { key, children: [] })
  }
  return tree
}

export function clone(tree: Tree): Tree {
  return tree.map((n) => ({ key: n.key, children: n.children.map((c) => ({ ...c })) }))
}

/** Baum ohne den Punkt ``key`` (samt Unterpunkten) und der herausgenommene Punkt */
export function take(tree: Tree, key: string): [Tree, MenuNode] {
  const next = clone(tree)
  const top = next.findIndex((n) => n.key === key)
  if (top >= 0) return [next, next.splice(top, 1)[0]]
  for (const n of next) {
    const i = n.children.findIndex((c) => c.key === key)
    if (i >= 0) return [next, n.children.splice(i, 1)[0]]
  }
  throw new Error(t('Menüpunkt {key} fehlt', { key }))
}

/** Ort im Baum: Hauptpunkt an Stelle ``index`` oder Unterpunkt von ``parent`` */
export type Place = { parent: string | null; index: number }

export function put(tree: Tree, node: MenuNode, place: Place): Tree {
  const next = clone(tree)
  if (place.parent === null) {
    next.splice(place.index, 0, node)
  } else {
    const holder = next.find((n) => n.key === place.parent)!
    holder.children.splice(place.index, 0, { key: node.key, children: [] })
  }
  return next
}

export function placeOf(tree: Tree, key: string): Place {
  const top = tree.findIndex((n) => n.key === key)
  if (top >= 0) return { parent: null, index: top }
  for (const n of tree) {
    const i = n.children.findIndex((c) => c.key === key)
    if (i >= 0) return { parent: n.key, index: i }
  }
  return { parent: null, index: tree.length }
}

export const sameTree = (a: Tree, b: Tree) => JSON.stringify(a) === JSON.stringify(b)

export interface Row {
  key: string
  depth: 0 | 1
  parent: string | null
}

export function rowsOf(tree: Tree): Row[] {
  return tree.flatMap((n) => [
    { key: n.key, depth: 0 as const, parent: null },
    ...n.children.map((c) => ({ key: c.key, depth: 1 as const, parent: n.key })),
  ])
}
