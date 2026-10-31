// Einfacher Editor für Rundschreiben: Textfeld mit Knöpfen für fett, kursiv,
// Liste, Link und Platzhalter. Gespeichert wird die einfache Auszeichnung.
import { useRef } from 'react'
import { promptDialog } from '../dialog.ts'
import { renderMarkup } from './markup.tsx'

export function MarkupPreview({ text }: { text: string }) {
  return (
    <div className="markup-preview">
      {text.trim() ? renderMarkup(text) : <p className="muted">Noch kein Text.</p>}
    </div>
  )
}

export function MarkupEditor({
  value,
  onChange,
  placeholders,
  error,
}: {
  value: string
  onChange: (text: string) => void
  placeholders: { name: string; label: string }[]
  error?: string
}) {
  const area = useRef<HTMLTextAreaElement>(null)

  /** Markierten Text ersetzen und die Auswahl dahinter setzen. */
  function replace(build: (selected: string) => string) {
    const el = area.current
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const inserted = build(value.slice(start, end))
    onChange(value.slice(0, start) + inserted + value.slice(end))
    requestAnimationFrame(() => {
      if (!el) return
      el.focus()
      el.setSelectionRange(start + inserted.length, start + inserted.length)
    })
  }

  const wrap = (mark: string, fallback: string) =>
    replace((sel) => `${mark}${sel || fallback}${mark}`)

  function list() {
    replace((sel) => {
      const lines = (sel || 'Punkt').split('\n')
      const text = lines.map((l) => (l.startsWith('- ') ? l : `- ${l}`)).join('\n')
      const el = area.current
      const before = el ? value.slice(0, el.selectionStart) : value
      return before && !before.endsWith('\n') ? `\n${text}` : text
    })
  }

  async function link() {
    const el = area.current
    const selected = el ? value.slice(el.selectionStart, el.selectionEnd) : ''
    const url = await promptDialog({
      title: 'Link einfügen',
      label: 'Adresse (https://…)',
      defaultValue: 'https://',
      confirmLabel: 'Einfügen',
      danger: false,
    })
    if (!url || url === 'https://') return
    const href = /^(https?:\/\/|mailto:)/.test(url) ? url : `https://${url}`
    replace(() => `[${selected || href}](${href})`)
  }

  return (
    <div className={`field markup-editor${error ? ' field-invalid' : ''}`}>
      <div className="markup-toolbar" role="toolbar" aria-label="Formatierung">
        <button type="button" title="Fett" onClick={() => wrap('**', 'fett')}>
          <strong>F</strong>
        </button>
        <button type="button" title="Kursiv" onClick={() => wrap('*', 'kursiv')}>
          <em>K</em>
        </button>
        <button type="button" title="Liste" onClick={list}>
          • Liste
        </button>
        <button type="button" title="Link" onClick={() => void link()}>
          Link
        </button>
        <select
          aria-label="Platzhalter einfügen"
          value=""
          onChange={(e) => {
            const name = e.target.value
            if (name) replace(() => `{${name}}`)
          }}
        >
          <option value="">Platzhalter …</option>
          {placeholders.map((p) => (
            <option key={p.name} value={p.name} title={p.label}>
              {`{${p.name}}`} – {p.label}
            </option>
          ))}
        </select>
      </div>
      <textarea
        ref={area}
        aria-label="Text"
        rows={12}
        value={value}
        aria-invalid={!!error}
        onChange={(e) => onChange(e.target.value)}
      />
      {error ? (
        <small className="field-error">{error}</small>
      ) : (
        <small className="muted">
          **fett**, *kursiv*, Zeilen mit „- “ werden zur Liste. Platzhalter wie {'{Vorname}'} werden
          für jeden Empfänger ersetzt.
        </small>
      )}
    </div>
  )
}
