import { useEffect, useState } from 'react'
import { memberApi } from '../api/members.ts'
import type { MemberRow, PickedMember } from '../api/members.ts'

/** Mitglied per Suche auswählen (auch bei vielen Mitgliedern schnell).
 *  `search` ersetzt die Suche in der Mitgliederliste, z. B. für Untereinheiten. */
export function MemberPicker<T extends PickedMember = MemberRow>({
  orgId,
  value,
  onChange,
  label = 'Mitglied (optional)',
  search,
}: {
  orgId: number
  value: T | null
  onChange: (m: T | null) => void
  label?: string
  search?: (term: string) => Promise<T[]>
}) {
  const [term, setTerm] = useState('')
  // Treffer gehören immer zu genau einem Suchtext; alte Treffer sind nie auswählbar
  const [results, setResults] = useState<{ term: string; rows: T[] } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (term.trim().length < 2) return
    let alive = true
    const tm = setTimeout(() => {
      const found = search
        ? search(term)
        : memberApi
            .list(orgId, { suche: term, status: 'aktiv', page_size: 8 })
            .then((page) => page.results as unknown as T[])
      found
        .then((rows) => {
          if (!alive) return
          setFailed(null)
          setResults({ term, rows })
        })
        .catch(() => alive && setFailed(term))
    }, 250)
    return () => {
      alive = false
      clearTimeout(tm)
    }
  }, [orgId, term, search, attempt])

  const short = term.trim().length < 2
  const current = !short && results?.term === term ? results.rows : null
  const status = short
    ? term.trim()
      ? 'Mindestens 2 Zeichen eingeben.'
      : ''
    : failed === term
      ? 'Suche nicht möglich.'
      : !current
        ? 'Suche läuft …'
        : current.length === 0
          ? 'Keine Mitglieder gefunden.'
          : `${current.length} Treffer`

  if (value) {
    return (
      <div className="field">
        <span>{label}</span>
        <p>
          {value.last_name}, {value.first_name}{' '}
          <button type="button" className="link-button" onClick={() => onChange(null)}>
            entfernen
          </button>
        </p>
      </div>
    )
  }

  return (
    <div className="field member-picker">
      <span>{label}</span>
      <input
        type="search"
        aria-label={label}
        placeholder="Name eingeben …"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
      />
      <small className="muted" role="status" aria-live="polite">
        {status}
        {!short && failed === term && (
          <>
            {' '}
            <button type="button" className="link-button" onClick={() => setAttempt((n) => n + 1)}>
              Erneut versuchen
            </button>
          </>
        )}
      </small>
      {current && current.length > 0 && (
        <ul className="picker-results">
          {current.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => {
                  onChange(r)
                  setTerm('')
                  setResults(null)
                }}
              >
                {r.last_name}, {r.first_name}
                {r.email && <span className="muted small"> · {r.email}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
