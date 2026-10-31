// Menü der Webseite per Ziehen ordnen, mit Unterpunkten (Ralf 31.10.)
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MenuItem, MenuNode } from '../api/website.ts'
import { MenuTree } from '../pages/website/MenuTree.tsx'
import { normalizeMenu } from '../pages/website/menuTree.ts'

const item = (key: string, label: string, extra: Partial<MenuItem> = {}): MenuItem => ({
  key,
  label,
  hint: '',
  toggle: null,
  heading: false,
  parent: null,
  ...extra,
})

const items: MenuItem[] = [
  item('events', 'Termine', { toggle: 'events' }),
  item('board', 'Vorstand', { toggle: 'board' }),
  item('group:history', 'Geschichte', { heading: true }),
  item('history', 'Chronik', { toggle: 'history', parent: 'group:history' }),
  item('page:7', 'Festschrift'),
  item('contact', 'Kontakt', { toggle: 'contact' }),
]

function Harness({ onChange }: { onChange: (t: MenuNode[]) => void }) {
  const [tree, setTree] = useState<MenuNode[]>([])
  return (
    <MenuTree
      items={items}
      value={tree}
      blocks={{ events: true, board: false }}
      onChange={(next) => {
        setTree(next)
        onChange(next)
      }}
      onToggle={() => undefined}
    />
  )
}

const order = () =>
  [...document.querySelectorAll('.menu-tree > li')].map(
    (li) => (li.classList.contains('menu-tree-child') ? '  ' : '') + li.textContent,
  )

afterEach(() => vi.restoreAllMocks())

describe('Menübaum', () => {
  it('ergänzt fehlende Punkte an ihrem Standardplatz', () => {
    expect(
      normalizeMenu(
        [
          { key: 'contact', children: [] },
          { key: 'x', children: [] },
        ],
        items,
      ),
    ).toEqual([
      { key: 'events', children: [] },
      { key: 'board', children: [] },
      { key: 'group:history', children: [{ key: 'history', children: [] }] },
      { key: 'page:7', children: [] },
      { key: 'contact', children: [] },
    ])
  })

  it('zeigt Unterpunkte und rückt mit den Pfeiltasten ein und aus', () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    expect(order()).toEqual([
      'Termine',
      'Vorstand',
      'Geschichte',
      '  Chronik',
      'Festschrift',
      'Kontakt',
    ])
    expect(screen.getByRole('checkbox', { name: 'Vorstand' })).not.toBeChecked()
    // Vorstand unter Termine
    fireEvent.keyDown(screen.getByRole('button', { name: 'Vorstand verschieben' }), {
      key: 'ArrowRight',
    })
    expect(order()).toEqual([
      'Termine',
      '  Vorstand',
      'Geschichte',
      '  Chronik',
      'Festschrift',
      'Kontakt',
    ])
    expect(onChange).toHaveBeenLastCalledWith(
      expect.arrayContaining([{ key: 'events', children: [{ key: 'board', children: [] }] }]),
    )
    // Chronik wieder Hauptpunkt, hinter „Geschichte“
    fireEvent.keyDown(screen.getByRole('button', { name: 'Chronik verschieben' }), {
      key: 'ArrowLeft',
    })
    expect(order()).toEqual([
      'Termine',
      '  Vorstand',
      'Geschichte',
      'Chronik',
      'Festschrift',
      'Kontakt',
    ])
    // Überschrift kann nicht eingerückt werden
    fireEvent.keyDown(screen.getByRole('button', { name: 'Geschichte verschieben' }), {
      key: 'ArrowRight',
    })
    expect(order()[2]).toBe('Geschichte')
  })

  it('macht einen Punkt durch Draufziehen zum Unterpunkt und zieht ihn wieder heraus', () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    // Jede Zeile 40 px hoch, in der angezeigten Reihenfolge
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: HTMLElement,
    ) {
      const rows = [...document.querySelectorAll('.menu-tree > li')]
      const i = rows.indexOf(this)
      const top = i * 40
      return {
        top,
        bottom: top + 40,
        height: 40,
        left: 0,
        right: 400,
        width: 400,
        x: 0,
        y: top,
      } as DOMRect
    })
    const handle = screen.getByRole('button', { name: 'Kontakt verschieben' })
    // Kontakt (Zeile 6) mitten auf Termine (Zeile 1) ziehen
    fireEvent.pointerDown(handle, { button: 0, clientX: 10, clientY: 220 })
    fireEvent.pointerMove(handle, { clientX: 10, clientY: 20 })
    fireEvent.pointerUp(handle)
    expect(order()).toEqual([
      'Termine',
      '  Kontakt',
      'Vorstand',
      'Geschichte',
      '  Chronik',
      'Festschrift',
    ])
    // und nach links unten heraus: wieder Hauptpunkt
    fireEvent.pointerDown(handle, { button: 0, clientX: 40, clientY: 60 })
    fireEvent.pointerMove(handle, { clientX: 5, clientY: 79 })
    fireEvent.pointerUp(handle)
    expect(order()).toEqual([
      'Termine',
      'Kontakt',
      'Vorstand',
      'Geschichte',
      '  Chronik',
      'Festschrift',
    ])
    expect(onChange).toHaveBeenCalledTimes(2)
  })
})
