import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { cardApi } from '../../api/cards.ts'
import { GENDERS, memberApi } from '../../api/members.ts'
import type { ListParams, MemberRow, Page } from '../../api/members.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import { errorMessage, formatDate, formatMemberDate, useLoad } from '../../components/forms.ts'
import type { DatePrecision } from '../../components/forms.ts'
import { Freshness, LoadError } from '../../components/ui.tsx'
import { ExportPanel } from '../../components/ExportPanel.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { t } from '../../i18n/index.ts'

interface Column {
  key: string
  label: string
  value: (r: MemberRow, precision: DatePrecision) => string
  sort?: string
}

const COLUMNS: Column[] = [
  {
    key: 'member_type',
    label: t('Mitgliedsart'),
    value: (r) => r.member_type ?? '–',
    sort: 'art',
  },
  {
    key: 'birth_date',
    label: t('Geburtsdatum'),
    value: (r) => (r.birth_year_only ? r.birth_date.slice(0, 4) : formatDate(r.birth_date)),
    sort: 'geburtsdatum',
  },
  { key: 'gender', label: t('Geschlecht'), value: (r) => r.gender || '–' },
  {
    key: 'entry_date',
    label: t('Eintritt'),
    value: (r, p) => formatMemberDate(r.entry_date, p),
    sort: 'eintritt',
  },
  { key: 'exit_date', label: t('Austritt'), value: (r, p) => formatMemberDate(r.exit_date, p) },
  {
    key: 'club_number',
    label: t('Mitgliedsnr.'),
    value: (r) => r.club_number || '–',
    sort: 'nummer',
  },
  {
    key: 'member_number',
    label: t('Verbandsnr.'),
    value: (r) => (r.member_number ? String(r.member_number) : '–'),
  },
  {
    key: 'departments',
    label: t('Abteilung'),
    value: (r) => r.departments.join(', ') || '–',
    sort: 'abteilung',
  },
  {
    key: 'honorary_titles',
    label: t('Ehrungen'),
    value: (r) => (r.honorary_titles ?? []).join(', ') || '–',
    sort: 'ehrentitel',
  },
  { key: 'email', label: t('E-Mail'), value: (r) => r.email || '–' },
  { key: 'phone', label: t('Telefon'), value: (r) => r.phone || '–' },
  {
    key: 'address',
    label: t('Anschrift'),
    value: (r) =>
      [r.street, t('{postal_code} {city}', { postal_code: r.postal_code, city: r.city }).trim()]
        .filter(Boolean)
        .join(', ') || '–',
  },
]

const DEFAULT_COLUMNS = ['member_type', 'birth_date', 'entry_date', 'departments']
const COLUMN_KEY = 'hubiplan.mitgliederliste.spalten'

function loadColumns(): string[] {
  try {
    const raw = localStorage.getItem(COLUMN_KEY)
    return raw ? (JSON.parse(raw) as string[]) : DEFAULT_COLUMNS
  } catch {
    return DEFAULT_COLUMNS
  }
}

function saveColumns(cols: string[]) {
  try {
    localStorage.setItem(COLUMN_KEY, JSON.stringify(cols))
  } catch {
    // ohne Speicher geht es auch
  }
}

// Suche, Filter, Sortierung und Seite überstehen den Weg in die Akte und zurück
// (nur für diese Sitzung im Browser, nicht in der teilbaren Adresse).
const LIST_KEY = (org: number) => `hubiplan.mitgliederliste.${org}`

function loadListState(org: number): ListParams | null {
  try {
    const raw = sessionStorage.getItem(LIST_KEY(org))
    return raw ? (JSON.parse(raw) as ListParams) : null
  } catch {
    return null
  }
}

