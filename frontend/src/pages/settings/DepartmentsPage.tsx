import { StatutePanel } from '../../components/StatutePanel.tsx'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { orgApi, PERM } from '../../api/orgs.ts'
import type { CatalogModule, Department, DepartmentRole } from '../../api/orgs.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import {
  DATE_PRECISION_OPTIONS,
  DATE_PRECISION_WORD,
  errorMessage,
  formatDate,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import type { DatePrecision } from '../../components/forms.ts'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { fillTerms, termsFor, useTerms } from '../../org/terms.ts'
import type { DeptTerms } from '../../org/terms.ts'
import { LabelFields } from '../../components/LabelFields.tsx'
import type { Gender } from '../../components/LabelFields.tsx'
import { LogoUpload } from './AppearancePage.tsx'
import { HomepageImage } from '../../components/HomepageImage.tsx'
import { FiscalYearFields, fiscalDescription } from '../../components/FiscalYearFields.tsx'
import { alertDialog, confirmDialog, confirmRoleRemoval } from '../../components/dialog.ts'
import { DataTable } from '../../components/DataTable.tsx'
import type { Column } from '../../components/DataTable.tsx'
import { DeleteIcon, EditIcon, IconButton, ViewIcon } from '../../components/icons.tsx'
import { HowTo, Why } from '../../learning/Aids.tsx'
import { RoleForm, RoleTable } from '../../components/RoleEditor.tsx'
import { UNIT_ROLE_FIELDS } from '../../components/roles.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { SortableList, SortHint } from '../../components/Sortable.tsx'
import { memberApi, todayIso } from '../../api/members.ts'
import type { MemberRow } from '../../api/members.ts'
import { t, tn } from '../../i18n/index.ts'

