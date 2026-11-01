// Foto der Scheibe aufnehmen und Treffer vorschlagen lassen (Schießscheiben Schritt 4).
// Das Foto geht nur zur Auswertung an den Server und wird dort nicht gespeichert; der
// Vorschlag landet im Antipp-Bild und wird erst mit „Übernehmen“ gespeichert.
import { useRef, useState } from 'react'
import type { PhotoResult } from '../../api/competitions.ts'
import { cameraAvailable } from './aim.ts'
import { LiveCamera } from './LiveCamera.tsx'
import { errorText, shrinkPhoto, toSuggestion, type PhotoSuggestion } from './photo.ts'

export function PhotoButton({
  detect,
  onResult,
  disabled,
  blackShare,
}: {
  detect: (photo: Blob) => Promise<PhotoResult>
  onResult: (s: PhotoSuggestion) => void
  disabled?: boolean
  /** Spiegel / äußerster Ring; mit Wert gibt es die Live-Kamera (Schritt 5) */
  blackShare?: number | null
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [live, setLive] = useState(false)

  async function onFile(file: Blob | undefined) {
    if (!file) return
    setError('')
    setBusy(true)
    try {
      const result = await detect(await shrinkPhoto(file))
      onResult(toSuggestion(result))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="pad-photo">
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        aria-label="Foto der Scheibe"
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <button
        type="button"
        className="button button-ghost"
        disabled={disabled || busy}
        onClick={() => input.current?.click()}
      >
        {busy ? 'Foto wird ausgewertet …' : 'Foto der Scheibe'}
      </button>
      {blackShare && cameraAvailable() ? (
        <button
          type="button"
          className="button button-ghost"
          disabled={disabled || busy}
          onClick={() => {
            setError('')
            setLive(true)
          }}
        >
          Live-Kamera
        </button>
      ) : null}
      {live && blackShare ? (
        <LiveCamera
          blackShare={blackShare}
          onCapture={(photo) => {
            setLive(false)
            void onFile(photo)
          }}
          onClose={() => setLive(false)}
        />
      ) : null}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
