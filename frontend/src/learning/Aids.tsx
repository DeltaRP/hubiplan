// Bausteine der Lernhilfen: <Why k />, <HowTo k />, <Term k>Wort</Term>.
// Texte kommen aus content.ts; hier nur Darstellung und Verhalten.
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  DECISIONS,
  HOWTOS,
  SOURCES,
  TERMS,
  termAnchor,
  tr,
  type DecisionKey,
  type HowKey,
  type SourceKey,
  type TermKey,
} from './content.ts'
import { useFirstOnPage, useLearning } from './LearningContext.tsx'
import './learning.css'

/** Breite, ab der Hilfen als Sheet von unten erscheinen */
export const NARROW = 700
/** Höher als dieser Anteil des Fensters: als Seitenpanel */
const TALL = 0.6
const GAP = 16

function InfoIcon() {
  return (
    <svg className="aid-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 7v4.2M8 4.6v.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export function SourceList({ sources }: { sources: SourceKey[] }) {
  if (!sources.length) return null
  return (
    <ul className="aid-sources">
      {sources.map((s) => (
        <li key={s}>
          {SOURCES[s].full}
          {'url' in SOURCES[s] && SOURCES[s].url && (
            <>
              {' '}
              <a href={SOURCES[s].url} target="_blank" rel="noreferrer noopener">
                Online
              </a>
            </>
          )}
        </li>
      ))}
    </ul>
  )
}

type Mode = 'below' | 'panel' | 'sheet'

/**
 * Lage einer Hilfe am Auslöser: darunter, wenn sie passt, sonst darüber, wenn dort
 * mehr Platz ist; nie über den Fensterrand hinaus, notfalls mit Scrollbereich
 * (UI-Audit NUI-05).
 */
// oxlint-disable-next-line react/only-export-components
export function placeNear(rect: DOMRect, height: number, width: number, shift = 0): CSSProperties {
  const left = Math.max(GAP, Math.min(rect.left - shift, window.innerWidth - width - GAP))
  const below = window.innerHeight - rect.bottom - 4 - GAP
  const above = rect.top - 4 - GAP
  if (height <= below || below >= above) {
    return { top: rect.bottom + 4, left, width, maxHeight: Math.max(below, 120), overflowY: 'auto' }
  }
  const h = Math.min(height, above)
  return { top: rect.top - 4 - h, left, width, maxHeight: above, overflowY: 'auto' }
}

/** Popover einer Hilfe: unter dem Titel, als Seitenpanel oder als Sheet von unten. */
function AidPopover({
  anchor,
  title,
  onClose,
  children,
}: {
  anchor: HTMLElement | null
  title: string
  onClose: (returnFocus: boolean) => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const [style, setStyle] = useState<CSSProperties>({ visibility: 'hidden' })
  const [mode, setMode] = useState<Mode>('below')

  const place = useCallback(() => {
    const box = ref.current
    if (!box || !anchor) return
    if (window.innerWidth <= NARROW) {
      setMode('sheet')
      setStyle({})
    } else if (box.scrollHeight > window.innerHeight * TALL) {
      // Volle Höhe des Inhalts, nicht die schon begrenzte Höhe der Box
      setMode('panel')
      setStyle({})
    } else {
      const width = Math.min(440, window.innerWidth - 2 * GAP)
      setMode('below')
      setStyle(placeNear(anchor.getBoundingClientRect(), box.scrollHeight, width))
    }
  }, [anchor])

  useLayoutEffect(() => {
    // Größe erst nach dem Rendern messbar, daher hier
    // oxlint-disable-next-line react/set-state-in-effect
    place()
    closeRef.current?.focus()
  }, [place])

  // Beim Scrollen mitwandern statt am alten Platz stehen zu bleiben
  useEffect(() => {
    const onScroll = (e: Event) => {
      if (ref.current?.contains(e.target as Node)) return
      place()
    }
    window.addEventListener('scroll', onScroll, true)
    return () => window.removeEventListener('scroll', onScroll, true)
  }, [place])

  useEffect(() => {
    const width = window.innerWidth
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (ref.current?.contains(target) || anchor?.contains(target)) return
      onClose(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose(true)
      }
    }
    const onResize = () => {
      if (window.innerWidth !== width) onClose(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', onResize)
    }
  }, [anchor, onClose])

  return (
    <div
      ref={ref}
      className={`aid-popover aid-popover-${mode}`}
      role="dialog"
      aria-label={title}
      style={style}
      // Esc schließt nur die Hilfe: Ohne stopPropagation erreicht der Tastendruck über
      // das Portal auch einen umgebenden Dialog (z. B. Termin) und schließt ihn mit
      // (UI-Audit NUI-06)
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return
        e.preventDefault()
        e.stopPropagation()
        onClose(true)
      }}
    >
      {mode === 'sheet' && <div className="aid-grip" aria-hidden="true" />}
      <div className="aid-popover-head">
        <h2 className="aid-popover-title">{title}</h2>
        <button
          ref={closeRef}
          type="button"
          className="aid-close"
          aria-label="Schließen"
          onClick={() => onClose(true)}
        >
          ×
        </button>
      </div>
      {children}
    </div>
  )
}

