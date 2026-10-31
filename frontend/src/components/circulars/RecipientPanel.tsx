// Empfängerauswahl eines Rundschreibens: Filter, Vorschau der Empfänger,
// einzelne hinzufügen oder abwählen.
import { useEffect, useId, useState } from 'react'
import { channelLabel, circularApi } from '../../api/circulars.ts'
import type {
  Candidate,
  CircularAudience,
  CircularBase,
  CircularFilters,
  CircularOptions,
  Recipients,
  SelectKey,
  SearchHit,
} from '../../api/circulars.ts'
import { errorMessage } from '../forms.ts'
import { Alert, Checkbox } from '../ui.tsx'
import { useTerms } from '../../org/terms.ts'

function toggle(list: number[] | undefined, id: number, on: boolean): number[] {
  const set = new Set(list ?? [])
  if (on) set.add(id)
  else set.delete(id)
  return [...set].sort((a, b) => a - b)
}

function numberOrNull(text: string): number | null {
  const n = Number.parseInt(text, 10)
  return Number.isNaN(n) ? null : n
}

function CheckList({
  legend,
  field,
  items,
  selected,
  filters,
  onFilters,
  onChange,
}: {
  legend: string
  field: SelectKey
  items: { id: number; name: string }[]
  selected: number[] | undefined
  filters: CircularFilters
  onFilters: (patch: Partial<CircularFilters>) => void
  onChange: (ids: number[]) => void
}) {
  // „alle“ und „nur ausgewählte“ sind getrennt gespeichert: „nur ausgewählte“ ohne
  // Häkchen heißt niemand, nie still alle (UI-Audit NMF-06).
  const chosen = selected ?? []
  const name = useId()
  if (items.length === 0) return null
  const some = (filters.selected ?? []).includes(field) || chosen.length > 0
  function setSome(on: boolean) {
    const rest = (filters.selected ?? []).filter((k) => k !== field)
    onFilters({ selected: on ? [...rest, field] : rest, ...(on ? {} : { [field]: [] }) })
  }
  return (
    <fieldset className="subcard stack-sm">
      <legend>{legend}</legend>
      <div className="button-row">
        <label className="checkbox">
          <input type="radio" name={name} checked={!some} onChange={() => setSome(false)} />
          <span>alle</span>
        </label>
        <label className="checkbox">
          <input type="radio" name={name} checked={some} onChange={() => setSome(true)} />
          <span>nur ausgewählte</span>
        </label>
      </div>
      {some && (
        <>
          {chosen.length === 0 && (
            <Alert kind="error">
              Noch nichts ausgewählt: So geht die Nachricht an niemanden. Bitte mindestens eins
              anhaken oder oben „alle“ wählen.
            </Alert>
          )}
          {items.map((item) => (
            <Checkbox
              key={item.id}
              label={item.name}
              checked={chosen.includes(item.id)}
              onChange={(on) => onChange(toggle(selected, item.id, on))}
            />
          ))}
        </>
      )}
    </fieldset>
  )
}

