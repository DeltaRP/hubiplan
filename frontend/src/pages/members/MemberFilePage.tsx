import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { GENDERS, memberApi, todayIso } from '../../api/members.ts'
import type { DurationInfo, Gender, MemberDetail } from '../../api/members.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'
import {
  DATE_PRECISION_WORD,
  errorMessage,
  formatDate,
  formatDateTime,
  formatMemberDate,
  jubileeWhen,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { confirmDiscard, useChangesGuard } from '../../components/leaveGuard.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField, LoadError } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { orgTerms, useTerms } from '../../org/terms.ts'
import { MembershipActions } from './MembershipActions.tsx'
import { SuggestCorrection } from './FederationMembersPage.tsx'
import { FieldsTab } from './FieldsTab.tsx'
import { PhotoSection } from './PhotoSection.tsx'
import { PublicationSection } from './PublicationSection.tsx'
import { HonoraryAwards } from './HonoraryAwards.tsx'
import { MemberAccessSection } from '../../components/AccessPanel.tsx'
import { AuditUndo } from '../../components/AuditUndo.tsx'
import { firstOfSet } from '../../components/undo.ts'
import { CardPanel } from '../../components/CardPanel.tsx'
import { cardApi, cardBase } from '../../api/cards.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { Term } from '../../learning/Aids.tsx'

type Tab = 'stammdaten' | 'mitgliedschaft' | 'zusatzfelder' | 'rollen' | 'verlauf'

const TABS: { id: Tab; label: string }[] = [
  { id: 'stammdaten', label: 'Stammdaten' },
  { id: 'mitgliedschaft', label: 'Mitgliedschaft' },
  { id: 'zusatzfelder', label: 'Zusatzfelder' },
  { id: 'rollen', label: 'Rollen & Ehrungen' },
  { id: 'verlauf', label: 'Verlauf' },
]

export function MemberFilePage() {
  const org = useActiveOrg()
  const id = Number(useParams().id)
  const { data, error, setData, reload } = useLoad(() => memberApi.detail(org.id, id), [org.id, id])
  // Bereich steht in der Adresse: Zurück, Neuladen und Links öffnen ihn wieder (NMF-07)
  const [params] = useSearchParams()
  const tab: Tab = TABS.find((t) => t.id === params.get('bereich'))?.id ?? 'stammdaten'
  const canEdit = org.permissions.includes(PERM.membersEdit)

  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>

  return (
    <section>
      <p>
        <Link to="/mitglieder">← Mitglieder</Link>
      </p>
      <div className="page-head">
        {data.photo.approved && (
          <img src={data.photo.approved.thumbnail_url} alt="" className="member-avatar-lg" />
        )}
        <div>
          <h1>
            {data.first_name} {data.last_name}
          </h1>
          <p className="muted">
            {data.status === 'active' ? 'Mitglied' : 'ehemaliges Mitglied'}
            {data.current_type && ` · ${data.current_type.member_type_name}`}
            {currentTitles(data).length > 0 && ` · ${currentTitles(data).join(', ')}`}
          </p>
        </div>
      </div>
      <nav className="tabs" aria-label="Bereiche der Mitgliedsakte">
        {TABS.map((t) => (
          <Link
            key={t.id}
            to={t.id === 'stammdaten' ? '.' : `?bereich=${t.id}`}
            className={`tab${tab === t.id ? ' active' : ''}`}
            aria-current={tab === t.id ? 'page' : undefined}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {tab === 'stammdaten' && (
        <div className="stack">
          <PhotoSection
            key={`foto-${data.id}`}
            orgId={org.id}
            memberId={data.id}
            initial={{
              photo: data.photo,
              photo_consent_at: data.photo_consent_at,
              photo_consent_source: data.photo_consent_source,
            }}
            canManage={org.permissions.includes(PERM.photosManage)}
            hasEmail={!!data.contact?.email}
            onChange={() => void reload()}
          />
          <MasterData
            key={data.id}
            org={org}
            member={data}
            canEdit={canEdit && !data.managed_by}
            onSaved={setData}
          />
          {data.managed_by && (
            <SuggestCorrection
              orgId={org.id}
              member={data}
              owner={data.managed_by.name}
              intro={`Stammdaten und Kontakt pflegt ${data.managed_by.name} auf einer eigenen HUBIplan-Instanz (Verbund). Mitgliedschaft, Mitgliedsart und Beitrag bleiben hier. Hier lässt sich eine Korrektur vorschlagen.`}
            />
          )}
          {org.modules.includes('website') && (
            <PublicationSection
              key={`veroeffentlichung-${data.id}`}
              orgId={org.id}
              memberId={data.id}
              canEdit={canEdit}
            />
          )}
          {data.status === 'active' && (
            <MemberAccessSection
              key={`zugang-${data.id}`}
              orgId={org.id}
              memberId={data.id}
              hasEmail={!!data.contact?.email}
              contactEmail={data.contact?.email}
              canManage={canEdit}
            />
          )}
          {org.permissions.includes(PERM.cardsManage) && (
            <CardPanel
              key={`ausweis-${data.id}`}
              base={cardBase.org(org.id, data.id)}
              pdfUrl={cardApi.orgPdfUrl(org.id, { mitglied: data.id })}
            />
          )}
        </div>
      )}
      {tab === 'mitgliedschaft' && (
        <MembershipTab
          org={org}
          member={data}
          canEdit={canEdit}
          reload={reload}
          setData={setData}
        />
      )}
      {tab === 'zusatzfelder' && <FieldsTab orgId={org.id} memberId={data.id} canEdit={canEdit} />}
      {tab === 'rollen' && <RolesTab org={org} member={data} canEdit={canEdit} reload={reload} />}
      {tab === 'verlauf' && <HistoryTab orgId={org.id} memberId={data.id} />}
    </section>
  )
}

function MasterData({
  org,
  member,
  canEdit,
  onSaved,
}: {
  org: OrgSummary
  member: MemberDetail
  canEdit: boolean
  onSaved: (m: MemberDetail) => void
}) {
  const tm = useTerms()
  const c = member.contact
  const form = useForm({
    last_name: member.last_name,
    first_name: member.first_name,
    birth_date: member.birth_date,
    gender: member.gender ?? '',
    club_number: member.club_number,
    email: c?.email ?? '',
    phone: c?.phone ?? '',
    street: c?.street ?? '',
    postal_code: c?.postal_code ?? '',
    city: c?.city ?? '',
    country: c?.country ?? 'Deutschland',
  })
  const v = form.values
  const e = form.errors
  const auto = useAutoSave(
    form,
    // Nur Geändertes senden: Der Server ergänzt neue Kontaktdaten selbst, und so
    // überschreibt ein veralteter Stand keine gleichzeitige Änderung anderer Felder.
    (changes) => memberApi.update(org.id, member.id, changes),
    { enabled: canEdit, onSaved: (saved) => onSaved(saved as MemberDetail) },
  )

  return (
    <form className="card card-wide" onSubmit={(ev) => ev.preventDefault()}>
      {canEdit && <SaveStatus auto={auto} />}
      <fieldset disabled={!canEdit}>
        <div className="grid-4">
          <Field
            label="Name"
            required
            value={v.last_name}
            error={e.last_name}
            onChange={(ev) => form.set('last_name', ev.target.value)}
          />
          <Field
            label="Vorname"
            required
            value={v.first_name}
            error={e.first_name}
            onChange={(ev) => form.set('first_name', ev.target.value)}
          />
          {member.birth_year_only && v.birth_date === member.birth_date ? (
            <Field
              label="Geburtsjahr"
              value={member.birth_date.slice(0, 4)}
              hint="Nach der Löschfrist ist nur noch das Jahr gespeichert."
              readOnly
            />
          ) : (
            <Field
              label="Geburtsdatum"
              type="date"
              required
              value={v.birth_date}
              error={e.birth_date}
              onChange={(ev) => form.set('birth_date', ev.target.value)}
            />
          )}
          <SelectField
            label="Geschlecht"
            value={v.gender}
            error={e.gender}
            onChange={(ev) => form.set('gender', ev.target.value as Gender)}
          >
            {GENDERS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </SelectField>
        </div>
        <div className="grid-2">
          <Field
            label="E-Mail-Adresse (optional)"
            type="email"
            value={v.email}
            error={e.email}
            onChange={(ev) => form.set('email', ev.target.value)}
          />
          <Field
            label="Telefon"
            value={v.phone}
            error={e.phone}
            onChange={(ev) => form.set('phone', ev.target.value)}
          />
        </div>
        <Field
          label="Straße und Hausnummer"
          required
          value={v.street}
          error={e.street}
          onChange={(ev) => form.set('street', ev.target.value)}
        />
        <div className="grid-3">
          <Field
            label="PLZ"
            required
            value={v.postal_code}
            error={e.postal_code}
            onChange={(ev) => form.set('postal_code', ev.target.value)}
          />
          <Field
            label="Ort"
            required
            value={v.city}
            error={e.city}
            onChange={(ev) => form.set('city', ev.target.value)}
          />
          <Field
            label="Land"
            value={v.country}
            error={e.country}
            onChange={(ev) => form.set('country', ev.target.value)}
          />
        </div>
        <div className="grid-2">
          <Field
            label={`Mitgliedsnummer ${tm.e_im}`}
            value={v.club_number}
            error={e.club_number}
            onChange={(ev) => form.set('club_number', ev.target.value)}
          />
        </div>
      </fieldset>
      <p className="muted small">
        {member.contact_shared
          ? `Kontaktdaten werden für alle ${tm.e_pl} gemeinsam gepflegt.`
          : `Kontaktdaten gelten nur für ${org.name}.`}
      </p>
    </form>
  )
}

/** Aktuelle Ehrungen (eigene und des Dachverbands) für die Kopfzeile */
function currentTitles(m: MemberDetail): string[] {
  const today = todayIso()
  const all = [...(m.honorary_titles?.own ?? []), ...(m.honorary_titles?.federation ?? [])]
  return [
    ...new Set(
      all
        .filter((a) => a.valid_from <= today && (!a.valid_until || a.valid_until >= today))
        .map((a) => a.title_name),
    ),
  ]
}

function MembershipTab({
  org,
  member,
  canEdit,
  reload,
  setData,
}: {
  org: OrgSummary
  member: MemberDetail
  canEdit: boolean
  reload: () => Promise<void>
  setData: (m: MemberDetail) => void
}) {
  const tm = useTerms()
  const [error, setError] = useState<string | null>(null)
  const departments = useLoad(() => orgApi.departments(org.id), [org.id])
  const precision = org.date_precision
  const terms = orgTerms(org)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="stack">
      {canEdit && <MembershipActions org={org} member={member} onChanged={setData} />}

      <Section title="Mitgliedsdauer">
        <DurationLine label={tm.e_im} info={member.duration.club} />
        {member.duration.federation && (
          <DurationLine
            label={`${terms.dv_im} (${member.duration.federation.rule})`}
            info={member.duration.federation}
          />
        )}
      </Section>

      <Section title="Zeiträume">
        <table className="table">
          <thead>
            <tr>
              <th>Eintritt</th>
              <th>Austritt</th>
              <th>Grund</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {member.periods.map((p) => (
              <tr key={p.id}>
                <td>{formatMemberDate(p.entry_date, precision)}</td>
                <td>{p.exit_date ? formatMemberDate(p.exit_date, precision) : 'heute'}</td>
                <td>{p.exit_reason_label || '–'}</td>
                <td className="actions">
                  {canEdit && member.periods.length > 1 && (
                    <button
                      type="button"
                      className="link-button"
                      onClick={async () => {
                        if (
                          await confirmDialog({
                            title: 'Diesen Zeitraum löschen?',
                            confirmLabel: 'Löschen',
                          })
                        ) {
                          void run(() => memberApi.deletePeriod(org.id, member.id, p.id))
                        }
                      }}
                    >
                      Löschen
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {canEdit && <AddPeriod org={org} member={member} onAdded={reload} />}
      </Section>

      <Section title="Mitgliedsarten">
        <ul className="plain-list">
          {member.type_history.map((t) => (
            <li key={t.id}>
              <strong>{t.member_type_name}</strong> · {formatMemberDate(t.valid_from, precision)} –{' '}
              {t.valid_until ? formatMemberDate(t.valid_until, precision) : 'heute'}
              <span className="muted small">
                {' '}
                ({t.active ? 'aktiv' : 'nicht aktiv'}, {t.reported ? 'gemeldet' : 'nicht gemeldet'})
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {member.federation && (
        <Section title={member.federation.name}>
          <p>
            {/* Die Verbandsnummer steht hier bewusst nicht (Ralf 2026-10-30). */}
            {member.federation.is_member ? 'Mitglied' : 'derzeit kein Mitglied'}
          </p>
          {member.federation.remote ? (
            <p className="muted small">
              Der Dachverband führt sein Register auf einer eigenen Instanz (Verbund).
            </p>
          ) : (
            <p>
              Eintritt:{' '}
              {formatMemberDate(
                member.federation.entry_date,
                member.duration.federation?.precision ?? precision,
              )}
              {member.federation.entry_date_manual ? ' (von Hand eingetragen)' : ' (berechnet)'}
            </p>
          )}
          {canEdit && !member.federation.remote && member.federation.member_number && (
            <FederationEntry org={org} member={member} onSaved={setData} />
          )}
        </Section>
      )}

      {member.other_memberships && member.other_memberships.length > 0 && (
        <Section title={`Mitgliedschaften in anderen ${tm.e_pl_dat}`}>
          <ul className="plain-list">
            {member.other_memberships.map((m, i) => (
              <li key={i}>
                <strong>{m.club}</strong> · {formatMemberDate(m.entry_date, precision)} –{' '}
                {m.exit_date ? formatMemberDate(m.exit_date, precision) : 'heute'}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title={org.department_label_plural}>
        {member.departments.length === 0 ? (
          <p className="muted">Keine Zuordnung.</p>
        ) : (
          <ul className="plain-list">
            {member.departments.map((d) => (
              <li key={d.id}>
                <strong>{d.department_name}</strong> · {formatMemberDate(d.valid_from, precision)} –{' '}
                {d.valid_until ? formatMemberDate(d.valid_until, precision) : 'heute'}
                {canEdit && !d.valid_until && (
                  <button
                    type="button"
                    className="link-button spaced"
                    onClick={() =>
                      void run(() => memberApi.endDepartment(org.id, member.id, d.id, todayIso()))
                    }
                  >
                    beenden
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {canEdit && departments.data && departments.data.length > 0 && (
          <AddWithDate
            label={`${org.department_label} hinzufügen`}
            options={departments.data
              .filter((d) => d.is_active)
              .map((d) => ({ id: d.id, name: unitName(d) }))}
            onAdd={(id, date) =>
              run(() =>
                memberApi.addDepartment(org.id, member.id, { department: id, valid_from: date }),
              )
            }
          />
        )}
        {org.modules.includes('billing') && member.departments.some((d) => !d.valid_until) && (
          <Checkbox
            label={`zahlt den Beitrag selbst (nicht über die Sammelrechnung ${org.department_terms?.gen ?? `der ${org.department_label}`})`}
            checked={member.pays_fee_self}
            disabled={!canEdit}
            onChange={(val) =>
              void run(() => memberApi.update(org.id, member.id, { pays_fee_self: val }))
            }
          />
        )}
      </Section>
      {/* Eigene Region, unabhängig von Untereinheiten (UX-Audit 31.10. W08) */}
      <Section title="Kommunikation & Zustellung">
        <Checkbox
          label="Rundschreiben der Art „Information“ erwünscht"
          checked={!member.info_opt_out_at}
          disabled={!canEdit}
          onChange={(val) =>
            void run(() => memberApi.update(org.id, member.id, { info_opt_out: !val }))
          }
        />
        <p className="small" role="status">
          {member.info_opt_out_at ? (
            <>
              Seit {formatDate(member.info_opt_out_at)} abbestellt (
              <Term k="opt_out">Widerspruch</Term>): keine Informationen per E-Mail oder Brief.
            </>
          ) : (
            'Erhält Informationen.'
          )}
        </p>
        <p className="muted small">
          Vereinsmitteilungen, Kurzmitteilungen, Rechnungen und Post an Vorstände oder Rolleninhaber
          kommen unabhängig davon.
        </p>
      </Section>
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

function DurationLine({ label, info }: { label: string; info: DurationInfo }) {
  return (
    <p>
      <strong>
        {info.years} {info.years === 1 ? 'Jahr' : 'Jahre'}
      </strong>{' '}
      {label}
      <span className="muted small">
        {' '}
        (
        {info.precision === 'day' || !info.precision
          ? `${info.days} Tage gezählt`
          : DATE_PRECISION_WORD[info.precision] + ' gezählt'}
        {info.next &&
          ` · nächstes Jubiläum: ${info.next.years} Jahre ${jubileeWhen(info.next.date, info.precision)}`}
        )
      </span>
    </p>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card card-wide">
      <h2>{title}</h2>
      {children}
    </div>
  )
}

function AddPeriod({
  org,
  member,
  onAdded,
}: {
  org: OrgSummary
  member: MemberDetail
  onAdded: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const types = useLoad(() => memberApi.types(org.id), [org.id])
  const empty = { entry_date: '', exit_date: '', exit_reason: 'exit', member_type: '' }
  const form = useForm(empty)
  // Nachtrag vor dem Speichern nicht unbemerkt verlieren (UX-Audit 31.10. W01)
  const { dirty } = useChangesGuard(form.values, open)
  if (!open) {
    return (
      <button type="button" className="button button-ghost" onClick={() => setOpen(true)}>
        Früheren Zeitraum nachtragen
      </button>
    )
  }
  async function save(ev: FormEvent) {
    ev.preventDefault()
    const { member_type, ...rest } = form.values
    const ok = await form.submit(() =>
      memberApi.addPeriod(org.id, member.id, {
        ...rest,
        member_type: member_type ? Number(member_type) : null,
      }),
    )
    if (ok) {
      form.setValues(empty)
      setOpen(false)
      await onAdded()
    }
  }
  return (
    <form className="subcard" onSubmit={save}>
      <div className="grid-3">
        <Field
          label="Eintritt"
          type="date"
          required
          value={form.values.entry_date}
          error={form.errors.entry_date}
          onChange={(e) => form.set('entry_date', e.target.value)}
        />
        <Field
          label="Austritt"
          type="date"
          required
          value={form.values.exit_date}
          error={form.errors.exit_date}
          onChange={(e) => form.set('exit_date', e.target.value)}
        />
        <SelectField
          label="Grund"
          value={form.values.exit_reason}
          error={form.errors.exit_reason}
          onChange={(e) => form.set('exit_reason', e.target.value)}
        >
          {member.exit_reasons.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </SelectField>
      </div>
      <SelectField
        label="Mitgliedsart in diesem Zeitraum"
        value={form.values.member_type}
        error={form.errors.member_type}
        onChange={(e) => form.set('member_type', e.target.value)}
      >
        <option value="">– unbekannt –</option>
        {types.data?.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </SelectField>
      {orgTerms(org).dv_has && (
        <p className="muted small">
          Nur Zeiten mit einer gemeldeten Art zählen für {orgTerms(org).dv_akk}.
        </p>
      )}
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={form.busy}>
          Speichern
        </button>
        <button
          type="button"
          className="button button-ghost"
          onClick={() =>
            void confirmDiscard(dirty).then((yes) => {
              if (!yes) return
              form.setValues(empty)
              setOpen(false)
            })
          }
        >
          Abbrechen
        </button>
      </div>
    </form>
  )
}

function FederationEntry({
  org,
  member,
  onSaved,
}: {
  org: OrgSummary
  member: MemberDetail
  onSaved: (m: MemberDetail) => void
}) {
  const form = useForm({
    date: member.federation?.entry_date_manual ? (member.federation.entry_date ?? '') : '',
  })
  async function save(ev: FormEvent) {
    ev.preventDefault()
    const saved = await form.submit(() =>
      memberApi.setFederationEntry(org.id, member.id, form.values.date || null),
    )
    if (saved) onSaved(saved as MemberDetail)
  }
  return (
    <form className="inline-add" onSubmit={save}>
      <input
        type="date"
        aria-label={`Eintritt in ${orgTerms(org).dv_akk} (Altdaten)`}
        value={form.values.date}
        onChange={(e) => form.set('date', e.target.value)}
      />
      <button type="submit" className="button button-ghost" disabled={form.busy}>
        {form.values.date ? 'Eintritt von Hand setzen' : 'Berechnen lassen'}
      </button>
    </form>
  )
}

function AddWithDate({
  label,
  options,
  onAdd,
}: {
  label: string
  options: { id: number; name: string }[]
  onAdd: (id: number, date: string) => Promise<void>
}) {
  const [id, setId] = useState('')
  const [date, setDate] = useState(todayIso)
  return (
    <form
      className="inline-add"
      onSubmit={(e) => {
        e.preventDefault()
        if (id) void onAdd(Number(id), date).then(() => setId(''))
      }}
    >
      <select aria-label={label} value={id} onChange={(e) => setId(e.target.value)}>
        <option value="">{label} …</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      <input type="date" aria-label="ab" value={date} onChange={(e) => setDate(e.target.value)} />
      <button type="submit" className="button button-ghost">
        Hinzufügen
      </button>
    </form>
  )
}

function RolesTab({
  org,
  member,
  canEdit,
  reload,
}: {
  org: OrgSummary
  member: MemberDetail
  canEdit: boolean
  reload: () => Promise<void>
}) {
  const departments = useLoad(() => orgApi.departments(org.id), [org.id])
  const [error, setError] = useState<string | null>(null)
  const roleOptions =
    departments.data?.flatMap((d) =>
      d.roles.map((r) => ({ id: r.id, name: `${r.name} (${d.name})` })),
    ) ?? []

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="stack">
      <HonoraryAwards
        orgId={org.id}
        memberId={member.id}
        awards={member.honorary_titles?.own ?? []}
        otherAwards={member.honorary_titles?.federation}
        otherLabel={`Verliehen ${orgTerms(org).dv_vom}`}
        canEdit={canEdit}
        onChanged={reload}
      />
      <Section title="Vorstandsrollen">
        {member.board_roles.length === 0 ? (
          <p className="muted">
            Keine. Vorstandsrollen vergibst du unter Einstellungen → Rollen & Benutzer.
          </p>
        ) : (
          <ul className="plain-list">
            {member.board_roles.map((r) => (
              <li key={r.id}>
                <strong>{r.role_name}</strong> · {formatDate(r.valid_from)} –{' '}
                {r.valid_until ? formatDate(r.valid_until) : 'heute'}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title={`Rollen in ${org.department_terms?.pl_dat ?? org.department_label_plural}`}>
        {member.department_roles.length === 0 ? (
          <p className="muted">Keine.</p>
        ) : (
          <ul className="plain-list">
            {member.department_roles.map((r) => (
              <li key={r.id}>
                <strong>{r.role_name}</strong> ({r.department_name}) · {formatDate(r.valid_from)} –{' '}
                {r.valid_until ? formatDate(r.valid_until) : 'heute'}
                {canEdit && !r.valid_until && (
                  <button
                    type="button"
                    className="link-button spaced"
                    onClick={() =>
                      void run(() =>
                        memberApi.endDepartmentRole(org.id, member.id, r.id, todayIso()),
                      )
                    }
                  >
                    beenden
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {canEdit && roleOptions.length > 0 && (
          <AddWithDate
            label="Rolle hinzufügen"
            options={roleOptions}
            onAdd={(id, date) =>
              run(() =>
                memberApi.addDepartmentRole(org.id, member.id, { role: id, valid_from: date }),
              )
            }
          />
        )}
        {error && <Alert kind="error">{error}</Alert>}
      </Section>
    </div>
  )
}

function HistoryTab({ orgId, memberId }: { orgId: number; memberId: number }) {
  const { data, error } = useLoad(() => memberApi.history(orgId, memberId), [orgId, memberId])
  const first = firstOfSet(data ?? [])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return (
    <Section title="Verlauf">
      {data.length === 0 ? (
        <p className="muted">Noch keine Einträge.</p>
      ) : (
        <ul className="audit-list">
          {data.map((entry) => (
            <li key={entry.id}>
              <div>
                <strong>{entry.object_type}</strong> {entry.action_label}
              </div>
              <div className="muted small">
                {formatDateTime(entry.timestamp)} · {entry.user_email || 'System'}
                {entry.via ? ` · über ${entry.via}` : ''}
              </div>
              {Object.keys(entry.changes).length > 0 && (
                <ul className="changes small">
                  {Object.entries(entry.changes).map(([field, [before, after]]) => (
                    <li key={field}>
                      {field}: {String(before ?? '–')} → {String(after ?? '–')}
                    </li>
                  ))}
                </ul>
              )}
              <AuditUndo entry={entry} orgId={orgId} showAction={first.has(entry.id)} />
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}
