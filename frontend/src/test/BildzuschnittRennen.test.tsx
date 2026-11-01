// Gesamtaudit 01.11., GA-F11: Ein später fertiger Zuschnitt einer abgebrochenen Auswahl
// darf eine neue Auswahl weder erfüllen noch deren Dialog schließen.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useImageCrop } from '../components/ImageCrop.tsx'

const pendingCrops: ((b: Blob) => void)[] = []

vi.mock('../components/photoCrop.ts', () => ({
  croppedName: (name: string) => `zugeschnitten-${name}`,
  prepareImage: () => Promise.resolve('blob:test'),
  cropImage: () => new Promise<Blob>((resolve) => pendingCrops.push(resolve)),
}))

function FakeCropper({ onCropComplete }: { onCropComplete: (a: unknown, b: unknown) => void }) {
  useEffect(() => onCropComplete({}, { x: 0, y: 0, width: 10, height: 10 }), [onCropComplete])
  return null
}

vi.mock('react-easy-crop', () => ({ default: FakeCropper }))

const handle: { pick: ((f: File) => Promise<File | null>) | null } = { pick: null }

function Probe() {
  const crop = useImageCrop()
  useEffect(() => {
    handle.pick = crop.pick
  })
  return <>{crop.dialog}</>
}

describe('Bildzuschnitt mit mehreren Auswahlen', () => {
  it('liefert für B nie das Ergebnis von A', async () => {
    const user = userEvent.setup()
    render(<Probe />)
    const a = new File(['a'], 'a.png', { type: 'image/png' })
    const b = new File(['b'], 'b.png', { type: 'image/png' })

    let resultA: File | null | undefined
    void act(() => {
      void handle.pick!(a).then((r) => (resultA = r))
    })
    let dialog = await screen.findByRole('dialog')
    await user.click(await within(dialog).findByRole('button', { name: 'Ausschnitt übernehmen' }))
    expect(pendingCrops).toHaveLength(1)
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen' }))
    await waitFor(() => expect(resultA).toBeNull())

    let resultB: File | null | undefined
    void act(() => {
      void handle.pick!(b).then((r) => (resultB = r))
    })
    dialog = await screen.findByRole('dialog')
    // Jetzt wird der alte Zuschnitt von A fertig
    await act(async () => {
      pendingCrops[0](new Blob(['A'], { type: 'image/png' }))
    })
    expect(resultB).toBeUndefined()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Unverändert übernehmen' }))
    await waitFor(() => expect(resultB).toBe(b))
  })
})