export function DepartmentsPage() {
  const org = useActiveOrg()
  const editable = org.permissions.includes(PERM.orgEdit)
  const { data, error, reload } = useLoad(() => orgApi.departments(org.id), [org.id])
  const catalog = useLoad(() => orgApi.catalog('department', org.id), [org.id])
  const tmx = useTerms()
  const label = tmx.sg
  const labelPlural = tmx.pl
  const [selected, setSelected] = useState<number | null>(null)
  const [sorting, setSorting] = useState(false)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selected !== null) panel.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [selected])

  if (org.type !== 'club')
    return (
      <Alert kind="info">
        {t('Nur Einheiten mit Mitgliedern haben {labelPlural}.', { labelPlural })}
      </Alert>
    )
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>

  const current = data.find((d) => d.id === selected) ?? null

  async function remove(dep: Department) {
    const own = ownTerms(dep, tmx)
    const ok = await confirmDialog({
      title: t('„{name}“ löschen?', { name: dep.name }),
      message: fillTerms(
        t('Nur möglich, solange {diesem} keine Mitglieder und Rolleninhaber zugeordnet sind ') +
          t('oder waren und {nom} keine eigenen Untereinheiten hat. Sonst {akk} besser auf ') +
          t('inaktiv setzen.'),
        own,
      ),
      confirmLabel: t('Löschen'),
    })
    if (!ok) return
    try {
      await orgApi.deleteDepartment(org.id, dep.id)
      if (selected === dep.id) setSelected(null)
      reload()
    } catch (err) {
      await alertDialog({
        title: t('{Sg} nicht gelöscht', { Sg: own.Sg }),
        message: errorMessage(err),
      })
    }
  }

  const columns: Column<Department>[] = [
    {
      key: 'name',
      label: t('Name'),
      value: (d) => d.path ?? d.name,
      searchText: (d) => t('{x} {x2}', { x: d.path ?? d.name, x2: d.short_name ?? '' }),
      render: (d) => (
        <span
          className="cell-with-logo"
          style={d.depth ? { paddingLeft: `${d.depth * 1.5}rem` } : undefined}
          data-depth={d.depth ?? 0}
        >
          {(d.depth ?? 0) > 0 && (
            <span className="muted" aria-hidden="true">
              ↳
            </span>
          )}
          {d.logo_url && <img src={d.logo_url} alt="" className="cell-logo" />}
          {d.name}
          {(d.depth ?? 0) > 0 && d.label && <span className="muted small">{d.label}</span>}
        </span>
      ),
    },
    { key: 'short_name', label: t('Kurzname'), value: (d) => d.short_name ?? '', optional: true },
    {
      key: 'founding_year',
      label: t('Gründungsjahr'),
      value: (d) => d.founding_year,
      numeric: true,
      optional: true,
    },
    { key: 'members', label: t('Mitglieder'), value: (d) => d.member_count ?? 0, numeric: true },
    {
      key: 'roles',
      label: t('Rollen'),
      value: (d) => d.roles.length,
      searchText: (d) => d.roles.map((r) => r.name).join(' '),
      render: (d) =>
        d.roles.length === 0 ? (
          <span className="muted">–</span>
        ) : (
          <span title={d.roles.map((r) => r.name).join(', ')}>{d.roles.length}</span>
        ),
      numeric: true,
      optional: true,
    },
    {
      key: 'status',
      label: t('Status'),
      value: (d) => (d.is_remote ? t('andere Instanz') : d.is_active ? 'aktiv' : 'inaktiv'),
      filter: {
        allLabel: t('aktive und inaktive'),
        options: [
          { value: 'aktiv', label: t('nur aktive') },
          { value: 'inaktiv', label: t('nur inaktive') },
        ],
      },
    },
  ]

  return (
    <div className="stack">
      <div className="card card-wide">
        <div className="card-head">
          <HowTo k="how_units" />
          {editable && data.length > 1 && (
            <button
              type="button"
              className="button button-ghost push-right"
              aria-pressed={sorting}
              onClick={() => setSorting((x) => !x)}
            >
              {sorting ? t('Schließen') : t('Reihenfolge ändern')}
            </button>
          )}
        </div>
        {sorting ? (
          <>
            <SortHint website={org.modules.includes('website')} />
            <UnitOrder orgId={org.id} units={data} parent={null} onChange={reload} />
          </>
        ) : (
          <DataTable
            label={labelPlural}
            rows={data}
            columns={columns}
            rowKey={(d) => d.id}
            searchPlaceholder={`${labelPlural} durchsuchen: Name, Kurzname, Rolle`}
            emptyText={t('Noch keine {labelPlural} angelegt.', { labelPlural })}
            countText={(n, total) =>
              n === total
                ? t('{total} {x}', { total, x: total === 1 ? label : labelPlural })
                : t('{n} von {total}', { n, total })
            }
            rowClassName={(d) =>
              [!d.is_active && 'inactive', d.id === selected && 'selected']
                .filter(Boolean)
                .join(' ') || undefined
            }
            actions={(d) => (
              <>
                <IconButton
                  label={t('{name} {x}', {
                    name: d.name,
                    x: editable && !d.is_remote ? 'bearbeiten' : 'anzeigen',
                  })}
                  icon={editable && !d.is_remote ? <EditIcon /> : <ViewIcon />}
                  aria-pressed={d.id === selected}
                  onClick={() => setSelected((s) => (s === d.id ? null : d.id))}
                />
                {editable && !d.is_remote && (
                  <IconButton
                    label={t('{name} löschen', { name: d.name })}
                    icon={<DeleteIcon />}
                    danger
                    onClick={() => void remove(d)}
                  />
                )}
              </>
            )}
          />
        )}
      </div>
      {current && (
        <div ref={panel}>
          <DepartmentCard
            key={current.id}
            orgId={org.id}
            dep={current}
            units={data}
            terms={tmx}
            inThis={ownTerms(current, tmx).diesem}
            editable={editable && !current.is_remote}
            catalog={catalog.data ?? []}
            onChange={reload}
            onClose={() => setSelected(null)}
          />
        </div>
      )}
      {editable && (
        <NewDepartment
          key={current?.id ?? 0}
          orgId={org.id}
          units={data}
          terms={tmx}
          initialParent={current?.id ?? null}
          onCreated={reload}
        />
      )}
    </div>
  )
}

/** Formen für die Bezeichnung einer Untereinheit selbst (z. B. „Gruppe“). */
function ownTerms(dep: Department, fallback: DeptTerms): DeptTerms {
  if (!dep.label || dep.depth === 0) return fallback
  return termsFor(
    dep.label,
    dep.label_plural ?? dep.label,
    dep.label_gender ?? 'f',
    '',
    dep.label_en,
    dep.label_plural_en,
  )
}

/** Formen für Untereinheiten unter ``parent`` (oder direkt unter der Einheit). */
function childTermsOf(parent: Department | undefined, fallback: DeptTerms): DeptTerms {
  return parent?.child_terms && Object.keys(parent.child_terms).length
    ? parent.child_terms
    : fallback
}

