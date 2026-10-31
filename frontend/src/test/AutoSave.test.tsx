import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client.ts'
import { useAutoSave } from '../components/forms.ts'

type V = { title: string }

function setup(save: (changes: Partial<V>) => Promise<unknown>) {
  const setErrors = vi.fn()
  return renderHook(
    ({ values }: { values: V }) => useAutoSave({ values, setErrors }, save, { delay: 10_000 }),
    { initialProps: { values: { title: 'alt' } } },
  )
}

describe('Autospeichern', () => {
  it('meldet einen Fehler an „Schließen“ und speichert beim nächsten Versuch', async () => {
    let fail = true
    const save = vi.fn(async () => {
      if (fail) throw new ApiError(500, { detail: 'Serverfehler' })
      return {}
    })
    const hook = setup(save)
    hook.rerender({ values: { title: 'neu' } })
    let ok = true
    await act(async () => {
      ok = await hook.result.current.flush()
    })
    expect(ok).toBe(false)
    expect(hook.result.current.state).toBe('error')
    fail = false
    await act(async () => {
      ok = await hook.result.current.flush()
    })
    expect(ok).toBe(true)
    expect(hook.result.current.state).toBe('saved')
    expect(save).toHaveBeenLastCalledWith({ title: 'neu' }, { title: 'neu' })
  })

  it('wartet auf eine laufende Anfrage und speichert danach den neuesten Stand', async () => {
    const pending: (() => void)[] = []
    const save = vi.fn(
      () =>
        new Promise((resolve) => {
          pending.push(() => resolve({}))
        }),
    )
    const hook = setup(save)
    hook.rerender({ values: { title: 'eins' } })
    let first!: Promise<boolean>
    act(() => {
      first = hook.result.current.flush()
    })
    hook.rerender({ values: { title: 'zwei' } })
    let done = false
    let second!: Promise<boolean>
    act(() => {
      second = hook.result.current.flush().then((ok) => {
        done = true
        return ok
      })
    })
    // Die erste Anfrage läuft noch: „Schließen“ darf noch nicht weitermachen
    await act(async () => {
      await Promise.resolve()
    })
    expect(done).toBe(false)
    // Laufende Anfragen nacheinander beantworten, bis beide Aufrufe fertig sind
    await act(async () => {
      for (let i = 0; i < 20 && !done; i++) {
        pending.shift()?.()
        await new Promise((r) => setTimeout(r, 0))
      }
    })
    expect(await first).toBe(true)
    expect(await second).toBe(true)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith({ title: 'zwei' }, { title: 'zwei' })
  })
})
