import { useState } from 'react'
import { Link } from 'react-router-dom'
import { fieldApi } from '../../api/fields.ts'
import type { BirthdayRow, JubileeRow, UnitJubileeRow } from '../../api/fields.ts'
import { todayIso } from '../../api/members.ts'
import { formatMemberDate, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { ExportPanel } from '../../components/ExportPanel.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { HowTo } from '../../learning/Aids.tsx'
import { buildTerms } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

function plusDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00`) // Mittag: Sommerzeitwechsel verschiebt den Tag nicht
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

/** Jubiläen einer Person zusammengefasst; die Reihenfolge folgt dem ersten Jubiläum. */
interface PersonJubilees {
  member_id: number
  first_name: string
  last_name: string
  units?: string
  items: JubileeRow[]
}

/** Name mit Untereinheit in Klammern, z. B. „Erika Muster (Jägerzug)“ */
function nameWithUnits(p: { first_name: string; last_name: string; units?: string }): string {
  const name = t('{first_name} {last_name}', { first_name: p.first_name, last_name: p.last_name })
  return p.units ? t('{name} ({units})', { name, units: p.units }) : name
}

/**
 * Überschrift aus den eigenen Bezeichnungen, z. B. „Jubiläen der Züge“ oder
 * „Jubiläen des Vereins und der Züge“; nie das technische Wort „Einheit“.
 */
export function unitJubileeHeading(rows: UnitJubileeRow[]): { title: string; column: string } {
  const groups = new Map<string, { row: UnitJubileeRow; ids: Set<number> }>()
  for (const r of rows) {
    const key = `${r.kind === 'self' ? 'self' : 'sub'}:${r.label}`
    const g = groups.get(key) ?? { row: r, ids: new Set<number>() }
    g.ids.add(r.id)
    groups.set(key, g)
  }
  const parts = [...groups.values()].map(({ row, ids }) => {
    const tm = buildTerms(
      row.label,
      row.label_plural || row.label,
      row.label_gender,
      row.label_genitive,
    )
    return ids.size === 1 ? tm.gen : t('der {pl}', { pl: tm.pl })
  })
  const list =
    parts.length > 1
      ? t('{x} und {x2}', { x: parts.slice(0, -1).join(', '), x2: parts[parts.length - 1] })
      : parts[0]
  const labels = new Set(rows.map((r) => r.label))
  return {
    title: t('{x} {x2}', { x: rows.length === 1 ? 'Jubiläum' : 'Jubiläen', x2: list ?? '' }).trim(),
    column: labels.size === 1 ? [...labels][0] : t('Name'),
  }
}

function groupByPerson(rows: JubileeRow[]): PersonJubilees[] {
  const groups = new Map<number, PersonJubilees>()
  for (const r of rows) {
    let g = groups.get(r.member_id)
    if (!g) {
      g = {
        member_id: r.member_id,
        first_name: r.first_name,
        last_name: r.last_name,
        units: r.units,
        items: [],
      }
      groups.set(r.member_id, g)
    }
    g.items.push(r)
  }
  return [...groups.values()]
}

export function JubileesPage() {
  const org = useActiveOrg()
  const [von, setVon] = useState(todayIso)
  const [bis, setBis] = useState(() => plusDays(todayIso(), 365))
  const { data, error } = useLoad(() => fieldApi.jubilees(org.id, von, bis), [org.id, von, bis])
  const units = useLoad(() => fieldApi.unitJubilees(org.id, von, bis), [org.id, von, bis])
  const [showExport, setShowExport] = useState(false)
  const unitHeading = unitJubileeHeading(units.data?.results ?? [])

  return (
    <>
      <div className="card card-wide filters">
        <label className="inline-label">
          von <input type="date" value={von} onChange={(e) => setVon(e.target.value)} />
        </label>
        <label className="inline-label">
          bis <input type="date" value={bis} onChange={(e) => setBis(e.target.value)} />
        </label>
        {org.permissions.includes('export.run') && (
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowExport((s) => !s)}
          >
            {t('Export')}
          </button>
        )}
      </div>
      {showExport && (
        <ExportPanel
          orgId={org.id}
          kind="jubilees"
          filters={{ von, bis }}
          onClose={() => setShowExport(false)}
        />
      )}
      {units.data && units.data.results.length > 0 && (
        <div className="card card-wide">
          <h2>{unitHeading.title}</h2>
          <table className="table" aria-label={unitHeading.title}>
            <thead>
              <tr>
                <th>{t('Jahr')}</th>
                <th>{unitHeading.column}</th>
                <th>{t('Jubiläum')}</th>
                <th className="col-optional">{t('gegründet')}</th>
              </tr>
            </thead>
            <tbody>
              {units.data.results.map((r) => (
                <tr key={`${r.id}-${r.years}`}>
                  <td>{r.year}</td>
                  <td>
                    {r.path} <span className="muted small">{r.label}</span>
                  </td>
                  <td>
                    {r.years} {t('Jahre')}
                  </td>
                  <td className="col-optional">{r.founding_year}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {!data ? (
        <p className="muted">{t('Lädt …')}</p>
      ) : (
        <div className="card card-wide">
          <HowTo k="calc_jubilee" />
          <p className="muted small">
            {data.results.length}{' '}
            {t(
              'Jubiläen · Stufen und die Regel für die Dauer stellt jede Organisation unter Mitglieder → Einrichtung → Jubiläen & Dauer ein.',
            )}
          </p>
          {data.results.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>{t('Datum')}</th>
                  <th>{t('Name')}</th>
                  <th>{t('Jubiläum')}</th>
                </tr>
              </thead>
              <tbody>
                {groupByPerson(data.results).map((p) =>
                  p.items.map((r, i) => (
                    <tr
                      key={`${r.member_id}-${r.kind}-${r.years}`}
                      className={i < p.items.length - 1 ? 'row-continued' : undefined}
                    >
                      <td>{formatMemberDate(r.date, r.precision)}</td>
                      {i === 0 && (
                        <td rowSpan={p.items.length}>
                          <Link to={`/mitglieder/${p.member_id}`}>
                            {p.last_name}, {p.first_name}
                          </Link>
                        </td>
                      )}
                      <td>
                        {r.years} {t('Jahre')} {r.organization_short ?? r.organization}
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  )
}

/** Kachel für die Startseite: Jubiläen der nächsten 90 Tage. */
export function JubileeTile() {
  const org = useActiveOrg()
  const today = todayIso()
  const { data } = useLoad(
    () => fieldApi.jubilees(org.id, today, plusDays(today, 90)),
    [org.id, today],
  )
  const units = useLoad(
    () => fieldApi.unitJubilees(org.id, today, plusDays(today, 90)),
    [org.id, today],
  )
  const unitRows: UnitJubileeRow[] = units.data?.results ?? []
  return (
    <div className="card tile">
      <h2>{t('Anstehende Jubiläen')}</h2>
      {unitRows.length > 0 && (
        <ul className="plain-list" aria-label={unitJubileeHeading(unitRows).title}>
          {unitRows.slice(0, 3).map((r) => (
            <li key={`${r.id}-${r.years}`} className="tile-entry">
              <span className="tile-entry-title">
                {r.years} {t('Jahre')} {r.short_name || r.name}
              </span>
              <span className="tile-entry-meta muted small">
                <span>{r.label}</span>
                <span aria-hidden="true">·</span>
                <span>{r.year}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {!data ? (
        <p className="muted">{t('Lädt …')}</p>
      ) : data.results.length === 0 ? (
        <p className="muted">{t('In den nächsten 90 Tagen keine.')}</p>
      ) : (
        <ul className="plain-list">
          {groupByPerson(data.results)
            .slice(0, 6)
            .map((p) => (
              <li key={p.member_id} className="tile-entry">
                <Link to={`/mitglieder/${p.member_id}`} className="tile-entry-title">
                  {nameWithUnits(p)}
                </Link>
                {p.items.map((r) => (
                  <span key={`${r.kind}-${r.years}`} className="tile-entry-meta muted small">
                    <span>{r.years} J.</span>
                    <span aria-hidden="true">·</span>
                    <span className="tile-entry-org" title={r.organization}>
                      {r.organization_short ?? r.organization}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>{formatMemberDate(r.date, r.precision)}</span>
                  </span>
                ))}
              </li>
            ))}
        </ul>
      )}
      <Link to="/mitglieder/jubilaeen" className="small">
        {t('Alle Jubiläen')}
      </Link>
    </div>
  )
}

const BIRTHDAY_DAYS = 30
const BIRTHDAY_PREVIEW = 8
// Eigene Kürzel: Intl schreibt je nach Laufzeit „Do“ oder „Do.“
const WEEKDAYS = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']

function birthdayLabel(iso: string, today: string): string {
  if (iso === today) return 'heute'
  if (iso === plusDays(today, 1)) return 'morgen'
  const d = new Date(`${iso}T12:00:00`)
  return t('{x}, {x2}.{x3}.', { x: WEEKDAYS[d.getDay()], x2: d.getDate(), x3: d.getMonth() + 1 })
}

/** Kachel auf der Startseite: Geburtstage der nächsten 30 Tage */
export function BirthdayTile() {
  const org = useActiveOrg()
  const today = todayIso()
  const { data, error } = useLoad(
    () => fieldApi.birthdays(org.id, today, plusDays(today, BIRTHDAY_DAYS)),
    [org.id, today],
  )
  const rows: BirthdayRow[] = data?.results ?? []
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? rows : rows.slice(0, BIRTHDAY_PREVIEW)
  return (
    <div className="card tile">
      <h2>{t('Anstehende Geburtstage')}</h2>
      {error ? (
        <p className="muted">{t('Geburtstage lassen sich gerade nicht laden.')}</p>
      ) : !data ? (
        <p className="muted">{t('Lädt …')}</p>
      ) : rows.length === 0 ? (
        <p className="muted">
          {t('In den nächsten {BIRTHDAY_DAYS} Tagen keine.', { BIRTHDAY_DAYS })}
        </p>
      ) : (
        <ul className="plain-list" aria-label={t('Geburtstage')}>
          {shown.map((r) => (
            <li
              key={`${r.member_id}-${r.date}`}
              className={r.date === today ? 'tile-entry tile-entry-today' : 'tile-entry'}
            >
              <Link to={`/mitglieder/${r.member_id}`} className="tile-entry-title">
                {nameWithUnits(r)}
              </Link>
              <span className="tile-entry-meta muted small">
                <span>{birthdayLabel(r.date, today)}</span>
                <span aria-hidden="true">·</span>
                <span>
                  {r.age} {t('Jahre')}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > BIRTHDAY_PREVIEW && (
        <p className="muted small">
          {showAll ? (
            <button type="button" className="link-button" onClick={() => setShowAll(false)}>
              {t('Weniger zeigen')}
            </button>
          ) : (
            <>
              und {rows.length - BIRTHDAY_PREVIEW}{' '}
              {t('weitere in den nächsten {BIRTHDAY_DAYS} Tagen ·', { BIRTHDAY_DAYS })}{' '}
              <button type="button" className="link-button" onClick={() => setShowAll(true)}>
                {t('alle zeigen')}
              </button>
            </>
          )}
        </p>
      )}
    </div>
  )
}