/** Aufklappbare Hilfe: natives details/summary, mit Skript als Popover. */
function Disclosure({
  prefix,
  title,
  children,
  summaryRef,
}: {
  prefix: string
  title: string
  children: ReactNode
  summaryRef?: (el: HTMLElement | null) => void
}) {
  const learning = useLearning()
  const id = useId()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const open = learning?.openId === id
  const setOpenId = learning?.setOpenId

  const close = useCallback(
    (returnFocus: boolean) => {
      setOpenId?.(null)
      if (returnFocus) anchor?.focus()
    },
    [setOpenId, anchor],
  )

  const toggle = () => setOpenId?.(open ? null : id)
  const ref = useCallback(
    (el: HTMLElement | null) => {
      setAnchor(el)
      summaryRef?.(el)
    },
    [summaryRef],
  )

  return (
    <>
      <details className="aid">
        <summary
          ref={ref}
          className="aid-summary"
          aria-expanded={open}
          onClick={(e) => {
            e.preventDefault()
            toggle()
          }}
          // Enter und Leertaste selbst behandeln, damit das Aufklappen nicht vom
          // Browser abhängt (der Standard würde das Element nur inline öffnen)
          onKeyDown={(e) => {
            if (e.key !== 'Enter' && e.key !== ' ') return
            e.preventDefault()
            toggle()
          }}
          onKeyUp={(e) => {
            if (e.key === ' ') e.preventDefault()
          }}
        >
          <InfoIcon />
          <span className="aid-prefix">{prefix}</span> <span className="aid-title">{title}</span>
        </summary>
        {!open && <div className="aid-body">{children}</div>}
      </details>
      {/* Ins body verlegt: so bleibt die Hilfe bedienbar, auch wenn sie in einem
          gesperrten Formular (fieldset disabled) steht */}
      {open &&
        createPortal(
          <AidPopover anchor={anchor} title={title} onClose={close}>
            <div className="aid-body">{children}</div>
          </AidPopover>,
          document.body,
        )}
    </>
  )
}

/** „Warum?“ an einer Entscheidung. */
export function Why({ k }: { k: DecisionKey }) {
  const learning = useLearning()
  const entry = DECISIONS[k]
  const [undo, setUndo] = useState(false)
  // Speichern fehlgeschlagen: Hinweis statt „ausgeblendet“ (Audit 29.10. FE-F02)
  const [failed, setFailed] = useState(false)
  const statusRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLElement | null>(null)
  const restoreFocus = useRef(false)
  const visible =
    !!learning &&
    learning.ready &&
    learning.hasFeature(entry.feature) &&
    (!('basic' in entry && entry.basic) || learning.enabled)
  const hidden = !!learning?.hidden.has(k)
  const first = useFirstOnPage(
    visible && !hidden && 'once' in entry && entry.once ? `why:${k}` : null,
  )
  const setTitleRef = useCallback((el: HTMLElement | null) => {
    titleRef.current = el
  }, [])

  useEffect(() => {
    if (!undo) return
    statusRef.current?.focus()
    let timer: number | undefined
    const start = () => {
      timer = window.setTimeout(() => {
        if (!statusRef.current?.contains(document.activeElement)) setUndo(false)
        else start()
      }, 6000)
    }
    start()
    return () => window.clearTimeout(timer)
  }, [undo])

  useEffect(() => {
    if (!hidden && restoreFocus.current) {
      restoreFocus.current = false
      titleRef.current?.focus()
    }
  }, [hidden])

  if (!learning || !visible) return null
  if (hidden) {
    if (!undo) return null
    return (
      <div className="aid-undo" role="status" tabIndex={-1} ref={statusRef}>
        Erklärung ausgeblendet ·{' '}
        <button
          type="button"
          className="link-button"
          onClick={() => {
            restoreFocus.current = true
            setUndo(false)
            setFailed(false)
            learning.show(k).catch(() => {
              restoreFocus.current = false
              setUndo(true)
              setFailed(true)
            })
          }}
        >
          {failed ? 'Erneut versuchen' : 'Rückgängig'}
        </button>
        {failed && ' · Die Einstellung konnte nicht gespeichert werden.'}
      </div>
    )
  }
  if (!first) return null
  return (
    <Disclosure prefix="Warum?" title={tr(entry.title)} summaryRef={setTitleRef}>
      <p>{tr(entry.text)}</p>
      <SourceList sources={entry.sources} />
      {failed && (
        <p className="small" role="alert">
          Die Einstellung konnte nicht gespeichert werden. Erneut versuchen.
        </p>
      )}
      <button
        type="button"
        className="aid-hide"
        onClick={() => {
          learning.setOpenId(null)
          setUndo(true)
          setFailed(false)
          learning.hide(k).catch(() => {
            setUndo(false)
            setFailed(true)
          })
        }}
      >
        Nicht mehr zeigen
      </button>
    </Disclosure>
  )
}

