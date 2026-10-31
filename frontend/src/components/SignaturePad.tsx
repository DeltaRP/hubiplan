// Unterschrift mit Finger, Stift oder Maus (Quittungen, Mein Konto › Briefvorlage & Unterschrift).
// Gespeichert wird nur die Form der Linien, keine Zeit- oder Druckwerte.
import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import type { SignatureInput, StoredShape } from '../api/finance.ts'

type Point = [number, number]

/** Zeichenfeld; meldet nach jedem Strich die Unterschrift (oder null, wenn leer). */
export function SignaturePad({
  onChange,
  label = 'Unterschrift',
  className = '',
}: {
  onChange: (value: SignatureInput | null) => void
  label?: string
  className?: string
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const strokes = useRef<Point[][]>([])
  const drawing = useRef(false)
  const [empty, setEmpty] = useState(true)

  // Auflösung an die Größe anpassen (scharf auf hochauflösenden Displays)
  useEffect(() => {
    const el = canvas.current
    if (!el) return
    const resize = () => {
      const ratio = window.devicePixelRatio || 1
      const rect = el.getBoundingClientRect()
      el.width = Math.max(1, Math.round(rect.width * ratio))
      el.height = Math.max(1, Math.round(rect.height * ratio))
      redraw()
    }
    resize()
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
    observer?.observe(el)
    return () => observer?.disconnect()
  }, [])

  function ctx() {
    const el = canvas.current
    const c = el?.getContext('2d')
    if (!el || !c) return null
    const ratio = el.width / Math.max(1, el.getBoundingClientRect().width)
    c.setTransform(ratio, 0, 0, ratio, 0, 0)
    c.lineWidth = 2.5
    c.lineCap = 'round'
    c.lineJoin = 'round'
    c.strokeStyle = '#1a2a6c'
    return c
  }

  function redraw() {
    const el = canvas.current
    const c = ctx()
    if (!el || !c) return
    c.clearRect(0, 0, el.width, el.height)
    for (const s of strokes.current) {
      c.beginPath()
      s.forEach(([x, y], i) => (i === 0 ? c.moveTo(x, y) : c.lineTo(x, y)))
      if (s.length === 1) c.lineTo(s[0][0] + 0.5, s[0][1])
      c.stroke()
    }
  }

  function point(e: ReactPointerEvent<HTMLCanvasElement>): Point {
    const rect = e.currentTarget.getBoundingClientRect()
    return [Math.round(e.clientX - rect.left), Math.round(e.clientY - rect.top)]
  }

  function emit() {
    const el = canvas.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const has = strokes.current.some((s) => s.length > 1)
    setEmpty(!has)
    onChange(
      has
        ? {
            width: Math.max(10, Math.round(rect.width)),
            height: Math.max(10, Math.round(rect.height)),
            strokes: strokes.current.map((s) => s.map((p) => [p[0], p[1]] as Point)),
          }
        : null,
    )
  }

  function down(e: ReactPointerEvent<HTMLCanvasElement>) {
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    drawing.current = true
    strokes.current.push([point(e)])
    redraw()
  }

  function move(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return
    e.preventDefault()
    const s = strokes.current[strokes.current.length - 1]
    const p = point(e)
    const last = s[s.length - 1]
    if (last && last[0] === p[0] && last[1] === p[1]) return
    s.push(p)
    const c = ctx()
    if (c && last) {
      c.beginPath()
      c.moveTo(last[0], last[1])
      c.lineTo(p[0], p[1])
      c.stroke()
    }
  }

  function up() {
    if (!drawing.current) return
    drawing.current = false
    emit()
  }

  function clear() {
    strokes.current = []
    redraw()
    emit()
  }

  return (
    <div className={`signature-pad ${className}`}>
      <canvas
        ref={canvas}
        aria-label={label}
        role="img"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        onPointerLeave={up}
      />
      <div className="signature-line" aria-hidden="true">
        <span>{label}</span>
      </div>
      {!empty && (
        <button type="button" className="link-button signature-clear" onClick={clear}>
          Löschen
        </button>
      )}
    </div>
  )
}

/** Gespeicherte Unterschrift als Bild (auf die Tinte zugeschnitten). */
export function SignatureImage({ shape, label }: { shape: StoredShape; label: string }) {
  const strokes = shape.s.filter((s) => s.length >= 2)
  if (!strokes.length) return null
  const xs = strokes.flatMap((s) => s.filter((_, i) => i % 2 === 0))
  const ys = strokes.flatMap((s) => s.filter((_, i) => i % 2 === 1))
  const pad = 8
  const minX = Math.min(...xs) - pad
  const minY = Math.min(...ys) - pad
  const w = Math.max(...xs) - minX + pad
  const h = Math.max(...ys) - minY + pad
  return (
    <svg
      className="signature-image"
      viewBox={`${minX} ${minY} ${w} ${h}`}
      role="img"
      aria-label={label}
      preserveAspectRatio="xMidYMid meet"
    >
      {strokes.map((s, i) => (
        <polyline
          key={i}
          points={s
            .reduce<string[]>((acc, v, j) => {
              if (j % 2 === 0) acc.push(`${v},${s[j + 1]}`)
              return acc
            }, [])
            .join(' ')}
          fill="none"
          stroke="#1a2a6c"
          strokeWidth={Math.max(3, w / 250)}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  )
}

/**
 * Vollbild zum Unterschreiben: oben, was bestätigt wird, darunter das Zeichenfeld.
 * Im Browser mit Fullscreen-API und Querformat, wo das geht; sonst (iPhone) eine
 * Ebene über der Seite mit dem Hinweis, das Telefon quer zu halten.
 */
export function SignatureFullscreen({
  title,
  text,
  onConfirm,
  onCancel,
  busy = false,
  error = null,
}: {
  title: string
  text: string
  onConfirm: (value: SignatureInput) => void
  onCancel: () => void
  busy?: boolean
  /** Fehler beim Speichern: steht im Vollbild, die Zeichnung bleibt (UX-Audit 31.10. C01) */
  error?: string | null
}) {
  const box = useRef<HTMLDivElement>(null)
  const head = useRef<HTMLParagraphElement>(null)
  const titleId = useId()
  const [value, setValue] = useState<SignatureInput | null>(null)
  const [portrait, setPortrait] = useState(false)
  // Neu gerendert wird oft (neue Funktion je Render); Vollbild soll nur einmal starten
  const cancel = useRef(onCancel)
  useEffect(() => {
    cancel.current = onCancel
  }, [onCancel])

  useEffect(() => {
    const el = box.current
    const doc = document as Document & { webkitExitFullscreen?: () => Promise<void> }
    let entered = false
    if (el?.requestFullscreen) {
      el.requestFullscreen()
        .then(() => {
          entered = true
          const orientation = screen.orientation as ScreenOrientation & {
            lock?: (o: string) => Promise<void>
          }
          return orientation?.lock?.('landscape')
        })
        .catch(() => undefined)
    }
    const check = () => setPortrait(window.innerHeight > window.innerWidth)
    check()
    window.addEventListener('resize', check)
    // Scrollen der Seite dahinter sperren
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && cancel.current()
    window.addEventListener('keydown', onKey)
    // Wie beim normalen Dialog: Fokus hinein, Seite dahinter sperren, danach zurück (C02)
    const previous = document.activeElement as HTMLElement | null
    const host = el?.parentElement
    const others = Array.from(document.body.children).filter(
      (other) => other !== host && !other.hasAttribute('inert') && other.tagName !== 'SCRIPT',
    )
    for (const other of others) other.setAttribute('inert', '')
    head.current?.focus()
    return () => {
      window.removeEventListener('resize', check)
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      for (const other of others) other.removeAttribute('inert')
      if (previous && document.contains(previous)) previous.focus()
      if (entered && document.fullscreenElement) void doc.exitFullscreen?.().catch(() => undefined)
    }
  }, [])

  // Tab bleibt im Vollbild
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'Tab' || !box.current) return
    const items = Array.from(
      box.current.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex="0"]'),
    )
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (e.shiftKey && (active === first || active === head.current)) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return createPortal(
    <div className="signature-fullscreen-host">
      <div
        ref={box}
        className="signature-fullscreen"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
      >
        <div className="signature-fullscreen-head">
          <p className="signature-fullscreen-text" id={titleId} ref={head} tabIndex={-1}>
            <span className="sr-only">{title}: </span>
            {text}
          </p>
          {error && (
            <p className="alert alert-error" role="alert">
              Unterschrift nicht gespeichert: {error} Deine Zeichnung bleibt erhalten; prüfe die
              Verbindung und tippe erneut auf „Bestätigen“.
            </p>
          )}
          {portrait && (
            <p className="muted small">Tipp: Telefon quer halten, dann ist mehr Platz.</p>
          )}
        </div>
        <SignaturePad onChange={setValue} label={title} className="signature-pad-full" />
        <div className="button-row signature-fullscreen-actions">
          <button type="button" className="button button-ghost" onClick={onCancel} disabled={busy}>
            Abbrechen
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={() => value && onConfirm(value)}
            disabled={!value || busy}
          >
            {busy ? 'Speichert …' : 'Bestätigen'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