export function MemberListPage() {
  const org = useActiveOrg()
  const navigate = useNavigate()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const [params, setParams] = useState<ListParams>(
    () => loadListState(org.id) ?? { status: 'aktiv', sortierung: 'name', page: 1 },
  )
  const [search, setSearch] = useState(() => params.suche ?? '')
  useEffect(() => {
    try {
      sessionStorage.setItem(LIST_KEY(org.id), JSON.stringify(params))
    } catch {
      // ohne Speicher geht es auch
    }
  }, [org.id, params])
  const [columns, setColumns] = useState<string[]>(loadColumns)
  const [showColumns, setShowColumns] = useState(false)
  const [showExport, setShowExport] = useState(false)
  const canExport = org.permissions.includes(PERM.exportRun)
  const [data, setData] = useState<Page<MemberRow> | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Für welche Auswahl die angezeigten Treffer gelten (NMF-05)
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const query = JSON.stringify(params)
  const types = useLoad(() => memberApi.types(org.id), [org.id])
  const departments = useLoad(() => orgApi.departments(org.id), [org.id])
  const titles = useLoad(() => memberApi.honoraryTitles(org.id, true), [org.id])
  const pageSize = 50

  // Suche erst nach kurzer Tipp-Pause auslösen
  useEffect(() => {
    const tm = setTimeout(
      () => setParams((p) => ((p.suche ?? '') === search ? p : { ...p, suche: search, page: 1 })),
      300,
    )
    return () => clearTimeout(tm)
  }, [search])

  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    memberApi
      .list(org.id, { ...params, page_size: pageSize })
      .then((d) => {
        if (alive) {
          setData(d)
          setError(null)
          setLoadedFor(JSON.stringify(params))
        }
      })
      .catch((err) => alive && setError(errorMessage(err)))
    return () => {
      alive = false
    }
  }, [org.id, params, attempt])
  const stale = !!data && loadedFor !== query

  function toggleColumn(key: string, on: boolean) {
    const next = on ? [...columns, key] : columns.filter((c) => c !== key)
    setColumns(next)
    saveColumns(next)
  }

  function sortBy(key: string) {
    setParams((p) => ({ ...p, sortierung: p.sortierung === key ? `-${key}` : key, page: 1 }))
  }

  const visible = COLUMNS.filter((c) => columns.includes(c.key))
  const pages = data ? Math.max(1, Math.ceil(data.count / pageSize)) : 1
  // Pfeil nur fürs Auge; Screenreader bekommen die Richtung über aria-sort (WCAG 1.3.1)
  const sortMark = (key: string) =>
    params.sortierung === key || params.sortierung === `-${key}` ? (
      <span aria-hidden="true">{params.sortierung === key ? ' ▲' : ' ▼'}</span>
    ) : null
  const ariaSort = (key: string) =>
    params.sortierung === key
      ? ('ascending' as const)
      : params.sortierung === `-${key}`
        ? ('descending' as const)
        : undefined

  return (
    <section>
      <div className="page-head">
        <h1>{t('Mitglieder')}</h1>
        <span className="push-right" />
        {canExport && (
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowExport((s) => !s)}
          >
            {t('Export')}
          </button>
        )}
        {org.permissions.includes(PERM.cardsManage) && (
          <a
            className="button button-ghost"
            href={cardApi.orgPdfUrl(org.id, {
              suche: params.suche,
              art: params.art,
              geschlecht: params.geschlecht,
              abteilung: params.abteilung,
              ehrentitel: params.ehrentitel,
              sortierung: params.sortierung,
            })}
            title={t(
              'Ausweise mit QR-Code für alle aktuellen Mitglieder der Auswahl (10 je A4-Seite)',
            )}
          >
            {t('Ausweise (PDF)')}
          </a>
        )}
        {canEdit && (
          <Link to="/mitglieder/neu" className="button button-primary">
            {t('Mitglied aufnehmen')}
          </Link>
        )}
      </div>

      <div className="card card-wide filters">
        <input
          type="search"
          className="search-input"
          placeholder={t('Suchen: Name, E-Mail, Mitglieds- oder Verbandsnummer')}
          aria-label={t('Mitglieder suchen')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label={t('Status')}
          value={params.status}
          onChange={(e) => setParams((p) => ({ ...p, status: e.target.value, page: 1 }))}
        >
          <option value="aktiv">{t('aktuelle Mitglieder')}</option>
          <option value="ehemalig">{t('ehemalige Mitglieder')}</option>
          <option value="alle">alle</option>
        </select>
        <select
          aria-label={t('Mitgliedsart')}
          value={params.art ?? ''}
          onChange={(e) => setParams((p) => ({ ...p, art: e.target.value, page: 1 }))}
        >
          <option value="">{t('alle Mitgliedsarten')}</option>
          {types.data?.map((tm) => (
            <option key={tm.id} value={tm.id}>
              {tm.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t('Geschlecht')}
          value={params.geschlecht ?? ''}
          onChange={(e) => setParams((p) => ({ ...p, geschlecht: e.target.value, page: 1 }))}
        >
          <option value="">{t('alle Geschlechter')}</option>
          {GENDERS.filter((g) => g.value).map((g) => (
            <option key={g.value} value={g.value}>
              {g.label}
            </option>
          ))}
          <option value="ohne">{t('ohne Angabe')}</option>
        </select>
        {departments.data && departments.data.length > 0 && (
          <select
            aria-label={org.department_label}
            value={params.abteilung ?? ''}
            onChange={(e) => setParams((p) => ({ ...p, abteilung: e.target.value, page: 1 }))}
          >
            <option value="">alle {org.department_label_plural}</option>
            {departments.data.map((d) => (
              <option key={d.id} value={d.id}>
                {unitName(d)}
              </option>
            ))}
          </select>
        )}
        {titles.data && titles.data.length > 0 && (
          <select
            aria-label={t('Ehrungen')}
            value={params.ehrentitel ?? ''}
            onChange={(e) => setParams((p) => ({ ...p, ehrentitel: e.target.value, page: 1 }))}
          >
            <option value="">{t('alle (mit und ohne Ehrung)')}</option>
            <option value="mit">{t('mit Ehrung')}</option>
            {titles.data.map((tm) => (
              <option key={tm.id} value={tm.id}>
                {tm.own
                  ? tm.name
                  : t('{name} ({owner_name})', { name: tm.name, owner_name: tm.owner_name })}
                {tm.is_archived ? ' (archiviert)' : ''}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="button button-ghost"
          onClick={() => setShowColumns((s) => !s)}
        >
          {t('Spalten')}
        </button>
        {showColumns && (
          <div className="column-picker">
            {COLUMNS.map((c) => (
              <label key={c.key} className="checkbox">
                <input
                  type="checkbox"
                  checked={columns.includes(c.key)}
                  onChange={(e) => toggleColumn(c.key, e.target.checked)}
                />
                <span>{c.key === 'departments' ? org.department_label : c.label}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {showExport && (
        <ExportPanel
          orgId={org.id}
          kind="members"
          filters={{ ...params, page: undefined }}
          onClose={() => setShowExport(false)}
        />
      )}
      {error && !data && <LoadError message={error} onRetry={() => setAttempt((n) => n + 1)} />}
      {data && (
        <Freshness
          refreshing={stale && !error}
          error={error}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      )}
      {!data ? (
        !error && <p className="muted">{t('Lädt …')}</p>
      ) : (
        <div className={`card card-wide${stale ? ' is-stale' : ''}`}>
          <p className="muted small">
            {data.count} {data.count === 1 ? t('Mitglied') : t('Mitglieder')}
          </p>
          {data.count === 0 ? (
            <p className="muted">{t('Keine Mitglieder gefunden.')}</p>
          ) : (
            <table className="table member-table">
              <thead>
                <tr>
                  <th aria-sort={ariaSort('name')}>
                    <button type="button" className="th-sort" onClick={() => sortBy('name')}>
                      {t('Name')}
                      {sortMark('name')}
                    </button>
                  </th>
                  {visible.map((c) => (
                    <th
                      key={c.key}
                      className={c.key === 'member_type' ? '' : 'col-optional'}
                      aria-sort={c.sort ? ariaSort(c.sort) : undefined}
                    >
                      {c.sort ? (
                        <button type="button" className="th-sort" onClick={() => sortBy(c.sort!)}>
                          {c.key === 'departments' ? org.department_label : c.label}
                          {sortMark(c.sort)}
                        </button>
                      ) : c.key === 'departments' ? (
                        org.department_label
                      ) : (
                        c.label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <tr
                    key={r.id}
                    className={`clickable${r.status === 'former' ? ' inactive' : ''}`}
                    onClick={() => navigate(`/mitglieder/${r.id}`)}
                  >
                    <td className="name-cell">
                      {r.photo_url ? (
                        <img src={r.photo_url} alt="" className="member-avatar" loading="lazy" />
                      ) : (
                        <span className="member-avatar member-avatar-empty" aria-hidden="true">
                          {r.first_name.charAt(0)}
                          {r.last_name.charAt(0)}
                        </span>
                      )}
                      <Link to={`/mitglieder/${r.id}`} onClick={(e) => e.stopPropagation()}>
                        {r.last_name}, {r.first_name}
                      </Link>
                    </td>
                    {visible.map((c) => (
                      <td key={c.key} className={c.key === 'member_type' ? '' : 'col-optional'}>
                        {c.value(r, org.date_precision)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {pages > 1 && (
            <div className="pager">
              <button
                type="button"
                className="button button-ghost"
                disabled={(params.page ?? 1) <= 1}
                onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) - 1 }))}
              >
                {t('Zurück')}
              </button>
              <span className="small">
                {t('Seite {page} von', { page: params.page })} {pages}
              </span>
              <button
                type="button"
                className="button button-ghost"
                disabled={(params.page ?? 1) >= pages}
                onClick={() => setParams((p) => ({ ...p, page: (p.page ?? 1) + 1 }))}
              >
                {t('Weiter')}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
