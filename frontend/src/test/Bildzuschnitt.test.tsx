import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { useImageCrop } from '../components/ImageCrop.tsx'
import { croppedName, hasTransparency } from '../components/photoCrop.ts'
import { LogoUpload } from '../pages/settings/AppearancePage.tsx'
import { fakeApi } from './fakeApi.ts'

beforeAll(() => {
  // jsdom kennt keine Objekt-URLs; Bilder laden dort ohnehin nie fertig
  if (!URL.createObjectURL) {
    URL.createObjectURL = vi.fn(() => 'blob:test')
    URL.revokeObjectURL = vi.fn()
  }
})

const png = () => new File(['png'], 'wappen.png', { type: 'image/png' })

function Probe({ onFile }: { onFile: (file: File | null) => void }) {
  const crop = useImageCrop()
  const [name, setName] = useState('')
  return (
    <>
      <input
        type="file"
        aria-label="Bild"
        onChange={(e) =>
          crop.choose(e, (f) => {
            setName(f?.name ?? 'keins')
            onFile(f)
          })
        }
      />
      <p>Ergebnis: {name}</p>
      {crop.dialog}
    </>
  )
}

describe('Bildausschnitt beim Hochladen', () => {
  it('öffnet nach der Auswahl den Zuschnitt-Dialog; unverändert übernehmen liefert die Datei', async () => {
    const onFile = vi.fn()
    const user = userEvent.setup()
    render(<Probe onFile={onFile} />)
    const file = png()
    await user.upload(screen.getByLabelText('Bild'), file)

    const dialog = await screen.findByRole('dialog', { name: 'Bildausschnitt festlegen' })
    expect(within(dialog).getByLabelText('Zoom')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Seitenverhältnis')).toHaveValue('original')
    // Zuschneiden geht erst, wenn das Bild geladen ist
    expect(within(dialog).getByRole('button', { name: 'Ausschnitt übernehmen' })).toBeDisabled()

    await user.click(within(dialog).getByRole('button', { name: 'Unverändert übernehmen' }))
    await waitFor(() => expect(onFile).toHaveBeenCalledWith(file))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Abbrechen lädt nichts hoch und leert das Dateifeld', async () => {
    const onFile = vi.fn()
    const user = userEvent.setup()
    render(<Probe onFile={onFile} />)
    const input = screen.getByLabelText<HTMLInputElement>('Bild')
    await user.upload(input, png())
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen' }))
    await waitFor(() => expect(onFile).toHaveBeenCalledWith(null))
    expect(input.value).toBe('')
    expect(screen.getByText('Ergebnis: keins')).toBeInTheDocument()
  })

  it('Logo/Wappen: erst Zuschnitt, dann Upload', async () => {
    const calls = fakeApi({
      'POST /api/orgs/7/logo/': () => ({ status: 200, body: { logo_url: '/media/logo.png' } }),
    })
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<LogoUpload uploadUrl="/api/orgs/7/logo/" logoUrl={null} onChange={onChange} />)
    await user.upload(screen.getByLabelText('Bild hochladen'), png())

    const dialog = await screen.findByRole('dialog', { name: 'Ausschnitt für Logo/Wappen' })
    expect(calls.some((c) => c.key.startsWith('POST'))).toBe(false)
    await user.click(within(dialog).getByRole('button', { name: 'Unverändert übernehmen' }))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/logo/')
    const form = post?.init?.body as FormData
    expect((form.get('logo') as File).name).toBe('wappen.png')
  })

  it('Dateiname und Transparenz des Ergebnisses', () => {
    expect(croppedName('Foto 2026.jpeg', 'image/jpeg')).toBe('Foto 2026.jpg')
    expect(croppedName('wappen.webp', 'image/png')).toBe('wappen.png')
    expect(croppedName('.png', 'image/jpeg')).toBe('bild.jpg')
    expect(hasTransparency(new Uint8ClampedArray([1, 2, 3, 255, 4, 5, 6, 255]))).toBe(false)
    expect(hasTransparency(new Uint8ClampedArray([1, 2, 3, 255, 4, 5, 6, 0]))).toBe(true)
  })
})