function NewDepartment({
  orgId,
  units,
  terms,
  initialParent,
  onCreated,
}: {
  orgId: number
  units: Department[]
  terms: DeptTerms
  initialParent: number | null
  onCreated: () => void
}) {
  const form = useForm({
    name: '',
    short_name: '',
    founding_year: '',
    parent_unit: initialParent ? String(initialParent) : '',
  })
  const parent = units.find((u) => String(u.id) === form.values.parent_unit)
  const label = childTermsOf(parent, terms).sg
  async function create(e: FormEvent) {
    e.preventDefault()
    const ok = await form.submit(
      () =>
        orgApi.createDepartment(orgId, {
          name: form.values.name,
          short_name: form.values.short_name,
          founding_year: form.values.founding_year ? Number(form.values.founding_year) : null,
          parent_unit: form.values.parent_unit ? Number(form.values.parent_unit) : null,
        }),
      t('{label} angelegt.', { label }),
    )
    if (ok) {
      form.setValues({
        name: '',
        short_name: '',
        founding_year: '',
        parent_unit: form.values.parent_unit,
      })
      onCreated()
    }
  }
  return (
    <form className="card" onSubmit={create}>
      <h2>{label} anlegen</h2>
      <SelectField
        label={t('Gehört zu')}
        value={form.values.parent_unit}
        error={form.errors.parent_unit}
        hint={t('Untereinheiten können selbst wieder Untereinheiten haben.')}
        onChange={(e) => form.set('parent_unit', e.target.value)}
      >
        <option value="">direkt {terms.e_zum}</option>
        {units
          .filter((u) => u.is_active)
          .map((u) => (
            <option key={u.id} value={String(u.id)}>
              {u.path ?? u.name}
            </option>
          ))}
      </SelectField>
      <div className="grid-3">
        <Field
          label={t('Vollständiger Name')}
          required
          value={form.values.name}
          error={form.errors.name}
          onChange={(e) => form.set('name', e.target.value)}
        />
        <Field
          label={t('Kurzname (optional)')}
          maxLength={50}
          value={form.values.short_name}
          error={form.errors.short_name}
          hint={t('Für Navigation, Listen und Auswahlfelder')}
          onChange={(e) => form.set('short_name', e.target.value)}
        />
        <Field
          label={t('Gründungsjahr (optional)')}
          type="number"
          min={800}
          max={2100}
          value={form.values.founding_year}
          error={form.errors.founding_year}
          onChange={(e) => form.set('founding_year', e.target.value)}
        />
      </div>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      <button type="submit" className="button button-primary" disabled={form.busy}>
        {t('Anlegen')}
      </button>
    </form>
  )
}

/** Alle Untereinheiten unterhalb von ``id`` (ohne ``id`` selbst). */
function below(id: number, units: Department[]): Department[] {
  const ids = subtreeIds(units, id)
  return units.filter((u) => u.id !== id && ids.has(u.id))
}

/** Die Untereinheit und alle darunter (dorthin darf sie nicht umgehängt werden). */
function subtreeIds(units: Department[], id: number): Set<number> {
  const ids = new Set([id])
  let grew = true
  while (grew) {
    grew = false
    for (const u of units)
      if (u.parent_unit != null && ids.has(u.parent_unit) && !ids.has(u.id)) {
        ids.add(u.id)
        grew = true
      }
  }
  return ids
}

