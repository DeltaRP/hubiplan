// Zuschnitt vor jedem Bild-Upload: Nach der Dateiauswahl öffnet sich ein Dialog,
// in dem man zoomt, den Ausschnitt verschiebt, ein Seitenverhältnis wählt und dreht.
// „Unverändert übernehmen“ lädt die Originaldatei ohne Zuschnitt hoch.
//
// Einsatz:  const crop = useImageCrop()
//           onChange={async (e) => { const f = await crop.pick(datei); if (f) hochladen(f) }}
//           …  {crop.dialog}
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import Cropper from 'react-easy-crop'
import type { Area } from 'react-easy-crop'
import { Modal } from './Modal.tsx'
import { croppedName, cropImage, prepareImage } from './photoCrop.ts'
import { Alert } from './ui.tsx'

export interface CropSettings {
  /** Titel des Dialogs */
  title?: string
  /** Längste Seite des Ergebnisses in Pixeln */
  maxSide?: number
  /** Voreingestelltes Seitenverhältnis (Breite/Höhe); ohne Angabe wie das Original */
  aspect?: number
}

const ASPECTS: { key: string; label: string; value: number | null }[] = [
  { key: 'original', label: 'wie das Original', value: null },
  { key: '1', label: 'quadratisch (1:1)', value: 1 },
  { key: '4:3', label: 'quer (4:3)', value: 4 / 3 },
  { key: '3:2', label: 'quer (3:2)', value: 3 / 2 },
  { key: '16:9', label: 'breit (16:9)', value: 16 / 9 },
  { key: '3:4', label: 'hoch (3:4)', value: 3 / 4 },
]

const TRANSPARENT_TYPES = ['image/png', 'image/webp']

function aspectKey(value: number | undefined): string {
  if (value === undefined) return 'original'
  return (
    ASPECTS.find((a) => a.value !== null && Math.abs(a.value - value) < 0.01)?.key ?? 'original'
  )
}

