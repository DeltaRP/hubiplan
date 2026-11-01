// Abteilungsbereich: was Inhaber von Abteilungsrollen sehen und tun dürfen.
import { useEffect, useState } from 'react'
import { SortHint } from '../../components/Sortable.tsx'
import { useSortable } from '../../components/useSortable.tsx'
import type { FormEvent } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'
import { SubpageUnavailable } from '../NoticePages.tsx'
import type { MemberRow, Page } from '../../api/members.ts'
import { DEPT_PERM, portalApi } from '../../api/portal.ts'
import type { DeptMember, DeptRole, DeptSummary, Holder } from '../../api/portal.ts'
import { AccessPanel } from '../../components/AccessPanel.tsx'
import { CardPanel } from '../../components/CardPanel.tsx'
import { cardApi, cardBase } from '../../api/cards.ts'
import { ExportSection } from '../../components/DataTransfer.tsx'
import {
  errorMessage,
  formatDate,
  formatMemberDate,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import {
  Alert,
  Checkbox,
  Field,
  SaveStatus,
  SelectField,
  Tabs,
  LoadError,
  Freshness,
} from '../../components/ui.tsx'
import { Term } from '../../learning/Aids.tsx'
import { useActiveDept } from '../../org/OrgContext.tsx'
import { DeptInvoices } from '../billing/MyInvoices.tsx'
import { DeptEntries } from '../entries/UnitEntries.tsx'
import { MovedCirculars } from '../circulars/CircularsPage.tsx'
import { MemberDevelopment } from '../members/DevelopmentPage.tsx'
import { statsApi } from '../../api/statistics.ts'
import { alertDialog, confirmDialog, confirmRoleRemoval } from '../../components/dialog.ts'
import { t } from '../../i18n/index.ts'

export function DepartmentArea() {
  const dept = useActiveDept()
  const can = (p: string) => dept.permissions.includes(p)
  const tabs = [
    ...(can(DEPT_PERM.membersView) || !can(DEPT_PERM.invoicesView)
      ? [{ to: '/abteilung', label: t('Mitglieder') }]
      : []),
    ...(can(DEPT_PERM.membersView)
      ? [{ to: '/abteilung/entwicklung', label: t('Entwicklung') }]
      : []),
    ...(can(DEPT_PERM.invoicesView)
      ? [
          {
            to: can(DEPT_PERM.membersView) ? '/abteilung/rechnungen' : '/abteilung',
            label: t('Rechnungen'),
          },
        ]
      : []),
    ...(can(DEPT_PERM.rolesManage)
      ? [{ to: '/abteilung/rollen', label: t('Rollen und Rechte') }]
      : []),
    ...(can(DEPT_PERM.entriesSubmit)
      ? [{ to: '/abteilung/meldungen', label: t('Meldungen') }]
      : []),
    ...(can(DEPT_PERM.export) ? [{ to: '/abteilung/export', label: t('Export') }] : []),
  ]
  return (
    <section>
      <div className="page-head">
        <h1>{dept.name}</h1>
        <p className="muted">
          {dept.label} · {dept.club_name}
        </p>
      </div>
      {tabs.length > 1 && <Tabs items={tabs} />}
      <Routes>
        <Route
          index
          element={
            !can(DEPT_PERM.membersView) && can(DEPT_PERM.invoicesView) ? (
              <DeptInvoices deptId={dept.id} />
            ) : (
              <DeptMemberList dept={dept} />
            )
          }
        />
        {can(DEPT_PERM.membersView) && (
          <Route
            path="entwicklung"
            element={
              <MemberDevelopment
                scope={`dept-${dept.id}`}
                load={(q) => statsApi.dept(dept.id, q)}
              />
            }
          />
        )}
        {can(DEPT_PERM.invoicesView) && (
          <Route path="rechnungen" element={<DeptInvoices deptId={dept.id} />} />
        )}
        <Route path="mitglied/:id" element={<DeptMemberPage dept={dept} />} />
        {can(DEPT_PERM.rolesManage) && (
          <Route path="rollen" element={<DeptRolesPage dept={dept} />} />
        )}
        {can(DEPT_PERM.export) && (
          <Route path="export" element={<ExportSection base={{ dept: dept.id }} />} />
        )}
        {can(DEPT_PERM.entriesSubmit) && (
          <Route path="meldungen/*" element={<DeptEntries deptId={dept.id} />} />
        )}
        <Route path="rundschreiben/*" element={<MovedCirculars />} />
        <Route
          path="*"
          element={<SubpageUnavailable to="/abteilung" label={t('Zur Übersicht')} />}
        />
      </Routes>
    </section>
  )
}

// Suche und Seite überstehen den Weg in die Akte und zurück (nur diese Sitzung, NMF-07)
const DEPT_LIST_KEY = (dept: number) => `hubiplan.abteilungsliste.${dept}`

function loadDeptList(dept: number): { term: string; page: number } {
  try {
    const raw = sessionStorage.getItem(DEPT_LIST_KEY(dept))
    if (raw) return JSON.parse(raw) as { term: string; page: number }
  } catch {
    // ohne Speicher geht es auch
  }
  return { term: '', page: 1 }
}

function DeptMemberList({ dept }: { dept: DeptSummary }) {
  const [initial] = useState(() => loadDeptList(dept.id))
  const [search, setSearch] = useState(initial.term)
  const [term, setTerm] = useState(initial.term)
  const [page, setPage] = useState(initial.page)
  const [data, setData] = useState<Page<MemberRow> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const query = `${term}|${page}`

  useEffect(() => {
    const tm = setTimeout(() => {
      if (search === term) return
      setTerm(search)
      setPage(1)
    }, 300)
    return () => clearTimeout(tm)
  }, [search, term])

  useEffect(() => {
    try {
      sessionStorage.setItem(DEPT_LIST_KEY(dept.id), JSON.stringify({ term, page }))
    } catch {
      // ohne Speicher geht es auch
    }
  }, [dept.id, term, page])

  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    portalApi
      .deptMembers(dept.id, { suche: term, page })
      .then((d) => {
        if (alive) {
          setData(d)
          setError(null)
          setLoadedFor(`${term}|${page}`)
        }
      })
      .catch((err) => alive && setError(errorMessage(err)))
    return () => {
      alive = false
    }
  }, [dept.id, term, page, attempt])
  const stale = !!data && loadedFor !== query

  if (!dept.permissions.includes(DEPT_PERM.membersView)) {
    return (
      <div className="card empty-state">
        <p>{t('Deine Rolle darf die Mitgliederliste nicht sehen.')}</p>
      </div>
    )
  }

  const pages = data ? Math.max(1, Math.ceil(data.count / 50)) : 1
  return (
    <div className="card card-wide">
      {dept.permissions.includes(DEPT_PERM.cardsManage) && (
        <div className="button-row">
          <a
            className="button button-ghost push-right"
            href={cardApi.deptPdfUrl(dept.id)}
            title={t('Ausweise mit QR-Code für alle Mitglieder (10 je A4-Seite)')}
          >
            {t('Ausweise aller Mitglieder (PDF)')}
          </a>
        </div>
      )}
      <input
        type="search"
        className="search-input"
        placeholder={t('Suchen: Name oder E-Mail')}
        aria-label={t('Mitglieder suchen')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
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
      ) : data.results.length === 0 ? (
        <p className={`muted${stale ? ' is-stale' : ''}`}>{t('Keine Mitglieder gefunden.')}</p>
      ) : (
        <div className={stale ? 'is-stale' : undefined}>
          <p className="muted small">
            {data.count} {t('Mitglieder')}
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>{t('Name')}</th>
                <th>{t('Geburtsdatum')}</th>
                <th>
                  <Term k="member_type">{t('Mitgliedsart')}</Term>
                </th>
                <th>{t('E-Mail')}</th>
                <th>{t('Telefon')}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/abteilung/mitglied/${r.id}`}>
                      {r.last_name}, {r.first_name}
                    </Link>
                  </td>
                  <td>{formatDate(r.birth_date)}</td>
                  <td>{r.member_type ?? '–'}</td>
                  <td>{r.email || '–'}</td>
                  <td>{r.phone || '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <div className="button-row">
              <button
                type="button"
                className="button button-ghost"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                {t('Zurück')}
              </button>
              <span className="muted small">
                {t('Seite {page} von', { page })} {pages}
              </span>
              <button
                type="button"
                className="button button-ghost"
                disabled={page >= pages}
                onClick={() => setPage(page + 1)}
              >
                {t('Weiter')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const CONTACT_KEYS = ['email', 'phone', 'street', 'postal_code', 'city', 'country'] as const

function memberValues(m: DeptMember) {
  return {
    last_name: m.last_name,
    first_name: m.first_name,
    birth_date: m.birth_date,
    email: m.contact?.email ?? '',
    phone: m.contact?.phone ?? '',
    street: m.contact?.street ?? '',
    postal_code: m.contact?.postal_code ?? '',
    city: m.contact?.city ?? '',
    country: m.contact?.country ?? '',
  }
}

function DeptMemberPage({ dept }: { dept: DeptSummary }) {
  const id = Number(useParams().id)
  const { data, error, setData } = useLoad(() => portalApi.deptMember(dept.id, id), [dept.id, id])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const canEdit = dept.permissions.includes(DEPT_PERM.membersEdit)
  const canAccess = dept.permissions.includes(DEPT_PERM.accessManage)
  return (
    <div className="stack">
      <p>
        <Link to="/abteilung">{t('← zur Liste')}</Link>
      </p>
      <DeptMemberForm
        key={data.id}
        dept={dept}
        member={data}
        canEdit={canEdit}
        onSaved={(m) => setData(m)}
      />
      {canAccess && (
        <AccessPanel
          access={data.access ?? null}
          hasEmail={!!data.contact?.email}
          contactEmail={data.contact?.email}
          canManage
          onSend={async (transfer) => {
            const r = await portalApi.sendDeptAccess(dept.id, id, transfer)
            setData({ ...data, access: r.access })
            return r
          }}
          onRemove={async () => {
            await portalApi.removeDeptAccess(dept.id, id)
            setData({ ...data, access: null })
          }}
        />
      )}
      {dept.permissions.includes(DEPT_PERM.cardsManage) && (
        <CardPanel
          base={cardBase.dept(dept.id, id)}
          pdfUrl={cardApi.deptPdfUrl(dept.id, { mitglied: id })}
        />
      )}
    </div>
  )
}

function DeptMemberForm({
  dept,
  member,
  canEdit,
  onSaved,
}: {
  dept: DeptSummary
  member: DeptMember
  canEdit: boolean
  onSaved: (m: DeptMember) => void
}) {
  const form = useForm(memberValues(member))
  const { values: v, errors, set } = form

  // Speichert automatisch; Kontaktdaten gehören zusammen und gehen gemeinsam raus
  const auto = useAutoSave(
    form,
    (changes, values) => {
      const payload: Record<string, string> = { ...changes }
      if (CONTACT_KEYS.some((k) => k in changes)) {
        for (const k of CONTACT_KEYS) payload[k] = values[k]
      }
      if (!payload.email) delete payload.email
      return portalApi.updateDeptMember(dept.id, member.id, payload)
    },
    { enabled: canEdit, onSaved: (saved) => onSaved(saved as DeptMember) },
  )

  return (
    <form className="card card-wide" onSubmit={(e: FormEvent) => e.preventDefault()}>
      <div className="card-head">
        <h2>
          {member.first_name} {member.last_name}
        </h2>
        {canEdit && <SaveStatus auto={auto} />}
      </div>
      <p className="muted small">
        {member.member_type ?? t('ohne Mitgliedsart')}
        {member.entry_date &&
          t(' · Mitglied seit {x}', {
            x: formatMemberDate(member.entry_date, dept.date_precision),
          })}
        {member.club_number && t(' · Nr. {club_number}', { club_number: member.club_number })}
        {member.departments.length > 0 && t(' · {x}', { x: member.departments.join(', ') })}
      </p>
      <fieldset disabled={!canEdit}>
        <div className="grid-3">
          <Field
            label={t('Name')}
            required
            value={v.last_name}
            error={errors.last_name}
            onChange={(e) => set('last_name', e.target.value)}
          />
          <Field
            label={t('Vorname')}
            required
            value={v.first_name}
            error={errors.first_name}
            onChange={(e) => set('first_name', e.target.value)}
          />
          <Field
            label={t('Geburtsdatum')}
            type="date"
            required
            value={v.birth_date}
            error={errors.birth_date}
            onChange={(e) => set('birth_date', e.target.value)}
          />
        </div>
        <div className="grid-3">
          {CONTACT_KEYS.map((key) => (
            <Field
              key={key}
              label={CONTACT_LABEL[key]}
              type={key === 'email' ? 'email' : 'text'}
              value={v[key]}
              error={errors[key]}
              onChange={(e) => set(key, e.target.value)}
            />
          ))}
        </div>
      </fieldset>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      {!canEdit && (
        <p className="muted small">{t('Deine Rolle darf die Daten ansehen, aber nicht ändern.')}</p>
      )}
    </form>
  )
}

const CONTACT_LABEL: Record<(typeof CONTACT_KEYS)[number], string> = {
  email: t('E-Mail'),
  phone: t('Telefon'),
  street: t('Straße und Hausnummer'),
  postal_code: 'PLZ',
  city: t('Ort'),
  country: t('Land'),
}

function DeptRolesPage({ dept }: { dept: DeptSummary }) {
  const roles = useLoad(() => portalApi.deptRoles(dept.id), [dept.id])
  const holders = useLoad(() => portalApi.holders(dept.id), [dept.id])
  const [error, setError] = useState<string | null>(null)
  const [newRole, setNewRole] = useState('')
  const sort = useSortable({
    items: roles.data?.roles ?? [],
    id: (r) => r.id,
    label: (r) => r.name,
    onReorder: (ids) => portalApi.reorderDeptRoles(dept.id, ids).then(() => roles.reload()),
  })

  const loadError = roles.error ?? holders.error
  if (loadError) return <Alert kind="error">{loadError}</Alert>
  if (!roles.data || !holders.data) return <p className="muted">{t('Lädt …')}</p>
  const perms = roles.data.catalog.flatMap((m) => m.permissions)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      await Promise.all([roles.reload(), holders.reload()])
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function toggle(role: DeptRole, code: string, on: boolean) {
    const next = on ? [...role.permissions, code] : role.permissions.filter((c) => c !== code)
    void run(() => portalApi.updateDeptRole(dept.id, role.id, { permissions: next }))
  }

  return (
    <div className="stack">
      <div className="card card-wide">
        <h2>{t('Rollen und Rechte')}</h2>
        <p className="muted small">
          {t(
            'Hier legt ihr fest, was jede Rolle in der {label} darf. Rechte wirken für alle, die die Rolle innehaben und einen Zugang haben.',
            { label: dept.label },
          )}
        </p>
        {sort.active && <SortHint />}
        <ul className="role-list">
          {sort.ordered.map((r) => (
            <li
              key={r.id}
              ref={sort.rowProps(r).ref}
              className={['role-row', sort.rowProps(r).className].filter(Boolean).join(' ')}
            >
              {sort.handle(r)}
              <strong>
                {r.name}
                <span className="muted small"> · {r.holder_count} vergeben</span>
              </strong>
              <div className="role-perms">
                {perms.map((p) => (
                  <Checkbox
                    key={p.code}
                    label={p.label}
                    checked={r.permissions.includes(p.code)}
                    onChange={(on) => toggle(r, p.code, on)}
                  />
                ))}
              </div>
              <button
                type="button"
                className="link-button"
                onClick={async () => {
                  if (!(await confirmRoleRemoval(r.name, r.holder_count))) return
                  try {
                    await portalApi.deleteDeptRole(dept.id, r.id)
                    await roles.reload()
                  } catch (err) {
                    await alertDialog({
                      title: t('Rolle nicht entfernt'),
                      message: errorMessage(err),
                    })
                  }
                }}
              >
                {t('Entfernen')}
              </button>
            </li>
          ))}
        </ul>
        {sort.status}
        <form
          className="inline-add"
          onSubmit={(e) => {
            e.preventDefault()
            if (!newRole.trim()) return
            void run(() =>
              portalApi.createDeptRole(dept.id, { name: newRole.trim(), permissions: [] }),
            ).then(() => setNewRole(''))
          }}
        >
          <input
            aria-label={t('Neue Rolle')}
            placeholder={t('z. B. Kassierer')}
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
          />
          <button type="submit" className="button button-ghost">
            {t('Rolle hinzufügen')}
          </button>
        </form>
        {error && <Alert kind="error">{error}</Alert>}
      </div>
      <HoldersCard dept={dept} roles={roles.data.roles} holders={holders.data} onRun={run} />
    </div>
  )
}

function HoldersCard({
  dept,
  roles,
  holders,
  onRun,
}: {
  dept: DeptSummary
  roles: DeptRole[]
  holders: Holder[]
  onRun: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [member, setMember] = useState('')
  const [role, setRole] = useState('')
  const [options, setOptions] = useState<MemberRow[]>([])
  // Ladefehler nicht als „keine Mitglieder“ zeigen (Audit 29.10.)
  const [load, setLoad] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let alive = true
    // Alle Seiten laden: auch in großen Einheiten muss jedes Mitglied wählbar sein
    async function loadAll() {
      const all: MemberRow[] = []
      for (let page = 1; page <= 100; page++) {
        const p = await portalApi.deptMembers(dept.id, { page, page_size: 200 })
        all.push(...p.results)
        if (!p.next) break
      }
      return all
    }
    loadAll()
      .then((all) => {
        if (!alive) return
        setOptions(all)
        setLoad('ready')
      })
      .catch(() => alive && setLoad('failed'))
    return () => {
      alive = false
    }
  }, [dept.id, attempt])

  return (
    <div className="card card-wide">
      <h2>{t('Wer hat welche Rolle?')}</h2>
      {holders.length === 0 ? (
        <p className="muted small">{t('Noch niemand.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Mitglied')}</th>
              <th>{t('Rolle')}</th>
              <th>seit</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {holders.map((h) => (
              <tr key={h.id}>
                <td>{h.member_name}</td>
                <td>{h.role_name}</td>
                <td>{formatDate(h.valid_from)}</td>
                <td className="actions">
                  <button
                    type="button"
                    className="link-button"
                    onClick={async () => {
                      if (
                        await confirmDialog({
                          title: t('Rolle von {member_name} beenden?', {
                            member_name: h.member_name,
                          }),
                          confirmLabel: t('Beenden'),
                        })
                      ) {
                        void onRun(() => portalApi.endHolder(dept.id, h.id))
                      }
                    }}
                  >
                    {t('Beenden')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form
        className="grid-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (!member || !role) return
          void onRun(() =>
            portalApi.addHolder(dept.id, { member: Number(member), role: Number(role) }),
          ).then(() => setMember(''))
        }}
      >
        <SelectField
          label={t('Mitglied')}
          value={member}
          onChange={(e) => setMember(e.target.value)}
        >
          <option value="">
            {load === 'loading'
              ? t('Mitglieder werden geladen …')
              : load === 'failed'
                ? t('Mitglieder konnten nicht geladen werden')
                : t('bitte wählen')}
          </option>
          {options.map((m) => (
            <option key={m.id} value={m.id}>
              {m.last_name}, {m.first_name}
            </option>
          ))}
        </SelectField>
        <SelectField label={t('Rolle')} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">{t('bitte wählen')}</option>
          {roles.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </SelectField>
        <div className="field">
          <span>&nbsp;</span>
          <button type="submit" className="button button-primary" disabled={!member || !role}>
            {t('Rolle vergeben')}
          </button>
        </div>
      </form>
      {load === 'failed' && (
        <p className="alert alert-error" role="alert">
          {t('Die Mitglieder konnten nicht geladen werden.')}{' '}
          <button
            type="button"
            className="link-button"
            onClick={() => {
              setLoad('loading')
              setAttempt((n) => n + 1)
            }}
          >
            {t('Erneut laden')}
          </button>
        </p>
      )}
    </div>
  )
}
