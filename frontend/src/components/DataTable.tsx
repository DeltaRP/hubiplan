// Wiederverwendbare Tabelle: Sortieren per Spaltenkopf, Suche, Filter je Spalte,
// Seiten mit 10, 20 oder 50 Zeilen und eine Spalte für Aktionen (Icons).
//
//   <DataTable
//     label="Züge"
//     rows={departments}
//     rowKey={(d) => d.id}
//     columns={[
//       { key: 'name', label: 'Name', value: (d) => d.name },
//       { key: 'active', label: 'Status', value: (d) => (d.is_active ? 'aktiv' : 'inaktiv'), filter: true },
//     ]}
//     actions={(d) => <IconButton … />}
//   />
//
// Sortiert, gefiltert und geblättert wird im Browser; das reicht für Listen bis
// zu einigen tausend Zeilen (Abteilungen, Vereine). Für sehr große Listen wie die
// Mitgliederliste bleibt die serverseitige Variante.
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { t } from '../i18n/index.ts'

export type CellValue = string | number | boolean | null | undefined

export interface Column<T> {
  key: string
  label: string
  /** Wert zum Sortieren, Suchen und Filtern */
  value: (row: T) => CellValue
  /** Anzeige in der Zelle; sonst der Wert als Text */
  render?: (row: T) => ReactNode
  /** Text für die Suche; sonst der Wert. `false`: Spalte nicht durchsuchen */
  searchText?: ((row: T) => string) | false
  sortable?: boolean
  /**
   * Auswahlfilter über dieser Spalte. `true`: Auswahl aus den vorkommenden Werten.
   * Mit `options` feste Auswahl; `initial` ist der vorgewählte Wert ('' = alle).
   */
  filter?:
    | boolean
    | {
        allLabel?: string
        options?: { value: string; label: string }[]
        initial?: string
      }
  /** Zahlen rechtsbündig */
  numeric?: boolean
  /** Auf schmalen Bildschirmen ausblenden */
  optional?: boolean
  /** Feste Breite (CSS), nur mit `fixedLayout` wirksam */
  width?: string
}

export interface DataTableProps<T> {
  /** Name der Tabelle für Screenreader, z. B. „Züge“ */
  label: string
  rows: T[]
  columns: Column<T>[]
  rowKey: (row: T) => string | number
  /** Icons am Zeilenende (Bearbeiten, Löschen …) */
  actions?: (row: T) => ReactNode
  initialSort?: { key: string; dir?: 'asc' | 'desc' }
  pageSizes?: number[]
  searchPlaceholder?: string
  /** Text bei leerer Liste bzw. wenn Suche/Filter nichts finden */
  emptyText?: string
  /** z. B. „3 Züge“ */
  countText?: (count: number, total: number) => string
  rowClassName?: (row: T) => string | undefined
  /** Zusätzliche Bedienelemente rechts in der Filterleiste */
  toolbar?: ReactNode
  /**
   * Feste Spaltenbreiten (`width` je Spalte): mehrere Tabellen untereinander
   * haben dann gleich breite Spalten, egal wie lang die Inhalte sind.
   */
  fixedLayout?: boolean
}

const collator = new Intl.Collator('de', { numeric: true, sensitivity: 'base' })

function compare(a: CellValue, b: CellValue): number {
  const emptyA = a === null || a === undefined || a === ''
  const emptyB = b === null || b === undefined || b === ''
  if (emptyA || emptyB) return emptyA === emptyB ? 0 : emptyA ? 1 : -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(b) - Number(a)
  return collator.compare(String(a), String(b))
}

const asText = (v: CellValue) => (v === null || v === undefined ? '' : String(v))

function filterSpec<T>(c: Column<T>) {
  if (!c.filter) return null
  return c.filter === true ? {} : c.filter
}

