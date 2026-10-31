// Regressionstests zum Datenaudit: Personenwechsel (DS01) und Autospeichern nach Fehlern (DS02).
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAutoSave } from '../components/forms.ts'
import { FieldsTab } from '../pages/members/FieldsTab.tsx'

const definition = {
  id: 5,
  label: 'Notiz',
  key: 'notiz',
  field_type: 'text',
  choices: [],
  repeatable: false,
  subfields: [],
  federation_wide: false,
  help_text: '',
  sort_order: 0,
  is_archived: false,
  inherited: false,
  owner_name: 'Verein',
  in_use: true,
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('Zusatzfelder beim Wechsel der Person (DS01)', () => {
  it('zeigt und speichert die Werte von A nicht bei B', async () => {
    document.cookie = 'csrftoken=test-token'
    let releaseB: (r: Response) => void = () => {}
    const puts: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if ((init?.method ?? 'GET') === 'PUT') {
        puts.push(url)
        return new Response(JSON.stringify([{ definition, value: 'x' }]), { status: 200 })
      }
      if (url.includes('/members/1/')) {
        return new Response(JSON.stringify([{ definition, value: 'Wert von A' }]), { status: 200 })
      }
      return new Promise<Response>((resolve) => {
        releaseB = resolve
      })
    })
    const { rerender } = render(<FieldsTab orgId={7} memberId={1} canEdit />)
    expect(await screen.findByDisplayValue('Wert von A')).toBeInTheDocument()
    rerender(<FieldsTab orgId={7} memberId={2} canEdit />)
    // Solange B lädt, stehen keine Werte von A im Formular
    expect(screen.queryByDisplayValue('Wert von A')).not.toBeInTheDocument()
    expect(screen.getByText('Lädt …')).toBeInTheDocument()
    await act(async () => {
      releaseB(new Response(JSON.stringify([{ definition, value: 'Wert von B' }]), { status: 200 }))
    })
    expect(await screen.findByDisplayValue('Wert von B')).toBeInTheDocument()
    expect(puts).toEqual([])
  })
})

describe('Autospeichern nach einem Fehler (DS02)', () => {
  function useTestForm(save: () => Promise<unknown>) {
    const [values, setValues] = useState({ name: 'alt' })
    const [, setErrors] = useState<Record<string, string>>({})
    const auto = useAutoSave({ values, setErrors }, save, { delay: 10 })
    return { auto, setValues }
  }

  it('warnt vor dem Schließen und versucht es beim Verlassen erneut', async () => {
    const save = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValue({})
    const { result, unmount } = renderHook(() => useTestForm(save))
    act(() => result.current.setValues({ name: 'neu' }))
    await waitFor(() => expect(result.current.auto.state).toBe('error'))
    expect(save).toHaveBeenCalledTimes(1)

    const event = new Event('beforeunload', { cancelable: true })
    fireEvent(window, event)
    expect(event.defaultPrevented).toBe(true)

    unmount()
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect(save.mock.calls[1][0]).toEqual({ name: 'neu' })
  })

  it('warnt nicht, wenn alles gespeichert ist', async () => {
    const save = vi.fn().mockResolvedValue({})
    const { result } = renderHook(() => useTestForm(save))
    act(() => result.current.setValues({ name: 'neu' }))
    await waitFor(() => expect(result.current.auto.state).toBe('saved'))
    const event = new Event('beforeunload', { cancelable: true })
    fireEvent(window, event)
    expect(event.defaultPrevented).toBe(false)
  })
})
