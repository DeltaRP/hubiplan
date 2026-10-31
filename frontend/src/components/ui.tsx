// Kleine, wiederverwendbare Bausteine für Formulare und Seiten.
import { useId } from 'react'
import type { ChangeEvent, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { NavLink } from 'react-router-dom'
import { useSubNav } from './subnav.ts'
import type { AutoSave, SaveState } from './forms.ts'

/**
 * Beschriftung, Hinweis und Fehler eines Feldes. Hinweis und Fehler hängen per
 * aria-describedby am Feld, damit sie nicht Teil des Feldnamens werden (WCAG 1.3.1, 3.3.1).
 */
function FieldFrame({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className={`field${error ? ' field-invalid' : ''}`}>
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      {children}
      {hint && !error && (
        <small className="muted" id={`${id}-hinweis`}>
          {hint}
        </small>
      )}
      {error && (
        <small className="field-error" id={`${id}-fehler`}>
          {error}
        </small>
      )}
    </div>
  )
}

function noteId(id: string, error?: string, hint?: string) {
  if (error) return `${id}-fehler`
  return hint ? `${id}-hinweis` : undefined
}

export function Field({
  label,
  error,
  hint,
  id,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }) {
  const own = useId()
  const fieldId = id ?? own
  return (
    <FieldFrame id={fieldId} label={label} error={error} hint={hint}>
      <input
        {...input}
        id={fieldId}
        aria-invalid={!!error}
        aria-describedby={
          [input['aria-describedby'], noteId(fieldId, error, hint)].filter(Boolean).join(' ') ||
          undefined
        }
      />
    </FieldFrame>
  )
}

export function SelectField({
  label,
  error,
  hint,
  id,
  children,
  ...select
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string; hint?: string }) {
  const own = useId()
  const fieldId = id ?? own
  return (
    <FieldFrame id={fieldId} label={label} error={error} hint={hint}>
      <select
        {...select}
        id={fieldId}
        aria-invalid={!!error}
        aria-describedby={
          [select['aria-describedby'], noteId(fieldId, error, hint)].filter(Boolean).join(' ') ||
          undefined
        }
      >
        {children}
      </select>
    </FieldFrame>
  )
}

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
  hint,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
  /** kurze Erklärung hinter der Beschriftung */
  hint?: string
}) {
  return (
    <label className="checkbox">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint && <span className="muted small"> · {hint}</span>}
      </span>
    </label>
  )
}

export function Alert({
  kind,
  children,
}: {
  kind: 'error' | 'success' | 'info'
  children: ReactNode
}) {
  return (
    <p className={`alert alert-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {children}
    </p>
  )
}

export function Tabs({ items }: { items: { to: string; label: string }[] }) {
  // Im App-Rahmen stehen die Punkte in der Seitenleiste (UX-Audit 31.10. W09)
  if (useSubNav(items)) return null
  return (
    <nav className="tabs" aria-label="Bereiche">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} className="tab" end>
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

const SAVE_TEXT: Record<SaveState, string> = {
  idle: 'Änderungen werden automatisch gespeichert.',
  pending: 'Ungespeicherte Änderungen …',
  saving: 'Wird gespeichert …',
  saved: '✓ Gespeichert',
  error: 'Nicht gespeichert',
}

/** Stand des Autospeicherns oben am Formular. */
export function SaveStatus(
  props: { auto: AutoSave } | { state: SaveState; error?: string | null },
) {
  const auto = 'auto' in props ? props.auto : null
  const state = auto ? auto.state : (props as { state: SaveState }).state
  const error = auto ? auto.error : (props as { error?: string | null }).error
  return (
    <div className={`save-status save-status-${state}`}>
      <p role="status" aria-live="polite">
        {SAVE_TEXT[state]}
        {state === 'error' && error ? `: ${error}` : ''}
        {state === 'error' && auto ? ' Deine Eingaben bleiben erhalten.' : ''}
      </p>
      {state === 'error' && auto && (
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={() => void auto.flush()}>
            Erneut versuchen
          </button>
          {auto.discard && (
            <button type="button" className="button button-ghost" onClick={auto.discard}>
              Änderungen verwerfen
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/** Ladefehler mit „Erneut laden“; der Bereich bleibt stehen, statt endlos „Lädt …“ zu zeigen. */
/**
 * Zustand einer Liste beim Nachladen mit vorhandenen Daten (UI-Audit 29.10. NMF-05):
 * „wird aktualisiert“, oder nach einem Fehler der Hinweis, dass noch die alten
 * Ergebnisse zu sehen sind.
 */
export function Freshness({
  refreshing,
  error,
  onRetry,
}: {
  refreshing: boolean
  error?: string | null
  onRetry?: () => void
}) {
  if (error) {
    return (
      <LoadError
        message={`Aktualisierung fehlgeschlagen (${error}). Angezeigt werden noch die vorherigen Ergebnisse.`}
        onRetry={onRetry}
      />
    )
  }
  return (
    <p className="muted small freshness" role="status" aria-live="polite">
      {refreshing ? 'Ergebnisse werden aktualisiert …' : ''}
    </p>
  )
}

export function LoadError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="alert alert-error" role="alert">
      {message}
      {onRetry && (
        <>
          {' '}
          <button type="button" className="link-button" onClick={onRetry}>
            Erneut laden
          </button>
        </>
      )}
    </div>
  )
}