function DepartmentCard({
  orgId,
  dep,
  units,
  terms,
  inThis,
  editable,
  catalog,
  onChange,
  onClose,
}: {
  orgId: number
  dep: Department
  units: Department[]
  terms: DeptTerms
  /** „diesem Zug“ / „dieser Abteilung“ */
  inThis: string
  editable: boolean
  catalog: CatalogModule[]
  onChange: () => void
  onClose: () => void
}) {
  const tm = useTerms()
  const editing = editable
  const [roleEdit, setRoleEdit] = useState<DepartmentRole | 'new' | null>(null)
  const hasWebsite = useActiveOrg().modules.includes('website')
  const hasBilling = useActiveOrg().modules.includes('billing')
  async function toggleActive(on: boolean) {
    const count = below(dep.id, units).filter((u) => u.is_active).length
    if (!on && count) {
      const ok = await confirmDialog({
        title: t('„{name}“ stilllegen?', { name: dep.name }),
        message: tn(
          'Damit wird auch 1 Untereinheit darunter stillgelegt. Wird sie wieder aktiv, kommt diese mit zurück.',
          'Damit werden auch {n} Untereinheiten darunter stillgelegt. Wird sie wieder aktiv, kommen diese mit zurück.',
          count,
        ),
        confirmLabel: t('Stilllegen'),
      })
      if (!ok) return
    }
    form.set('is_active', on)
  }
  const form = useForm({
    name: dep.name,
    short_name: dep.short_name ?? '',
    founding_year: dep.founding_year == null ? '' : String(dep.founding_year),
    website: dep.website ?? '',
    website_on_site: !!dep.website_on_site,
    is_active: dep.is_active,
    date_precision: dep.date_precision,
    fiscal_start_month: dep.fiscal_start_month,
    fiscal_start_day: dep.fiscal_start_day,
    department_label: dep.department_label ?? t('Gruppe'),
    department_label_plural: dep.department_label_plural ?? t('Gruppen'),
    department_label_gender: (dep.department_label_gender ?? 'f') as Gender,
    department_label_genitive: dep.department_label_genitive ?? '',
    department_label_en: dep.department_label_en ?? '',
    department_label_plural_en: dep.department_label_plural_en ?? '',
    own_workspace: !!dep.own_workspace,
    self_managed: !!dep.self_managed,
    own_website: !!dep.own_website,
    fee_exempt: !!dep.fee_exempt,
    parent_unit: dep.parent_unit ? String(dep.parent_unit) : '',
  })
  const blocked = subtreeIds(units, dep.id)
  const hasChildren = units.some((u) => u.parent_unit === dep.id)

  const auto = useAutoSave(
    form,
    (changes) => {
      const payload: Record<string, unknown> = { ...changes }
      if ('founding_year' in changes)
        payload.founding_year = changes.founding_year ? Number(changes.founding_year) : null
      if ('parent_unit' in changes)
        payload.parent_unit = changes.parent_unit ? Number(changes.parent_unit) : null
      return orgApi.updateDepartment(orgId, dep.id, payload as Partial<Department>)
    },
    { enabled: editable && editing, onSaved: () => onChange() },
  )

  async function finish() {
    if (!(await auto.flush())) return
    onClose()
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        {dep.logo_url && <img src={dep.logo_url} alt="" className="logo-img" />}
        <div>
          <h2>{dep.name}</h2>
          <p className="muted small">
            {dep.short_name && t('Kurzname: {short_name} · ', { short_name: dep.short_name })}
            {dep.founding_year != null &&
              t('gegründet {founding_year} · ', { founding_year: dep.founding_year })}
            {t('Geschäftsjahr')} {fiscalDescription(dep.fiscal_start_month, dep.fiscal_start_day)}
            {dep.date_precision &&
              t(' · Mitgliedschaften {x}', { x: DATE_PRECISION_WORD[dep.date_precision] })}
            {!dep.is_active && t(' · inaktiv')}
          </p>
        </div>
        {/* Felder speichern automatisch; Schließen wartet nur auf die letzte Änderung */}
        <button
          type="button"
          className="button button-ghost push-right"
          onClick={() => (editable ? void finish() : onClose())}
        >
          {t('Schließen')}
        </button>
      </div>
      {dep.is_remote && (
        <Alert kind="info">
          {t(
            'Diese Einheit führt ihre Daten auf einer eigenen HUBIplan-Instanz. Sie ist über den Verbund gekoppelt und pflegt sich dort; hier ist sie nur zu sehen. Die Kopplung steht unter Einstellungen › Verbund.',
          )}
        </Alert>
      )}

      {editing && (
        <form onSubmit={(e) => e.preventDefault()} className="inline-form">
          <SaveStatus auto={auto} />
          <div className="grid-3">
            <Field
              label={t('Vollständiger Name')}
              required
              value={form.values.name}
              error={form.errors.name}
              onChange={(e) => form.set('name', e.target.value)}
            />
            <Field
              label={t('Kurzname (optional)')}
              maxLength={50}
              value={form.values.short_name}
              error={form.errors.short_name}
              onChange={(e) => form.set('short_name', e.target.value)}
            />
            <Field
              label={t('Gründungsjahr (optional)')}
              type="number"
              min={800}
              max={2100}
              value={form.values.founding_year}
              error={form.errors.founding_year}
              onChange={(e) => form.set('founding_year', e.target.value)}
            />
          </div>
          <Field
            label={t('Homepage (optional)')}
            inputMode="url"
            placeholder="https://"
            value={form.values.website}
            error={form.errors.website}
            onChange={(e) => form.set('website', e.target.value)}
          />
          {hasWebsite && (
            <Checkbox
              label={t('Homepage auf der Webseite verlinken')}
              hint={t(
                'Der Link steht auf der Seite von {name} und öffnet sich in einem neuen Tab.',
                { name: dep.name },
              )}
              checked={form.values.website_on_site}
              disabled={!form.values.website.trim()}
              onChange={(on) => form.set('website_on_site', on)}
            />
          )}
          {hasWebsite && dep.website && form.values.website_on_site && (
            <HomepageImage
              orgId={orgId}
              depId={dep.id}
              imageUrl={dep.website_image_url ?? null}
              custom={!!dep.website_image_custom}
              onChange={onChange}
            />
          )}
          <Checkbox
            label={t('{name} ist aktiv', { name: dep.name })}
            hint={
              below(dep.id, units).length
                ? t(
                    'statt Löschen auf inaktiv setzen; legt auch alle Untereinheiten darunter still',
                  )
                : t('statt Löschen auf inaktiv setzen, wenn es Mitglieder gab')
            }
            checked={form.values.is_active}
            onChange={(on) => void toggleActive(on)}
          />
          <SelectField
            label={t('Gehört zu')}
            value={form.values.parent_unit}
            error={form.errors.parent_unit}
            hint={t('Umhängen: Untereinheiten und Mitglieder wandern mit.')}
            onChange={(e) => form.set('parent_unit', e.target.value)}
          >
            <option value="">direkt {terms.e_zum}</option>
            {units
              .filter((u) => u.is_active && !blocked.has(u.id))
              .map((u) => (
                <option key={u.id} value={String(u.id)}>
                  {u.path ?? u.name}
                </option>
              ))}
          </SelectField>
          <FiscalYearFields
            month={form.values.fiscal_start_month}
            day={form.values.fiscal_start_day}
            error={form.errors.fiscal_start_month ?? form.errors.fiscal_start_day}
            onChange={(m, d) => {
              form.set('fiscal_start_month', m)
              form.set('fiscal_start_day', d)
            }}
          />
          <SelectField
            label={t('Genauigkeit für Mitgliedschaften')}
            value={form.values.date_precision}
            error={form.errors.date_precision}
            hint={t('Wie Ein- und Austritt in {inThis} angezeigt werden.', { inThis })}
            onChange={(e) => form.set('date_precision', e.target.value as DatePrecision | '')}
          >
            <option value="">wie {tm.e_nom}</option>
            {DATE_PRECISION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </SelectField>
          {hasBilling && (
            <>
              <h3>{t('Beitrag')}</h3>
              <Checkbox
                label={t('Mitglieder von {name} sind beitragsfrei', { name: dep.name })}
                hint={t(
                  'Gilt auch für die Einheiten darunter. Der Beitragslauf berechnet für sie 0 € und nennt sie in der Prüfliste. Der Beitrag an den Dachverband bleibt.',
                )}
                checked={form.values.fee_exempt}
                onChange={(on) => form.set('fee_exempt', on)}
              />
            </>
          )}
          <h3>{t('Verwaltung')}</h3>
          <Checkbox
            label={t('{name} verwaltet sich selbst', { name: dep.name })}
            hint={
              form.values.own_workspace
                ? t('Mit eigenem Arbeitsbereich immer an.')
                : t('Rolleninhaber bekommen Zugänge mit Rechten.')
            }
            checked={form.values.self_managed || form.values.own_workspace}
            disabled={form.values.own_workspace}
            onChange={(on) => form.set('self_managed', on)}
          />
          <Why k="unit_self_managed" />
          <p className="muted small">
            {form.values.self_managed || form.values.own_workspace
              ? t(
                  'Die Mitglieder bleiben {e_beim}. Wer in {inThis} eine Rolle mit Rechten hat, arbeitet mit eigenem Zugang.',
                  { e_beim: tm.e_beim, inThis },
                )
              : t(
                  'Die Einheit darüber verwaltet alles. Rollen sind reine Ämter: keine Rechte, keine Zugänge, keine E-Mails.',
                )}
          </p>
          {form.errors.self_managed && <Alert kind="error">{form.errors.self_managed}</Alert>}
          {(form.values.self_managed || form.values.own_workspace) && (
            <>
              <h3>{t('Eigener Arbeitsbereich')}</h3>
              <Checkbox
                label={t('{name} führt eine eigene Kasse und hat eigene Rollen mit Zugängen', {
                  name: dep.name,
                })}
                checked={form.values.own_workspace}
                onChange={(on) => {
                  form.set('own_workspace', on)
                  if (on) form.set('self_managed', true)
                }}
              />
              <p className="muted small">
                {t(
                  'Die Mitglieder bleiben {e_beim}. Der Arbeitsbereich erscheint oben in der Auswahl. Wer hier Rollen verwaltet, richtet dort die Zugänge ein; wer hier die Kasse sieht, sieht dort die Kasse mit (nur lesen).',
                  { e_beim: tm.e_beim },
                )}
              </p>
            </>
          )}
          {hasWebsite && (form.values.own_workspace || form.values.own_website) && (
            <>
              <Checkbox
                label={t('{name} hat eine eigene Webseite', { name: dep.name })}
                checked={form.values.own_website}
                onChange={(on) => form.set('own_website', on)}
              />
              <p className="muted small">
                {t(
                  'Optional. Gepflegt wird sie im Arbeitsbereich unter „Webseite“, mit eigenen Texten, eigener Domain und eigenen Ansprechpartnern. Die Mitglieder und ihre Einwilligungen kommen {e_vom}.',
                  { e_vom: tm.e_vom },
                )}
              </p>
              {form.errors.own_website && <Alert kind="error">{form.errors.own_website}</Alert>}
            </>
          )}
          {/* Ohne Untereinheiten braucht es keine Bezeichnung dafür */}
          {hasChildren && (
            <>
              <h3>{t('Bezeichnung der Untereinheiten')}</h3>
              <p className="muted small">
                {t('So heißen Einheiten, die zu {inThis} gehören (z. B. „Gruppe“ oder „Rotte“).', {
                  inThis,
                })}
              </p>
              <LabelFields
                preview="children"
                testId="unit-child-terms-preview"
                value={{
                  label: form.values.department_label,
                  plural: form.values.department_label_plural,
                  gender: form.values.department_label_gender,
                  genitive: form.values.department_label_genitive,
                  labelEn: form.values.department_label_en,
                  pluralEn: form.values.department_label_plural_en,
                }}
                errors={{
                  label: form.errors.department_label,
                  plural: form.errors.department_label_plural,
                  gender: form.errors.department_label_gender,
                  genitive: form.errors.department_label_genitive,
                }}
                onChange={(v) => {
                  form.set('department_label', v.label)
                  form.set('department_label_plural', v.plural)
                  form.set('department_label_gender', v.gender)
                  form.set('department_label_genitive', v.genitive)
                  form.set('department_label_en', v.labelEn ?? '')
                  form.set('department_label_plural_en', v.pluralEn ?? '')
                }}
              />
            </>
          )}
          <h4>{t('Wappen / Logo')}</h4>
          <LogoUpload
            uploadUrl={orgApi.departmentLogoUrl(orgId, dep.id)}
            logoUrl={dep.logo_url}
            onChange={onChange}
          />
          {hasWebsite && (
            <p className="muted small" data-testid="unit-gallery-hint">
              {t('Fotos fürs Bilderkarussell gehören nicht hierher:')}{' '}
              <Link to={`/webseite/inhalte?einheit=${dep.id}`}>
                {t('Webseite › Texte › Text für')} {dep.name}
              </Link>
            </p>
          )}
        </form>
      )}

      {editable && dep.self_managed && (
        <ManagerSetup orgId={orgId} dep={dep} inThis={inThis} onChange={onChange} />
      )}

      <div className="card-head">
        <h3>
          {t('Rollen in')} {inThis}
        </h3>
        {editable && roleEdit === null && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setRoleEdit('new')}
          >
            {t('Neue Rolle')}
          </button>
        )}
      </div>
      {roleEdit !== null && (
        <RoleForm
          key={roleEdit === 'new' ? 'new' : roleEdit.id}
          role={
            roleEdit === 'new'
              ? null
              : { ...roleEdit, holders: roleEdit.holders.map((h) => h.name) }
          }
          catalog={catalog}
          fields={UNIT_ROLE_FIELDS}
          hasWebsite={hasWebsite}
          readOnly={!editable}
          permissionsOptional
          showPermissions={!!dep.self_managed}
          onSave={(data) =>
            roleEdit === 'new'
              ? orgApi.createDepartmentRole(orgId, dep.id, data)
              : orgApi.updateDepartmentRole(orgId, roleEdit.id, data)
          }
          onDelete={
            roleEdit === 'new' ? undefined : () => orgApi.deleteDepartmentRole(orgId, roleEdit.id)
          }
          confirmDelete={
            roleEdit === 'new'
              ? undefined
              : () =>
                  confirmRoleRemoval(
                    roleEdit.name,
                    roleEdit.holders.map((h) => h.name),
                  )
          }
          onDone={() => {
            setRoleEdit(null)
            onChange()
          }}
          onCancel={() => setRoleEdit(null)}
        />
      )}
      <RoleTable
        roles={dep.roles.map((r) => ({ ...r, holders: r.holders.map((h) => h.name) }))}
        catalog={catalog}
        holderLabel={t('Inhaber')}
        noPermissions="keine (nur Amt)"
        showPermissions={!!dep.self_managed}
        editLabel={editable ? t('Bearbeiten') : t('Ansehen')}
        onEdit={(r) => setRoleEdit(dep.roles.find((x) => x.id === r.id) ?? null)}
        onReorder={
          editable
            ? (ids) => orgApi.reorderDepartmentRoles(orgId, dep.id, ids).then(() => onChange())
            : undefined
        }
        website={hasWebsite}
      />
      <UnitHolders orgId={orgId} dep={dep} onChange={onChange} />
      {dep.self_managed ? (
        <p className="muted small">
          {t(
            'Eine Rolle ohne Rechte ist ein reines Amt: Die Inhaber brauchen kein Konto und bekommen keine E-Mail. Rechte wirken nur, wenn unter Organisation → Zugänge für Mitglieder eingeschaltet sind und der Inhaber einen Zugang hat (z. B. über „Verwalter einrichten“).',
          )}
        </p>
      ) : (
        <p className="muted small">
          {dep.name}{' '}
          {t(
            'wird von oben verwaltet: Die Rollen sind reine Ämter, ohne Konto und ohne E-Mail. Eigene Zugänge gibt es erst mit „verwaltet sich selbst“ (oben unter Bearbeiten).',
          )}
        </p>
      )}
      <details className="statute-details">
        <summary>{t('Satzung')}</summary>
        <StatutePanel orgId={orgId} departmentId={dep.id} heading="h3" />
      </details>
      <details className="statute-details">
        <summary>{t('Beitragsordnung')}</summary>
        <StatutePanel orgId={orgId} departmentId={dep.id} heading="h3" kind="fee_rules" />
      </details>
      <details className="statute-details">
        <summary>{t('Gründungsurkunde')}</summary>
        <StatutePanel orgId={orgId} departmentId={dep.id} heading="h3" kind="founding_deed" />
      </details>
    </div>
  )
}