export function RecipientPanel({
  base,
  circularId,
  options,
  audience,
  filters,
  onFilters,
  version,
  fixed = false,
}: {
  base: CircularBase
  circularId: number
  options: CircularOptions
  audience: CircularAudience
  filters: CircularFilters
  onFilters: (patch: Partial<CircularFilters>) => void
  version: number
  /** Empfänger kommen aus einem Verteiler: nur anzeigen, keine Filter */
  fixed?: boolean
}) {
  const tm = useTerms()
  const [data, setData] = useState<Recipients | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let alive = true
    circularApi
      .recipients(base, circularId)
      .then((r) => {
        if (alive) {
          setData(r)
          setError(null)
        }
      })
      .catch((err) => alive && setError(errorMessage(err)))
    return () => {
      alive = false
    }
    // base ist ein neues Objekt je Aufruf; die Nummer genügt
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [circularId, version])

  useEffect(() => {
    if (query.trim().length < 2) {
      setHits([])
      return
    }
    let alive = true
    const timer = setTimeout(() => {
      circularApi
        .search(base, circularId, query.trim())
        .then((r) => alive && setHits(r))
        .catch(() => alive && setHits([]))
    }, 300)
    return () => {
      alive = false
      clearTimeout(timer)
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [query, circularId])

  const exclude = filters.exclude ?? []
  const include = filters.include ?? []
  function setExcluded(c: Candidate, excluded: boolean) {
    if (c.included && excluded) {
      onFilters({ include: include.filter((k) => k !== c.key) })
      return
    }
    onFilters({
      exclude: excluded ? [...exclude, c.key] : exclude.filter((k) => k !== c.key),
    })
  }

  const federation = options.org_type === 'federation'
  const boards = federation && audience === 'boards'
  const showGroup = federation || audience === 'departments' || audience === 'roles'
  const items = data?.items ?? []
  const shown = showAll ? items : items.slice(0, 100)
  const year = new Date().getFullYear()

  return (
    <div className="card card-wide">
      <h2>Empfänger</h2>
      {fixed ? (
        <p className="muted small">
          Die Empfänger kommen aus dem gewählten Verteiler. Ändern lassen sie sich dort unter
          Rundschreiben › Verteiler.
        </p>
      ) : (
        <>
          {audience === 'roles' ? (
            <>
              <p className="muted small">
                Geht an die aktuellen Inhaber der gewählten Rollen des Vereins, ohne die Rollen in
                den {tm.pl_dat}.
              </p>
              <CheckList
                field="club_roles"
                filters={filters}
                onFilters={onFilters}
                legend="Welche Rollen"
                items={options.club_roles ?? []}
                selected={filters.club_roles}
                onChange={(ids) => onFilters({ club_roles: ids })}
              />
              {(options.club_roles ?? []).some((r) => r.is_board) && (
                <div className="button-row">
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() =>
                      onFilters({
                        club_roles: (options.club_roles ?? [])
                          .filter((r) => r.is_board)
                          .map((r) => r.id),
                        selected: [
                          ...(filters.selected ?? []).filter((k) => k !== 'club_roles'),
                          'club_roles',
                        ],
                      })
                    }
                  >
                    Alle Vorstandsrollen auswählen
                  </button>
                </div>
              )}
            </>
          ) : audience === 'departments' ? (
            <>
              <p className="muted small">
                Geht an die aktuellen Inhaber von Rollen in den gewählten Einheiten.
              </p>
              <div className="grid-2">
                <CheckList
                  field="departments"
                  filters={filters}
                  onFilters={onFilters}
                  legend="Wo"
                  items={options.departments ?? []}
                  selected={filters.departments}
                  onChange={(ids) => onFilters({ departments: ids })}
                />
                <CheckList
                  field="role_names"
                  filters={filters}
                  onFilters={onFilters}
                  legend="Welche Rollen"
                  items={(options.role_names ?? []).map((name, i) => ({ id: i, name }))}
                  selected={(filters.role_names ?? [])
                    .map((n) => (options.role_names ?? []).indexOf(n))
                    .filter((i) => i >= 0)}
                  onChange={(ids) =>
                    onFilters({ role_names: ids.map((i) => (options.role_names ?? [])[i]) })
                  }
                />
              </div>
            </>
          ) : federation ? (
            <>
              <CheckList
                field="clubs"
                filters={filters}
                onFilters={onFilters}
                legend={tm.Pl}
                items={options.clubs ?? []}
                selected={filters.clubs}
                onChange={(ids) => onFilters({ clubs: ids })}
              />
              {boards ? (
                <p className="muted small">
                  Es schreiben die Inhaber von Vorstandsrollen mit Zugang; hat {tm.ein} keinen, geht
                  die Mail an die hinterlegte Kontaktadresse.
                </p>
              ) : (
                <>
                  <Checkbox
                    label={`nur an ${tm.e_akk} gemeldete Mitglieder`}
                    checked={!!filters.reported}
                    onChange={(on) => onFilters({ reported: on })}
                  />
                  {(options.honorary_titles ?? []).length > 0 && (
                    <CheckList
                      field="honorary_titles"
                      filters={filters}
                      onFilters={onFilters}
                      legend="Ehrungen"
                      items={options.honorary_titles ?? []}
                      selected={filters.honorary_titles}
                      onChange={(ids) => onFilters({ honorary_titles: ids })}
                    />
                  )}
                </>
              )}
            </>
          ) : (
            <>
              <div className="grid-2">
                <CheckList
                  field="member_types"
                  filters={filters}
                  onFilters={onFilters}
                  legend="Mitgliedsarten"
                  items={options.member_types ?? []}
                  selected={filters.member_types}
                  onChange={(ids) => onFilters({ member_types: ids })}
                />
                {!options.department && (
                  <CheckList
                    field="departments"
                    filters={filters}
                    onFilters={onFilters}
                    legend="Zugehörigkeit"
                    items={options.departments ?? []}
                    selected={filters.departments}
                    onChange={(ids) => onFilters({ departments: ids })}
                  />
                )}
              </div>
              {(options.honorary_titles ?? []).length > 0 && (
                <CheckList
                  field="honorary_titles"
                  filters={filters}
                  onFilters={onFilters}
                  legend="Ehrungen"
                  items={options.honorary_titles ?? []}
                  selected={filters.honorary_titles}
                  onChange={(ids) => onFilters({ honorary_titles: ids })}
                />
              )}
              <CheckList
                field="roles"
                filters={filters}
                onFilters={onFilters}
                legend="Inhaber von Rollen"
                items={(options.roles ?? []).map((r) => ({
                  id: r.id,
                  name: options.department ? r.name : `${r.name} (${r.department})`,
                }))}
                selected={filters.roles}
                onChange={(ids) => onFilters({ roles: ids })}
              />
              {!options.department && (
                <Checkbox
                  label="nur Mitglieder mit einer Vorstandsrolle"
                  checked={!!filters.board}
                  onChange={(on) => onFilters({ board: on })}
                />
              )}
              <div className="grid-3">
                <label className="field">
                  <span>Alter ab</span>
                  <input
                    type="number"
                    min={0}
                    max={120}
                    value={filters.age_min ?? ''}
                    onChange={(e) => onFilters({ age_min: numberOrNull(e.target.value) })}
                  />
                </label>
                <label className="field">
                  <span>Alter bis</span>
                  <input
                    type="number"
                    min={0}
                    max={120}
                    value={filters.age_max ?? ''}
                    onChange={(e) => onFilters({ age_max: numberOrNull(e.target.value) })}
                  />
                </label>
                <label className="field">
                  <span>nur Jubilare im Jahr</span>
                  <input
                    type="number"
                    min={1900}
                    max={2200}
                    placeholder={String(year)}
                    value={filters.jubilee_year ?? ''}
                    onChange={(e) => onFilters({ jubilee_year: numberOrNull(e.target.value) })}
                  />
                </label>
              </div>
            </>
          )}

          {audience === 'members' && (
            <div className="stack-sm">
              <label className="field">
                <span>Einzelnes Mitglied hinzufügen</span>
                <input
                  type="search"
                  placeholder="Name suchen …"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              {hits.length > 0 && (
                <ul className="chips">
                  {hits.map((h) => {
                    const already = items.some((c) => c.key === h.key && !c.excluded)
                    return (
                      <li key={h.key}>
                        <button
                          type="button"
                          className="chip"
                          disabled={already}
                          onClick={() => {
                            onFilters({
                              include: [...include.filter((k) => k !== h.key), h.key],
                              exclude: exclude.filter((k) => k !== h.key),
                            })
                            setQuery('')
                          }}
                        >
                          + {h.last_name}, {h.first_name}
                          {federation && ` (${h.club})`}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          )}
        </>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {data && (
        <>
          <p>
            <strong>
              {(data.counts.app ?? 0) > 0 && `${data.counts.app} per App · `}
              {data.counts.mail} per E-Mail · {data.counts.letter} per Brief
              {(data.counts.portal ?? 0) > 0 && ` · ${data.counts.portal} nur im Mitgliederbereich`}
            </strong>
            {!!data.counts.opted_out && ` · ${data.counts.opted_out} abgemeldet`}
            {!!data.counts.excluded && ` · ${data.counts.excluded} abgewählt`}
          </p>
          {items.length === 0 ? (
            <p className="muted">Für diese Auswahl gibt es keine Empfänger.</p>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    {showGroup && <th className="col-optional">{federation ? tm.Sg : 'Rolle'}</th>}
                    <th>Weg</th>
                    {!fixed && (
                      <th>
                        <span className="sr-only">Auswahl</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((c) => (
                    <tr key={c.key} className={c.excluded ? 'muted' : undefined}>
                      <td>
                        {c.last_name}
                        {c.first_name && `, ${c.first_name}`}
                        {c.included && <span className="badge">einzeln</span>}
                        {c.email && <div className="muted small">{c.email}</div>}
                      </td>
                      {showGroup && (
                        <td className="col-optional">
                          {federation ? c.club : (c.departments ?? []).join(', ')}
                        </td>
                      )}
                      <td>
                        {c.channel ? channelLabel[c.channel] : '–'}
                        {c.opted_out && <div className="muted small">{c.note}</div>}
                      </td>
                      {!fixed && (
                        <td>
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => setExcluded(c, !c.excluded)}
                          >
                            {c.excluded ? 'wieder aufnehmen' : 'abwählen'}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {items.length > shown.length && (
            <button type="button" className="link-button" onClick={() => setShowAll(true)}>
              Alle {items.length} anzeigen
            </button>
          )}
        </>
      )}
    </div>
  )
}
