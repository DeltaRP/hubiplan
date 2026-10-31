import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { alertDialog, confirmDialog, promptDialog } from '../components/dialog.ts'

describe('App-eigene Rückfragen', () => {
  it('bestätigt und gibt den Fokus zurück', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const user = userEvent.setup()
    const result = confirmDialog({
      title: 'Rolle „Oberleutnant“ entfernen?',
      message: 'Die Rolle verschwindet aus dem Zug.',
      confirmLabel: 'Entfernen',
    })
    const dialog = screen.getByRole('alertdialog', { name: 'Rolle „Oberleutnant“ entfernen?' })
    expect(dialog).toHaveAccessibleDescription('Die Rolle verschwindet aus dem Zug.')
    // Sicherer Standard: Fokus liegt auf „Abbrechen“
    expect(within(dialog).getByRole('button', { name: 'Abbrechen' })).toHaveFocus()
    expect(opener.parentElement === document.body && opener.hasAttribute('inert')).toBe(true)
    await user.click(within(dialog).getByRole('button', { name: 'Entfernen' }))
    await expect(result).resolves.toBe(true)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(opener).not.toHaveAttribute('inert')
    expect(opener).toHaveFocus()
    opener.remove()
  })

  it('bricht mit Esc und Abbrechen ab', async () => {
    const user = userEvent.setup()
    const first = confirmDialog('Foto löschen?')
    await user.keyboard('{Escape}')
    await expect(first).resolves.toBe(false)
    const second = confirmDialog('Foto löschen?')
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }))
    await expect(second).resolves.toBe(false)
  })

  it('hält den Fokus im Dialog', async () => {
    const user = userEvent.setup()
    const result = confirmDialog({ title: 'Löschen?', confirmLabel: 'Löschen' })
    const cancel = screen.getByRole('button', { name: 'Abbrechen' })
    const ok = screen.getByRole('button', { name: 'Löschen' })
    await user.tab()
    expect(ok).toHaveFocus()
    await user.tab()
    expect(cancel).toHaveFocus()
    await user.tab({ shift: true })
    expect(ok).toHaveFocus()
    await user.keyboard('{Enter}')
    await expect(result).resolves.toBe(true)
  })

  it('fragt Text ab', async () => {
    const user = userEvent.setup()
    const result = promptDialog({ title: 'Termin absagen?', label: 'Hinweis' })
    const input = screen.getByLabelText('Hinweis')
    expect(input).toHaveFocus()
    await user.type(input, 'Regen{Enter}')
    await expect(result).resolves.toBe('Regen')
    const cancelled = promptDialog({ title: 'Termin absagen?', label: 'Hinweis' })
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }))
    await expect(cancelled).resolves.toBeNull()
  })

  it('zeigt einen Hinweis mit OK', async () => {
    const user = userEvent.setup()
    const result = alertDialog('Gespeichert.')
    expect(screen.queryByRole('button', { name: 'Abbrechen' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'OK' }))
    await expect(result).resolves.toBeUndefined()
  })
})
