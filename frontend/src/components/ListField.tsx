// Eingabefeld für Listen ("10, 25, 40"): Der getippte Text bleibt stehen,
// damit Komma, Leerzeichen und halbe Eingaben nicht sofort verschwinden.
// Nach außen geht immer die geparste Liste; beim Verlassen wird der Text
// ordentlich formatiert.
import { useState } from 'react'
import type { InputHTMLAttributes } from 'react'

type Props<T> = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & {
  value: T[]
  onChange: (value: T[]) => void
  parse: (text: string) => T[]
  label?: string
  error?: string
  hint?: string
}

const same = (a: unknown[], b: unknown[]) => JSON.stringify(a) === JSON.stringify(b)

export function ListInput<T>({
  value,
  onChange,
  parse,
  label,
  error,
  hint,
  onBlur,
  ...input
}: Props<T>) {
  const [state, setState] = useState(() => ({ text: value.join(', '), synced: value }))
  const text = state.text
  const setText = (t: string) => setState({ text: t, synced: value })

  // Wert von außen geändert (z. B. Rückgängig oder Neuladen): Text nachziehen.
  if (!same(value, state.synced)) {
    setState({ text: same(parse(text), value) ? text : value.join(', '), synced: value })
  }

  const field = (
    <input
      {...input}
      value={text}
      aria-invalid={label ? !!error : input['aria-invalid']}
      onChange={(e) => {
        const next = parse(e.target.value)
        setState({ text: e.target.value, synced: next })
        if (!same(next, value)) onChange(next)
      }}
      onBlur={(e) => {
        setText(parse(text).join(', '))
        onBlur?.(e)
      }}
    />
  )
  if (!label) return field
  return (
    <label className={`field${error ? ' field-invalid' : ''}`}>
      <span>{label}</span>
      {field}
      {hint && !error && <small className="muted">{hint}</small>}
      {error && <small className="field-error">{error}</small>}
    </label>
  )
}