/** Rollen der Untereinheit an Mitglieder vergeben: ohne Konto, ohne E-Mail. */
function UnitHolders({
  orgId,
  dep,
  onChange,
}: {
  orgId: number
  dep: Department
  onChange: () => void
}) {
  const { can } = useOrg()
  const [today] = useState(todayIso)
  const [member, setMember] = useState<MemberRow | null>(null)
  const [role, setRole] = useState('')
  const [from, setFrom] = useState(today)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  if (dep.roles.length === 0 || !can(PERM.membersView)) return null
  const canEdit = can(PERM.membersEdit)
  const rows = dep.roles.flatMap((r) => r.holders.map((h) => ({ ...h, role: r })))
  const roleId = role || String(dep.roles[0].id)

  async function run(action: () => Promise<unknown>, text: string): Promise<boolean> {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage({ kind: 'success', text })
      onChange()
      return true
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    const picked = dep.roles.find((r) => String(r.id) === roleId)
    if (!member || !picked) return
    const name = t('{first_name} {last_name}', {
      first_name: member.first_name,
      last_name: member.last_name,
    })
    const ok = await run(
      () => memberApi.addDepartmentRole(orgId, member.id, { role: picked.id, valid_from: from }),
      t(
        '{name} hat jetzt die Rolle „{name2}“. Es wurde kein Konto angelegt und keine E-Mail verschickt.',
        { name, name2: picked.name },
      ),
    )
    if (ok) setMember(null)
  }

  async function end(h: (typeof rows)[number]) {
    const ok = await confirmDialog({
      title: t('Rolle „{name}“ von {name2} beenden?', { name: h.role.name, name2: h.name }),
      message: t('Die Amtszeit endet heute und bleibt in der Mitgliederakte erhalten.'),
      confirmLabel: t('Beenden'),
    })
    if (!ok) return
    await run(
      () => memberApi.endDepartmentRole(orgId, h.membership, h.id, today),
      t('Die Rolle „{name}“ von {name2} ist beendet.', { name: h.role.name, name2: h.name }),
    )
  }

  return (
    <div className="subcard" data-testid="unit-holders">
      <h3>{t('Wer hat welche Rolle?')}</h3>
      {rows.length === 0 ? (
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
            {rows.map((h) => (
              <tr key={h.id}>
                <td>{h.name}</td>
                <td>{h.role.name}</td>
                <td>{formatDate(h.valid_from)}</td>
                <td className="actions">
                  {canEdit && (
                    <button
                      type="button"
                      className="link-button"
                      disabled={busy}
                      onClick={() => void end(h)}
                    >
                      {t('Beenden')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <form onSubmit={add} className="stack">
          <p className="muted small">
            {t(
              'Mitglied aus der Mitgliederliste wählen. Es wird kein Konto angelegt und keine E-Mail verschickt.',
            )}
          </p>
          <MemberPicker orgId={orgId} value={member} onChange={setMember} label={t('Mitglied')} />
          <div className="grid-2">
            <SelectField
              label={t('Rolle')}
              value={roleId}
              onChange={(e) => setRole(e.target.value)}
            >
              {dep.roles.map((r) => (
                <option key={r.id} value={String(r.id)}>
                  {r.name}
                </option>
              ))}
            </SelectField>
            <Field
              label="seit"
              type="date"
              required
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </div>
          <div className="button-row">
            <button type="submit" className="button button-primary" disabled={!member || busy}>
              {t('Rolle zuordnen')}
            </button>
          </div>
        </form>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </div>
  )
}

/** Ersten Verwalter einer Einheit in einem Schritt einrichten. */
function ManagerSetup({
  orgId,
  dep,
  inThis,
  onChange,
}: {
  orgId: number
  dep: Department
  inThis: string
  onChange: () => void
}) {
  const { can } = useOrg()
  const [member, setMember] = useState<MemberRow | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  if (!can(PERM.membersView)) return null

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!member) return
    setBusy(true)
    setMessage(null)
    try {
      const r = await orgApi.setupUnitManager(orgId, dep.id, member.id)
      const mail =
        r.mail === 'invitation'
          ? t('Eine Einladung zum Festlegen des Passworts ging an {email}.', { email: r.email })
          : r.mail === 'none'
            ? t(
                'Die E-Mail an {email} konnte nicht gesendet werden; bitte später über „Zugang“ in der Mitgliederakte erneut senden.',
                { email: r.email },
              )
            : t('Ein Hinweis zur Anmeldung ging an {email}.', { email: r.email })
      const extra = r.workspace_role
        ? t(' und im Arbeitsbereich die Rolle „{workspace_role}“', {
            workspace_role: r.workspace_role,
          })
        : ''
      setMessage({
        kind: 'success',
        text: t(
          '{first_name} {last_name} hat jetzt die Rolle „{role}“ mit allen Rechten{extra}. {mail}',
          { first_name: member.first_name, last_name: member.last_name, role: r.role, extra, mail },
        ),
      })
      setMember(null)
      onChange()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="stack" data-testid="unit-manager">
      <h3>{t('Verwalter einrichten')}</h3>
      <p className="muted small">
        {t('Gibt einem Mitglied die Rolle „Leitung“ mit allen Rechten in')} {inThis}
        {dep.own_workspace ? ' (auch für Kasse und Rechnungen)' : ''}{' '}
        {t(
          'und richtet ihm einen Zugang ein. Die Person braucht eine E-Mail-Adresse und kann danach selbst weitere Rollen vergeben. Nur nötig, wenn jemand selbst in HUBIplan arbeiten soll; Ämter ohne Zugang vergibst du unter „Wer hat welche Rolle?“.',
        )}
      </p>
      <MemberPicker orgId={orgId} value={member} onChange={setMember} label={t('Mitglied')} />
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={!member || busy}>
          {t('Verwalter einrichten')}
        </button>
      </div>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </form>
  )
}

/** Reihenfolge der Untereinheiten: je Ebene eine Liste zum Ziehen. */
function UnitOrder({
  orgId,
  units,
  parent,
  onChange,
}: {
  orgId: number
  units: Department[]
  parent: number | null
  onChange: () => unknown
}) {
  const children = units.filter((u) => (u.parent_unit ?? null) === parent)
  if (children.length === 0) return null
  return (
    <SortableList
      ariaLabel={parent === null ? t('Reihenfolge') : t('Reihenfolge darunter')}
      items={children}
      id={(u) => u.id}
      label={(u) => u.name}
      onReorder={(ids) => orgApi.reorderDepartments(orgId, parent, ids).then(() => onChange())}
      render={(u) => (
        <>
          <span className={u.is_active ? undefined : 'muted'}>
            {u.name}
            {!u.is_active && ' (inaktiv)'}
          </span>
          <UnitOrder orgId={orgId} units={units} parent={u.id} onChange={onChange} />
        </>
      )}
    />
  )
}
