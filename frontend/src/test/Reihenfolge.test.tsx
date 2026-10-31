import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SortableList } from '../components/Sortable.tsx'

const items = [
  { id: 1, name: 'Kassierer' },
  { id: 2, name: 'Schriftführer' },
  { id: 3, name: 'Zeugwart' },
]

function names() {
  return screen.getAllByRole('listitem').map((li) => li.textContent)
}

describe('Reihenfolge per Ziehen', () => {
  it('verschiebt mit den Pfeiltasten und speichert sofort', async () => {
    const onReorder = vi.fn().mockResolvedValue(undefined)
    render(
      <SortableList
        ariaLabel="Rollen"
        items={items}
        id={(i) => i.id}
        label={(i) => i.name}
        onReorder={onReorder}
      />,
    )
    const handle = screen.getByRole('button', { name: 'Zeugwart verschieben' })
    handle.focus()
    await userEvent.keyboard('{ArrowUp}')
    expect(onReorder).toHaveBeenCalledWith([1, 3, 2])
    expect(names()).toEqual(['Kassierer', 'Zeugwart', 'Schriftführer'])
    // Fokus bleibt auf dem Griff, die Stelle wird angesagt
    expect(screen.getByRole('button', { name: 'Zeugwart verschieben' })).toHaveFocus()
    expect(await screen.findByText('Zeugwart steht jetzt an Stelle 2 von 3.')).toBeInTheDocument()
    await userEvent.keyboard('{Home}')
    expect(onReorder).toHaveBeenLastCalledWith([3, 1, 2])
  })

  it('nimmt die Vorschau zurück, wenn das Speichern scheitert', async () => {
    const onReorder = vi.fn().mockRejectedValue(new Error('Keine Verbindung'))
    render(
      <SortableList
        ariaLabel="Rollen"
        items={items}
        id={(i) => i.id}
        label={(i) => i.name}
        onReorder={onReorder}
      />,
    )
    screen.getByRole('button', { name: 'Kassierer verschieben' }).focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(names()).toEqual(['Kassierer', 'Schriftführer', 'Zeugwart']))
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('zeigt bei nur einem Eintrag keinen Griff', () => {
    render(
      <SortableList
        ariaLabel="Rollen"
        items={items.slice(0, 1)}
        id={(i) => i.id}
        label={(i) => i.name}
        onReorder={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button')).toBeNull()
  })
})
