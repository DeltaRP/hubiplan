// Darstellung der app-eigenen Rückfragen; aufgerufen wird sie über dialog.ts.
import { useId, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

export type ConfirmOptions = {
  /** Überschrift; ohne eigene Überschrift wird die Frage selbst zur Überschrift. */
  title?: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Rot hervorgehoben, z. B. für Löschen. Standard: true. */
  danger?: boolean
}

export type PromptOptions = {
  title: string
  message?: string
  label: string
  defaultValue?: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
}

export type AlertOptions = {
  title?: string
  message?: string
  okLabel?: string
}

export type ChoiceOptions = {
  title: string
  message?: string
  /** Knöpfe von links nach rechts; der erste mit primary ist die Vorgabe (Enter). */
  choices: {
    value: string
    label: string
    /** kurze Erklärung unter der Beschriftung; dann stehen die Knöpfe untereinander */
    hint?: string
    primary?: boolean
    danger?: boolean
  }[]
  /** Ergebnis bei Esc oder Klick neben den Dialog */
  cancelValue: string
}

export type DialogSpec =
  | { kind: 'choice'; options: ChoiceOptions }
  | { kind: 'confirm'; options: ConfirmOptions }
  | { kind: 'prompt'; options: PromptOptions }
  | { kind: 'alert'; options: AlertOptions }

const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'

export function AppDialog({
  spec,
  onDone,
}: {
  spec: DialogSpec
  onDone: (result: boolean | string | null) => void
}) {
  const { options } = spec
  const titleId = useId()
  const messageId = useId()
  const ref = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState(
    spec.kind === 'prompt' ? (spec.options.defaultValue ?? '') : '',
  )

  const title = options.title ?? options.message ?? ''
  const message = options.title ? options.message : undefined
  const danger =
    (spec.kind === 'confirm' || spec.kind === 'prompt') &&
    (spec.options.danger ?? spec.kind === 'confirm')
  const cancel = () =>
    onDone(
      spec.kind === 'choice'
        ? spec.options.cancelValue
        : spec.kind === 'confirm'
          ? false
          : spec.kind === 'prompt'
            ? null
            : true,
    )

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      cancel()
      return
    }
    if (e.key !== 'Tab' || !ref.current) return
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (spec.kind === 'choice') {
      const main = spec.options.choices.find((c) => c.primary) ?? spec.options.choices[0]
      onDone(main.value)
      return
    }
    onDone(spec.kind === 'prompt' ? value : true)
  }

  const confirmLabel =
    spec.kind === 'alert'
      ? (spec.options.okLabel ?? 'OK')
      : spec.kind === 'choice'
        ? ''
        : (spec.options.confirmLabel ?? (spec.kind === 'confirm' ? 'Ja' : 'OK'))
  const cancelLabel =
    spec.kind === 'alert' || spec.kind === 'choice'
      ? null
      : (spec.options.cancelLabel ?? 'Abbrechen')

  return (
    <div className="modal-backdrop app-dialog-backdrop" onMouseDown={cancel}>
      <div
        className="modal card app-dialog"
        role={spec.kind === 'prompt' ? 'dialog' : 'alertdialog'}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={message ? messageId : undefined}
        ref={ref}
        onKeyDown={onKeyDown}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <form onSubmit={submit}>
          <h2 id={titleId}>{title}</h2>
          {message && (
            <p id={messageId} className="app-dialog-message">
              {message}
            </p>
          )}
          {spec.kind === 'prompt' && (
            <label className="field">
              <span>{spec.options.label}</span>
              <input autoFocus value={value} onChange={(e) => setValue(e.target.value)} />
            </label>
          )}
          {spec.kind === 'choice' ? (
            <div
              className={`button-row app-dialog-actions${
                spec.options.choices.some((c) => c.hint) ? ' app-dialog-choices' : ''
              }`}
            >
              {spec.options.choices.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  className={`button ${
                    c.danger ? 'button-danger-solid' : c.primary ? 'button-primary' : 'button-ghost'
                  }`}
                  autoFocus={c.primary}
                  onClick={() => onDone(c.value)}
                >
                  {c.label}
                  {c.hint && <span className="choice-hint">{c.hint}</span>}
                </button>
              ))}
            </div>
          ) : (
            <div className="button-row app-dialog-actions">
              {cancelLabel && (
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={cancel}
                  autoFocus={spec.kind === 'confirm'}
                >
                  {cancelLabel}
                </button>
              )}
              <button
                type="submit"
                className={`button ${danger ? 'button-danger-solid' : 'button-primary'}`}
                autoFocus={spec.kind === 'alert'}
              >
                {confirmLabel}
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