export function DataTable<T>({
  label,
  rows,
  columns,
  rowKey,
  actions,
  initialSort,
  pageSizes = [10, 20, 50],
  searchPlaceholder = t('Suchen …'),
  emptyText = t('Keine Einträge.'),
  countText,
  rowClassName,
  toolbar,
  fixedLayout = false,
}: DataTableProps<T>) {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(
    initialSort ? { key: initialSort.key, dir: initialSort.dir ?? 'asc' } : null,
  )
  const [filters, setFilters] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      columns.flatMap((c) => {
        const spec = filterSpec(c)
        return spec?.initial ? [[c.key, spec.initial]] : []
      }),
    ),
  )
  const [pageSize, setPageSize] = useState(pageSizes[0])
  const [page, setPage] = useState(1)

  // Auswahl je Filterspalte: feste Optionen oder die vorkommenden Werte
  const filterOptions = useMemo(
    () =>
      columns.flatMap((c) => {
        const spec = filterSpec(c)
        if (!spec) return []
        const options =
          spec.options ??
          [...new Set(rows.map((r) => asText(c.value(r))).filter(Boolean))]
            .sort(collator.compare)
            .map((v) => ({ value: v, label: v }))
        return [
          { column: c, allLabel: spec.allLabel ?? t('{label}: alle', { label: c.label }), options },
        ]
      }),
    [columns, rows],
  )

  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('de')
    const words = needle ? needle.split(/\s+/) : []
    let result = rows.filter((row) =>
      columns.every((c) => {
        const wanted = filters[c.key]
        return !wanted || asText(c.value(row)) === wanted
      }),
    )
    if (words.length) {
      result = result.filter((row) => {
        const hay = columns
          .map((c) =>
            c.searchText === false ? '' : c.searchText ? c.searchText(row) : asText(c.value(row)),
          )
          .join(' ')
          .toLocaleLowerCase('de')
        return words.every((w) => hay.includes(w))
      })
    }
    const col = sort && columns.find((c) => c.key === sort.key)
    if (col) {
      const factor = sort.dir === 'asc' ? 1 : -1
      // stabile Sortierung: bei Gleichstand bleibt die ursprüngliche Reihenfolge
      result = result
        .map((row, i) => ({ row, i }))
        .sort((a, b) => factor * compare(col.value(a.row), col.value(b.row)) || a.i - b.i)
        .map((x) => x.row)
    }
    return result
  }, [rows, columns, filters, search, sort])

  const pages = Math.max(1, Math.ceil(visible.length / pageSize))
  // Nach Löschen oder Filtern nicht auf einer leeren Seite stehen bleiben
  const current = Math.min(page, pages)
  const start = (current - 1) * pageSize
  const shown = visible.slice(start, start + pageSize)

  function toggleSort(key: string) {
    setPage(1)
    setSort((s) =>
      s?.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    )
  }

  const filtered = search.trim() !== '' || Object.values(filters).some(Boolean)

  return (
    <div className="data-table">
      <div className="filters data-table-filters">
        <input
          type="search"
          className="search-input"
          placeholder={searchPlaceholder}
          aria-label={t('{label} durchsuchen', { label })}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        {filterOptions.map(({ column, allLabel, options }) => (
          <select
            key={column.key}
            aria-label={t('Filter {label}', { label: column.label })}
            value={filters[column.key] ?? ''}
            onChange={(e) => {
              setFilters((f) => ({ ...f, [column.key]: e.target.value }))
              setPage(1)
            }}
          >
            <option value="">{allLabel}</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        ))}
        {columns.some((c) => c.sortable !== false) && (
          <label className="data-table-sort">
            <span>{t('Sortieren nach')}</span>
            <select
              value={sort ? `${sort.key}:${sort.dir}` : ''}
              onChange={(e) => {
                const [key, dir] = e.target.value.split(':')
                setPage(1)
                setSort(key ? { key, dir: dir === 'desc' ? 'desc' : 'asc' } : null)
              }}
            >
              {!sort && <option value="">{t('Sortieren nach …')}</option>}
              {columns
                .filter((c) => c.sortable !== false)
                .flatMap((c) => [
                  <option key={`${c.key}:asc`} value={`${c.key}:asc`}>
                    {c.label} {t('▲ aufsteigend')}
                  </option>,
                  <option key={`${c.key}:desc`} value={`${c.key}:desc`}>
                    {c.label} {t('▼ absteigend')}
                  </option>,
                ])}
            </select>
          </label>
        )}
        {toolbar}
      </div>

      <p className="muted small" aria-live="polite">
        {countText
          ? countText(visible.length, rows.length)
          : filtered
            ? t('{n} von {n2} Einträgen', { n: visible.length, n2: rows.length })
            : t('{n} {x}', { n: rows.length, x: rows.length === 1 ? 'Eintrag' : 'Einträge' })}
      </p>

      {shown.length === 0 ? (
        <p className="muted">{rows.length > 0 && filtered ? t('Nichts gefunden.') : emptyText}</p>
      ) : (
        <div className="table-scroll">
          <table className={fixedLayout ? 'table table-fixed' : 'table'} aria-label={label}>
            <thead>
              <tr>
                {columns.map((c) => {
                  const active = sort?.key === c.key
                  const cls = [c.numeric && 'num', c.optional && 'col-optional']
                    .filter(Boolean)
                    .join(' ')
                  return (
                    <th
                      key={c.key}
                      className={cls || undefined}
                      style={fixedLayout && c.width ? { width: c.width } : undefined}
                      aria-sort={
                        active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined
                      }
                    >
                      {c.sortable === false ? (
                        c.label
                      ) : (
                        <button
                          type="button"
                          className={`th-sort${active ? ' th-sort-active' : ''}`}
                          onClick={() => toggleSort(c.key)}
                        >
                          {c.label}
                          <span className="sort-mark" aria-hidden="true">
                            {active ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ↕'}
                          </span>
                        </button>
                      )}
                    </th>
                  )
                })}
                {actions && (
                  <th className="actions">
                    <span className="sr-only">{t('Aktionen')}</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={rowKey(row)} className={rowClassName?.(row)}>
                  {columns.map((c) => {
                    const cls = [c.numeric && 'num', c.optional && 'col-optional']
                      .filter(Boolean)
                      .join(' ')
                    return (
                      <td key={c.key} className={cls || undefined} data-label={c.label}>
                        {c.render ? c.render(row) : asText(c.value(row))}
                      </td>
                    )
                  })}
                  {actions && (
                    <td className="actions">
                      <div className="row-actions">{actions(row)}</div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {visible.length > pageSizes[0] || pageSize !== pageSizes[0] ? (
        <div className="pager data-table-pager">
          <label className="small page-size">
            {t('Zeilen pro Seite')}{' '}
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value))
                setPage(1)
              }}
            >
              {pageSizes.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button button-ghost"
            disabled={current <= 1}
            onClick={() => setPage(current - 1)}
          >
            {t('Zurück')}
          </button>
          <span className="small">
            {visible.length === 0 ? 0 : start + 1}
            {t('–{x} von  {n} · Seite {current} von', {
              x: Math.min(start + pageSize, visible.length),
              n: visible.length,
              current,
            })}{' '}
            {pages}
          </span>
          <button
            type="button"
            className="button button-ghost"
            disabled={current >= pages}
            onClick={() => setPage(current + 1)}
          >
            {t('Weiter')}
          </button>
        </div>
      ) : null}
    </div>
  )
}