export function ImageCropDialog({
  file,
  settings = {},
  onDone,
  onCancel,
}: {
  file: File
  settings?: CropSettings
  onDone: (file: File) => void
  onCancel: () => void
}) {
  const transparent = TRANSPARENT_TYPES.includes(file.type)
  const [src, setSrc] = useState<string | null>(null)
  const [natural, setNatural] = useState<number | null>(null)
  const [crop, setCrop] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)
  const [aspectChoice, setAspectChoice] = useState(aspectKey(settings.aspect))
  const [area, setArea] = useState<Area | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    let url: string | null = null
    prepareImage(file, transparent).then(
      (u) => {
        if (alive) {
          url = u
          setSrc(u)
        } else URL.revokeObjectURL(u)
      },
      (err: unknown) => {
        if (alive)
          setError(err instanceof Error ? err.message : 'Bild konnte nicht geladen werden.')
      },
    )
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [file, transparent])

  const onCropComplete = useCallback((_: Area, pixels: Area) => setArea(pixels), [])

  // Nach dem Drehen um 90° tauschen Breite und Höhe des Originals
  const turned = rotation % 180 !== 0
  const originalAspect = natural ? (turned ? 1 / natural : natural) : 4 / 3
  const chosen = ASPECTS.find((a) => a.key === aspectChoice)?.value ?? null
  const aspect = chosen ?? originalAspect

  async function apply() {
    if (!src || !area) return
    setBusy(true)
    setError(null)
    try {
      const blob = await cropImage(src, area, rotation, false, {
        maxSide: settings.maxSide ?? 2000,
        keepTransparency: transparent,
      })
      onDone(new File([blob], croppedName(file.name, blob.type), { type: blob.type }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Das hat nicht geklappt.')
      setBusy(false)
    }
  }

  return (
    <Modal title={settings.title ?? 'Bildausschnitt festlegen'} onClose={onCancel}>
      <div className="photo-editor">
        <div className={`crop-area${transparent ? ' crop-area-checker' : ''}`}>
          {src ? (
            <Cropper
              image={src}
              crop={crop}
              zoom={zoom}
              rotation={rotation}
              aspect={aspect}
              maxZoom={4}
              onCropChange={setCrop}
              onZoomChange={setZoom}
              onCropComplete={onCropComplete}
              onMediaLoaded={(m) => setNatural(m.naturalWidth / m.naturalHeight)}
            />
          ) : (
            !error && <p className="crop-loading">Bild wird geladen …</p>
          )}
        </div>
        <div className="photo-tools">
          <label className="inline-label">
            Zoom
            <input
              type="range"
              min={1}
              max={4}
              step={0.05}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              aria-label="Zoom"
            />
          </label>
          <label className="inline-label">
            Format
            <select
              aria-label="Seitenverhältnis"
              value={aspectChoice}
              onChange={(e) => {
                setAspectChoice(e.target.value)
                setCrop({ x: 0, y: 0 })
              }}
            >
              {ASPECTS.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
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
            onClick={() => {
              setZoom(1)
              setRotation(0)
              setCrop({ x: 0, y: 0 })
              setAspectChoice(aspectKey(settings.aspect))
            }}
          >
            Zurücksetzen
          </button>
        </div>
        <p className="muted small">
          Ausschnitt mit der Maus oder dem Finger verschieben; zoomen mit dem Regler, dem Mausrad
          oder zwei Fingern. Nur der helle Bereich wird gespeichert.
        </p>
        {error && <Alert kind="error">{error}</Alert>}
        <div className="button-row">
          <button
            type="button"
            className="button button-primary"
            disabled={!src || !area || busy}
            onClick={() => void apply()}
          >
            {busy ? 'Wird zugeschnitten …' : 'Ausschnitt übernehmen'}
          </button>
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() => onDone(file)}
          >
            Unverändert übernehmen
          </button>
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        </div>
      </div>
    </Modal>
  )
}

/**
 * Zuschnitt-Dialog als Hook: ``pick(file)`` öffnet den Dialog und liefert die
 * zugeschnittene Datei, die unveränderte Datei oder ``null`` (abgebrochen).
 * ``dialog`` muss irgendwo in der Komponente gerendert werden.
 */
export function useImageCrop(settings: CropSettings = {}): {
  pick: (file: File) => Promise<File | null>
  /** Für ``<input type="file" onChange>``: übergibt das Ergebnis (oder null) an ``done``. */
  choose: (e: ChangeEvent<HTMLInputElement>, done: (file: File | null) => void) => void
  dialog: ReactNode
} {
  const [pending, setPending] = useState<{ file: File; gen: number } | null>(null)
  const resolver = useRef<((file: File | null) => void) | null>(null)
  // Jede Auswahl hat ihre Nummer: Ein später fertiger Zuschnitt einer abgebrochenen
  // Auswahl erfüllt nie eine neuere (Gesamtaudit 01.11., GA-F11)
  const generation = useRef(0)

  // Offener Dialog beim Verlassen der Seite: Warten beenden
  useEffect(
    () => () => {
      resolver.current?.(null)
      resolver.current = null
    },
    [],
  )

  const pick = useCallback((file: File) => {
    resolver.current?.(null)
    generation.current += 1
    setPending({ file, gen: generation.current })
    return new Promise<File | null>((resolve) => {
      resolver.current = resolve
    })
  }, [])

  function choose(e: ChangeEvent<HTMLInputElement>, done: (file: File | null) => void) {
    const input = e.target
    const file = input.files?.[0]
    if (!file) {
      done(null)
      return
    }
    void pick(file).then((result) => {
      // Abgebrochen: Auswahl im Feld zurücksetzen, damit nichts Falsches angezeigt wird
      if (!result) input.value = ''
      done(result)
    })
  }

  function finish(gen: number, file: File | null) {
    if (gen !== generation.current) return // veraltete Auswahl
    generation.current += 1
    resolver.current?.(file)
    resolver.current = null
    setPending(null)
  }

  const dialog = pending ? (
    <ImageCropDialog
      key={pending.gen}
      file={pending.file}
      settings={settings}
      onDone={(file) => finish(pending.gen, file)}
      onCancel={() => finish(pending.gen, null)}
    />
  ) : null
  return { pick, choose, dialog }
}