/** „Wie gerechnet?“ bzw. „So funktioniert es:“ an Ergebnissen und Bausteinen. */
export function HowTo({ k }: { k: HowKey }) {
  const learning = useLearning()
  const entry = HOWTOS[k]
  if (!learning || !learning.ready || !learning.hasFeature(entry.feature)) return null
  const example = 'example' in entry ? entry.example : undefined
  return (
    <Disclosure
      prefix={entry.kind === 'calc' ? 'Wie gerechnet?' : 'So funktioniert es:'}
      title={tr(entry.title)}
    >
      <p>{tr(entry.text)}</p>
      {example && (
        <table className="aid-example">
          <thead>
            <tr>
              {example.head.map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {example.rows.map((row) => (
              <tr key={row.join('|')}>
                {row.map((cell, i) => (
                  <td key={i}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <SourceList sources={entry.sources} />
    </Disclosure>
  )
}

/** Fachbegriff mit „?“: kleine Box mit Bedeutung, Beispiel und Glossarlink. */
export function Term({ k, children, note }: { k: TermKey; children: ReactNode; note?: string }) {
  const learning = useLearning()
  const entry = TERMS[k]
  const id = useId()
  const boxId = `${id}-box`
  const wrapRef = useRef<HTMLSpanElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [tooltip, setTooltip] = useState<string | null>(null)
  const [style, setStyle] = useState<CSSProperties>({ visibility: 'hidden' })
  const active =
    !!learning && learning.ready && learning.enabled && learning.hasFeature(entry.feature)
  const first = useFirstOnPage(active && 'simple' in entry && entry.simple ? `term:${k}` : null)
  const shown = active && first
  const open = shown && learning?.openId === id

  // Tooltip der Zelle übernehmen: eine Hilfe pro Stelle, nicht zwei
  useLayoutEffect(() => {
    if (!shown) return
    const cell = wrapRef.current?.parentElement?.closest<HTMLElement>('[title]')
    const text = cell?.getAttribute('title')
    if (!cell || !text) return
    cell.removeAttribute('title')
    setTooltip(text)
    return () => {
      cell.setAttribute('title', text)
    }
  }, [shown])

  const boxRef = useRef<HTMLSpanElement>(null)
  const placeBox = useCallback(() => {
    if (!buttonRef.current) return
    const width = Math.min(320, window.innerWidth - 2 * GAP)
    const height = boxRef.current?.scrollHeight ?? 0
    setStyle(placeNear(buttonRef.current.getBoundingClientRect(), height, width, 8))
  }, [])
  useLayoutEffect(() => {
    if (!open) return
    placeBox()
    const onScroll = (e: Event) => {
      if (!boxRef.current?.contains(e.target as Node)) placeBox()
    }
    window.addEventListener('scroll', onScroll, true)
    return () => window.removeEventListener('scroll', onScroll, true)
  }, [open, placeBox])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) learning?.setOpenId(null)
    }
    const width = window.innerWidth
    const onResize = () => {
      if (window.innerWidth !== width) learning?.setOpenId(null)
    }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('resize', onResize)
    }
  }, [open, learning])

  if (!shown || !learning) return <>{children}</>
  const name = tr(entry.name)
  const extra = note ?? tooltip

  function onKey(e: ReactKeyboardEvent) {
    if (e.key === 'Escape' && open) {
      e.preventDefault()
      e.stopPropagation()
      learning?.setOpenId(null)
      buttonRef.current?.focus()
    }
  }

  return (
    <span
      className="term"
      ref={wrapRef}
      onKeyDown={onKey}
      onBlur={(e) => {
        if (open && !wrapRef.current?.contains(e.relatedTarget as Node | null))
          learning.setOpenId(null)
      }}
    >
      {children}
      <button
        ref={buttonRef}
        type="button"
        className="term-q"
        aria-label={`${name}: Was heißt das?`}
        aria-expanded={open}
        aria-controls={boxId}
        onClick={() => learning.setOpenId(open ? null : id)}
      >
        <span aria-hidden="true">?</span>
      </button>
      <span
        id={boxId}
        ref={boxRef}
        className="term-box"
        role="dialog"
        aria-label={name}
        hidden={!open}
        style={open ? style : undefined}
      >
        <strong className="term-name">{name}</strong>
        <span className="term-meaning">{tr(entry.meaning)}</span>
        {extra && <span className="term-note">{extra}</span>}
        <span className="term-example">{tr(entry.example)}</span>
        <a className="term-link" href={`/glossar#${termAnchor(k)}`} target="_blank" rel="noopener">
          im Glossar ↗
        </a>
      </span>
    </span>
  )
}
