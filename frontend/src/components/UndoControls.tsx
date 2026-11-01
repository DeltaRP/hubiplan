// Rückgängig/Wiederherstellen in der Kopfleiste, Strg+Z / Strg+Y und ein kurzer Hinweis.
import { useEffect, useRef, useState } from 'react'
import { dismissNotice, groupSteps, redo, undo, useUndo } from './undo.ts'
import { t } from '../i18n/index.ts'

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    !!document.querySelector('.app-dialog-host')
  )
}

function StepList({
  head,
  list,
  onPick,
}: {
  head: string
  list: { setId: string; label: string }[]
  onPick: (count: number) => void
}) {
  if (list.length === 0) return null
  return (
    <>
      <p className="undo-history-head">{head}</p>
      <ul className="undo-steps">
        {groupSteps(list).map((g) => (
          <li key={g.key}>
            <button type="button" className="undo-step" onClick={() => onPick(g.upTo)}>
              <span>{g.label}</span>
              {g.count > 1 && (
                <span
                  className="undo-step-count"
                  aria-label={t('{count} Schritte', { count: g.count })}
                >
                  {g.count}×
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

export function UndoControls({ base }: { base: string }) {
  const { canUndo, canRedo, notice, undoList, redoList, busy } = useUndo(base)
  const [open, setOpen] = useState(false)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function close(e: MouseEvent | KeyboardEvent) {
      if (
        e instanceof KeyboardEvent ? e.key === 'Escape' : !panel.current?.contains(e.target as Node)
      )
        setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey) || e.altKey || isTyping(e.target)) return
      const key = e.key.toLowerCase()
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault()
        void undo(base)
      } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
        e.preventDefault()
        void redo(base)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [base])

  // Hinweis schließt nach 15 s, aber nicht solange Maus oder Tastaturfokus darauf sind
  // (WCAG 2.2.1): wer langsam liest oder hinspringt, verliert ihn nicht.
  const [heldNotice, setHeldNotice] = useState<typeof notice>(null)
  const holdNotice = heldNotice !== null && heldNotice === notice
  const setHoldNotice = (on: boolean) => setHeldNotice(on ? notice : null)
  useEffect(() => {
    if (!notice || holdNotice) return
    const tm = setTimeout(dismissNotice, 15000)
    return () => clearTimeout(tm)
  }, [notice, holdNotice])

  return (
    <>
      <div className="undo-controls" role="group" aria-label={t('Rückgängig und Wiederherstellen')}>
        <button
          type="button"
          className="button button-ghost undo-button"
          onClick={() => void undo(base)}
          disabled={!canUndo}
          title={t('Rückgängig (Strg+Z)')}
          aria-label={t('Letzte Änderung rückgängig machen')}
        >
          ↶
        </button>
        <button
          type="button"
          className="button button-ghost undo-button"
          onClick={() => void redo(base)}
          disabled={!canRedo}
          title={t('Wiederherstellen (Strg+Y)')}
          aria-label={t('Rückgängig Gemachtes wiederherstellen')}
        >
          ↷
        </button>
        <div className="undo-history" ref={panel}>
          <button
            type="button"
            className="button button-ghost undo-button"
            onClick={() => setOpen((o) => !o)}
            disabled={busy || (undoList.length === 0 && redoList.length === 0)}
            aria-expanded={open}
            title={t('Letzte Schritte')}
            aria-label={t('Letzte Schritte')}
          >
            ▾
          </button>
          {open && (
            <div className="undo-history-panel">
              <StepList
                head={t('Rückgängig machen bis einschließlich …')}
                list={undoList}
                onPick={(n) => {
                  setOpen(false)
                  void undo(base, n)
                }}
              />
              <StepList
                head={t('Wiederherstellen bis einschließlich …')}
                list={redoList}
                onPick={(n) => {
                  setOpen(false)
                  void redo(base, n)
                }}
              />
            </div>
          )}
        </div>
      </div>
      {notice && (
        <div
          className="undo-notice"
          role="status"
          onMouseEnter={() => setHoldNotice(true)}
          onMouseLeave={() => setHoldNotice(false)}
          onFocus={() => setHoldNotice(true)}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHoldNotice(false)
          }}
        >
          <span>{notice.text}</span>
          {notice.action === 'undo' && (
            <button type="button" className="link-button" onClick={() => void undo(base)}>
              {t('Rückgängig')}
            </button>
          )}
          {notice.action === 'redo' && (
            <button type="button" className="link-button" onClick={() => void redo(base)}>
              {t('Wiederherstellen')}
            </button>
          )}
          <button
            type="button"
            className="link-button undo-notice-close"
            onClick={dismissNotice}
            aria-label={t('Hinweis schließen')}
          >
            ×
          </button>
        </div>
      )}
    </>
  )
}
