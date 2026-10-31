// Mehrzeiliges Feld mit Beschriftung, Hinweis und Fehler (Impressum, Datenschutz).
export function TextArea({
  id,
  label,
  value,
  hint,
  error,
  rows = 3,
  onChange,
}: {
  id?: string
  label: string
  value: string
  hint?: string
  error?: string
  rows?: number
  onChange: (value: string) => void
}) {
  return (
    <label className={`field${error ? ' field-invalid' : ''}`}>
      <span>{label}</span>
      <textarea id={id} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} />
      {hint && !error && <small className="muted">{hint}</small>}
      {error && <small className="field-error">{error}</small>}
    </label>
  )
}
