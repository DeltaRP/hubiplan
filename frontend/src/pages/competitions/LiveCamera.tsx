// Live-Kamera mit automatischer Auslösung (Schießscheiben Schritt 5, Ralf 01.11.: „seamless“,
// Foto löst aus, wenn Winkel und Lage passen). Jedes Kamerabild wird verkleinert geprüft
// (aim.ts); sind einige Bilder hintereinander gut und ruhig, nimmt die Kamera das schärfste
// davon in voller Auflösung. Von Hand auslösen geht immer.
import { useEffect, useRef, useState } from 'react'
import { analyze, judge, toGray, type Aim, type Frame } from './aim.ts'
import { cameraError } from './cameraError.ts'
import { t } from '../../i18n/index.ts'

const PROBE_W = 160
const STEADY = 6 // so viele gute Bilder hintereinander, bevor ausgelöst wird

export function LiveCamera({
  blackShare,
  onCapture,
  onClose,
  onFail,
}: {
  /** Spiegel / äußerster Ring (Durchmesser), aus den Maßen der Scheibe */
  blackShare: number
  onCapture: (photo: Blob) => void
  onClose: () => void
  /** Kamera lässt sich nicht öffnen: Grund als verständlicher Satz */
  onFail: (message: string) => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const [aim, setAim] = useState<Aim>({ ok: false, hint: 'Kamera wird gestartet …' })
  const [steady, setSteady] = useState(0)
  const done = useRef(false)
  // neueste Rückmeldung, ohne die Kamera bei jedem Neuzeichnen neu zu starten
  const capture = useRef(onCapture)
  const fail = useRef(onFail)
  useEffect(() => {
    capture.current = onCapture
    fail.current = onFail
  }, [onCapture, onFail])

  // Seite dahinter festhalten, solange die Kamera offen ist
  useEffect(() => {
    const root = document.documentElement
    const before = [root.style.overflow, document.body.style.overflow]
    root.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    return () => {
      root.style.overflow = before[0]
      document.body.style.overflow = before[1]
    }
  }, [])

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

    if (!navigator.mediaDevices?.getUserMedia) {
      fail.current(cameraError(null))
      return
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
      .catch((err: unknown) => fail.current(cameraError(err)))
    return () => {
      window.clearTimeout(timer)
      stream?.getTracks().forEach((tm) => tm.stop())
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
    <div className="live-camera" role="dialog" aria-modal="true" aria-label={t('Live-Kamera')}>
      <div className={`live-frame${aim.ok ? ' live-ok' : ''}`}>
        <video ref={video} playsInline muted aria-hidden="true" />
        <svg className="live-guide" viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="42" />
        </svg>
      </div>
      <p className="live-hint" role="status" aria-live="polite">
        {aim.hint}
        {aim.ok ? ` (${Math.min(steady, STEADY)}/${STEADY})` : ''}
      </p>
      <p className="muted small">
        {t(
          'Scheibe auf eine helle Unterlage legen, Handy gerade darüber halten. Das Foto wird nur ausgewertet, nicht gespeichert.',
        )}
      </p>
      <div className="button-row">
        <button type="button" className="button" onClick={manual}>
          {t('Jetzt auslösen')}
        </button>
        <button type="button" className="button button-ghost" onClick={onClose}>
          {t('Abbrechen')}
        </button>
      </div>
    </div>
  )
}
