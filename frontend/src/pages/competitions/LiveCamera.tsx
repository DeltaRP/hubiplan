// Live-Kamera mit automatischer Auslösung (Schießscheiben Schritt 5, Ralf 01.11.: „seamless“,
// Foto löst aus, wenn Winkel und Lage passen). Jedes Kamerabild wird verkleinert geprüft
// (aim.ts); sind einige Bilder hintereinander gut und ruhig, nimmt die Kamera das schärfste
// davon in voller Auflösung. Von Hand auslösen geht immer.
import { useEffect, useRef, useState } from 'react'
import { analyze, judge, toGray, type Aim, type Frame } from './aim.ts'

const PROBE_W = 160
const STEADY = 6 // so viele gute Bilder hintereinander, bevor ausgelöst wird

export function LiveCamera({
  blackShare,
  onCapture,
  onClose,
}: {
  /** Spiegel / äußerster Ring (Durchmesser), aus den Maßen der Scheibe */
  blackShare: number
  onCapture: (photo: Blob) => void
  onClose: () => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const [aim, setAim] = useState<Aim>({ ok: false, hint: 'Kamera wird gestartet …' })
  const [error, setError] = useState('')
  const [steady, setSteady] = useState(0)
  const done = useRef(false)
  // neueste Rückmeldung, ohne die Kamera bei jedem Neuzeichnen neu zu starten
  const capture = useRef(onCapture)
  useEffect(() => {
    capture.current = onCapture
  }, [onCapture])

  useEffect(() => {
    let stream: MediaStream | null = null
    let timer = 0
    let prev: Frame | null = null
    let good = 0
    let bestSharp = -1
    let best: HTMLCanvasElement | null = null
    const probe = document.createElement('canvas')

    function grab(full: boolean): HTMLCanvasElement | null {
      const v = video.current
      if (!v || !v.videoWidth) return null
      const c = full ? document.createElement('canvas') : probe
      c.width = full ? v.videoWidth : PROBE_W
      c.height = full
        ? v.videoHeight
        : Math.max(1, Math.round((PROBE_W * v.videoHeight) / v.videoWidth))
      c.getContext('2d')?.drawImage(v, 0, 0, c.width, c.height)
      return c
    }

    function finish(c: HTMLCanvasElement) {
      if (done.current) return
      done.current = true
      c.toBlob((blob) => blob && capture.current(blob), 'image/jpeg', 0.92)
    }

    function tick() {
      const c = grab(false)
      const ctx = c?.getContext('2d')
      if (c && ctx) {
        const { data } = ctx.getImageData(0, 0, c.width, c.height)
        const frame = analyze(toGray(data, c.width, c.height), c.width, c.height)
        const verdict = judge(frame, blackShare, prev)
        prev = frame
        if (verdict.ok) {
          good++
          // das schärfste der guten Bilder in voller Größe merken
          if (frame.sharp > bestSharp) {
            bestSharp = frame.sharp
            best = grab(true)
          }
        } else {
          good = 0
          bestSharp = -1
          best = null
        }
        setAim(verdict)
        setSteady(good)
        if (good >= STEADY && best) {
          finish(best)
          return
        }
      }
      timer = window.setTimeout(tick, 120)
    }

    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1440 } },
        audio: false,
      })
      .then((s) => {
        stream = s
        const v = video.current
        if (!v) return
        v.srcObject = s
        void v.play().catch(() => {})
        timer = window.setTimeout(tick, 300)
      })
      .catch(() =>
        setError(
          'Die Kamera lässt sich nicht öffnen (keine Freigabe oder keine Kamera). Bitte „Foto der Scheibe“ nutzen.',
        ),
      )
    return () => {
      window.clearTimeout(timer)
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [blackShare])

  function manual() {
    const v = video.current
    if (!v || !v.videoWidth) return
    const c = document.createElement('canvas')
    c.width = v.videoWidth
    c.height = v.videoHeight
    c.getContext('2d')?.drawImage(v, 0, 0)
    if (done.current) return
    done.current = true
    c.toBlob((blob) => blob && capture.current(blob), 'image/jpeg', 0.92)
  }

  return (
    <div className="live-camera" role="dialog" aria-modal="true" aria-label="Live-Kamera">
      <div className={`live-frame${aim.ok ? ' live-ok' : ''}`}>
        <video ref={video} playsInline muted aria-hidden="true" />
        <div className="live-guide" aria-hidden="true" />
      </div>
      <p className="live-hint" role="status" aria-live="polite">
        {error || aim.hint}
        {aim.ok && !error ? ` (${Math.min(steady, STEADY)}/${STEADY})` : ''}
      </p>
      <p className="muted small">
        Scheibe auf eine helle Unterlage legen, Handy gerade darüber halten. Das Foto wird nur
        ausgewertet, nicht gespeichert.
      </p>
      <div className="button-row">
        <button type="button" className="button" onClick={manual} disabled={!!error}>
          Jetzt auslösen
        </button>
        <button type="button" className="button button-ghost" onClick={onClose}>
          Abbrechen
        </button>
      </div>
    </div>
  )
}
