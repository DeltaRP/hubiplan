import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import Cropper from 'react-easy-crop'
import type { Area } from 'react-easy-crop'
import { cropImage, prepareImage } from './photoCrop.ts'
import { Alert } from './ui.tsx'
import { RightsHint } from './RightsHint.tsx'

const ASPECTS = [
  { value: 3 / 4, label: 'Passbild (3:4)' },
  { value: 1, label: 'quadratisch' },
]
const MAX_FILE = 10 * 1024 * 1024

/**
 * Bild wählen und zuschneiden: drehen (90°), spiegeln, zoomen, Ausschnitt
 * verschieben. ``onDone`` erhält das fertige JPEG.
 */
export function PhotoEditor({
  onDone,
  onCancel,
  busy = false,
  submitLabel = 'Übernehmen',
  children,
}: {
  onDone: (blob: Blob) => void | Promise<void>
  onCancel?: () => void
  busy?: boolean
  submitLabel?: string
  children?: ReactNode
}) {
  const [src, setSrc] = useState<string | null>(null)
  const [crop, setCrop] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)
  const [flip, setFlip] = useState(false)
  const [aspect, setAspect] = useState(ASPECTS[0].value)
  const [area, setArea] = useState<Area | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(
    () => () => {
      if (src) URL.revokeObjectURL(src)
    },
    [src],
  )
  // Nur die zuletzt gewählte Datei zählt; späte Ergebnisse nach neuer Auswahl oder
  // nach dem Schließen werden verworfen und freigegeben (Audit 29.10. FE-F03)
  const generation = useRef(0)
  useEffect(
    () => () => {
      generation.current += 1
    },
    [],
  )

  const onCropComplete = useCallback((_: Area, pixels: Area) => setArea(pixels), [])

  async function choose(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const mine = ++generation.current
    setError(null)
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError('Bitte ein JPEG-, PNG- oder WebP-Bild wählen.')
      return
    }
    if (file.size > MAX_FILE) {
      setError('Das Bild darf höchstens 10 MB groß sein.')
      return
    }
    let url: string
    try {
      url = await prepareImage(file)
    } catch (err) {
      if (mine === generation.current) {
        setError(err instanceof Error ? err.message : 'Bild konnte nicht geladen werden.')
      }
      return
    }
    if (mine !== generation.current) {
      URL.revokeObjectURL(url)
      return
    }
    setSrc(url)
    setZoom(1)
    setRotation(0)
    setFlip(false)
    setCrop({ x: 0, y: 0 })
  }

  async function apply() {
    if (!src || !area) return
    try {
      await onDone(await cropImage(src, area, rotation, flip))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Das hat nicht geklappt.')
    }
  }

  return (
    <div className="photo-editor">
      <label className="button button-ghost">
        {src ? 'Anderes Bild wählen' : 'Bild wählen'}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="file-input"
          onChange={choose}
        />
      </label>
      <RightsHint />
      {src && (
        <>
          <div className="crop-area">
            <Cropper
              image={src}
              crop={crop}
              zoom={zoom}
              rotation={rotation}
              aspect={aspect}
              onCropChange={setCrop}
              onZoomChange={setZoom}
              onCropComplete={onCropComplete}
              transform={`translate(${crop.x}px, ${crop.y}px) rotate(${rotation}deg) scale(${zoom}) scaleX(${flip ? -1 : 1})`}
            />
          </div>
          <div className="photo-tools">
            <button
              type="button"
              className="button button-ghost"
              aria-label="nach links drehen"
              onClick={() => setRotation((r) => (r + 270) % 360)}
            >
              ⟲ Drehen
            </button>
            <button
              type="button"
              className="button button-ghost"
              aria-label="nach rechts drehen"
              onClick={() => setRotation((r) => (r + 90) % 360)}
            >
              ⟳ Drehen
            </button>
            <button
              type="button"
              className="button button-ghost"
              aria-pressed={flip}
              onClick={() => setFlip((f) => !f)}
            >
              ⇋ Spiegeln
            </button>
            <label className="inline-label">
              Zoom
              <input
                type="range"
                min={1}
                max={3}
                step={0.05}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
                aria-label="Zoom"
              />
            </label>
            <select
              aria-label="Format"
              value={aspect}
              onChange={(e) => setAspect(Number(e.target.value))}
            >
              {ASPECTS.map((a) => (
                <option key={a.label} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
          <p className="muted small">
            Bild mit der Maus oder dem Finger verschieben, zum Zoomen ziehen oder scrollen.
          </p>
        </>
      )}
      {children}
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={!src || !area || busy}
          onClick={() => void apply()}
        >
          {busy ? 'Wird hochgeladen …' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        )}
      </div>
    </div>
  )
}
