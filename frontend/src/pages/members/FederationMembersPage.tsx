import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'
import { cardApi } from '../../api/cards.ts'
import { api } from '../../api/client.ts'
import type { MemberDetail, MemberRow, Page } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { ExportPanel } from '../../components/ExportPanel.tsx'
import {
  errorMessage,
  formatMemberDate,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { Alert, Field, SaveStatus } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { MembersDevelopmentPage } from './DevelopmentPage.tsx'
import { HonoraryAwards } from './HonoraryAwards.tsx'
import { memberApi } from '../../api/members.ts'
import { useTerms } from '../../org/terms.ts'
import { Term } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

type FedRow = MemberRow & { club: string; club_id: number }
type FedDetail = MemberDetail & { club: string; readonly: boolean; remote?: boolean }

const base = (org: number) => `/api/orgs/${org}/federation`

/** Dachverband: Mitglieder aller angeschlossenen Vereine (gemäß Plattform-Freigabe).
 *  `prefix`: Pfad der Übersicht (mit eigenen Mitgliedern liegt sie unter /mitglieder/verbund). */
export function FederationMembersPage({ prefix = '/mitglieder' }: { prefix?: string }) {
  const tm = useTerms()
  const org = useActiveOrg()
  if (!org.federation_member_access || org.federation_member_access === 'none') {
    return (
      <section>
        <h1>{t('Mitglieder')}</h1>
        <div className="card empty-state">
          <p>
            {t(
              'Die Plattform hat den Zugriff auf Mitgliedsdaten der {pl} für {e_diesen} nicht freigegeben.',
              { pl: tm.pl, e_diesen: tm.e_diesen },
            )}
          </p>
        </div>
      </section>
    )
  }
  return (
    <Routes>
      <Route index element={<FederationList prefix={prefix} />} />
      <Route path="entwicklung" element={<MembersDevelopmentPage view="all" />} />
      <Route path=":id" element={<FederationDetail prefix={prefix} />} />
    </Routes>
  )
}

function FederationList({ prefix }: { prefix: string }) {
  const tm = useTerms()
  const org = useActiveOrg()
  const clubs = useLoad(
    () => api.get<{ id: number; name: string }[]>(`${base(org.id)}/clubs/`),
    [org.id],
  )
  const titles = useLoad(() => memberApi.honoraryTitles(org.id), [org.id])
  const [params, setParams] = useState<Record<string, string>>({
    status: 'aktiv',
    sortierung: 'name',
  })
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<FedRow> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showExport, setShowExport] = useState(false)

  useEffect(() => {
    const tmx = setTimeout(() => {
      setParams((p) => ({ ...p, suche: search }))
      setPage(1)
    }, 300)
    return () => clearTimeout(tmx)
  }, [search])

  useEffect(() => {
    let alive = true
    const q = new URLSearchParams(
      Object.entries({ ...params, page: String(page), page_size: '50' }).filter(([, v]) => v),
    )
    api
      .get<Page<FedRow>>(`${base(org.id)}/members/?${q}`)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((err) => alive && setError(errorMessage(err)))
    return () => {
      alive = false
    }
  }, [org.id, params, page])

  const set = (key: string, value: string) => {
    setParams((p) => ({ ...p, [key]: value }))
    setPage(1)
  }
  const pages = data ? Math.max(1, Math.ceil(data.count / 50)) : 1

  return (
    <section>
      <div className="page-head">
        <h1>
          {t('Mitglieder')} {tm.e_im}
        </h1>
        {org.permissions.includes(PERM.cardsManage) && (
          <a
            className="button button-ghost push-right"
            href={cardApi.orgPdfUrl(org.id, {
              suche: params.suche,
              verein: params.verein,
              gemeldet: params.gemeldet,
              aktiv: params.aktiv,
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
        {org.permissions.includes(PERM.exportRun) && (
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShowExport((s) => !s)}
          >
            {t('Export')}
          </button>
        )}
      </div>
      <p className="muted small">
        {t('Zugriff:')}{' '}
        {org.federation_member_access === 'write' ? t('lesen und ändern') : t('nur lesen')}{' '}
        {t('· jeder Zugriff wird protokolliert.')}
      </p>
      <div className="card card-wide filters">
        <input
          type="search"
          className="search-input"
          aria-label={t('Suchen')}
          placeholder={t('Suchen: Name oder Verbandsnummer')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label={tm.Sg}
          value={params.verein ?? ''}
          onChange={(e) => set('verein', e.target.value)}
        >
          <option value="">alle {tm.pl}</option>
          {clubs.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t('Status')}
          value={params.status}
          onChange={(e) => set('status', e.target.value)}
        >
          <option value="aktiv">{t('aktuelle Mitglieder')}</option>
          <option value="ehemalig">ehemalige</option>
          <option value="alle">alle</option>
        </select>
        {titles.data && titles.data.length > 0 && (
          <select
            aria-label={t('Ehrungen')}
            value={params.ehrentitel ?? ''}
            onChange={(e) => set('ehrentitel', e.target.value)}
          >
            <option value="">{t('alle (mit und ohne Ehrung)')}</option>
            <option value="mit">
              {t('mit Ehrung')} {tm.e_gen}
            </option>
            {titles.data.map((tmx) => (
              <option key={tmx.id} value={tmx.id}>
                {tmx.name}
                {tmx.is_archived ? ' (archiviert)' : ''}
              </option>
            ))}
          </select>
        )}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={params.gemeldet === '1'}
            onChange={(e) => set('gemeldet', e.target.checked ? '1' : '')}
          />
          <span>{t('nur gemeldete')}</span>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={params.aktiv === '1'}
            onChange={(e) => set('aktiv', e.target.checked ? '1' : '')}
          />
          <span>{t('nur aktive')}</span>
        </label>
      </div>
      {showExport && (
        <ExportPanel
          orgId={org.id}
          kind="federation_members"
          filters={params}
          onClose={() => setShowExport(false)}
        />
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {!data ? (
        <p className="muted">{t('Lädt …')}</p>
      ) : (
        <div className="card card-wide">
          <p className="muted small">
            {data.count} {t('Mitgliedschaften')}
          </p>
          <table className="table member-table">
            <thead>
              <tr>
                <th>{t('Name')}</th>
                <th>{tm.Sg}</th>
                <th className="col-optional">
                  <Term k="federation_number">{t('Verbandsnr.')}</Term>
                </th>
                <th className="col-optional">
                  <Term k="member_type">{t('Mitgliedsart')}</Term>
                </th>
                <th className="col-optional">{t('Eintritt')}</th>
                <th className="col-optional">{t('Ehrungen')}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => (
                <tr key={r.id} className={r.status === 'former' ? 'inactive' : ''}>
                  <td>
                    <Link to={`${prefix}/${r.id}`}>
                      {r.last_name}, {r.first_name}
                    </Link>
                  </td>
                  <td>{r.club}</td>
                  <td className="col-optional">{r.member_number ?? '–'}</td>
                  <td className="col-optional">{r.member_type ?? '–'}</td>
                  <td className="col-optional">
                    {formatMemberDate(r.entry_date, org.date_precision)}
                  </td>
                  <td className="col-optional">{(r.honorary_titles ?? []).join(', ') || '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 && (
            <div className="pager">
              <button
                type="button"
                className="button button-ghost"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                {t('Zurück')}
              </button>
              <span className="small">
                {t('Seite {page} von', { page })} {pages}
              </span>
              <button
                type="button"
                className="button button-ghost"
                disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}
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

function FederationDetail({ prefix }: { prefix: string }) {
  const tm = useTerms()
  const org = useActiveOrg()
  const id = Number(useParams().id)
  const { data, error, setData, reload } = useLoad(
    () => api.get<FedDetail>(`${base(org.id)}/members/${id}/`),
    [org.id, id],
  )
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <section>
      <p>
        <Link to={prefix}>
          {t('← Mitglieder')} {tm.e_im}
        </Link>
      </p>
      <h1>
        {data.first_name} {data.last_name}
      </h1>
      <p className="muted">
        {data.club} · {data.status === 'active' ? t('Mitglied') : t('ehemaliges Mitglied')}
        {data.current_type &&
          t(' · {member_type_name}', { member_type_name: data.current_type.member_type_name })}
        {data.federation?.member_number &&
          t(' · Verbandsnr. {member_number}', { member_number: data.federation.member_number })}
      </p>
      <div className="stack">
        {data.remote ? (
          <SuggestCorrection
            orgId={org.id}
            member={data}
            owner={data.club}
            intro={`${data.club} führt die Daten auf einer eigenen Instanz und meldet nur Name, Vorname, Geburtsdatum, Mitgliedsart und Zeiträume. Ändern kann nur ${data.club}; hier lässt sich eine Korrektur vorschlagen.`}
          />
        ) : (
          <FederationMasterData orgId={org.id} member={data} onSaved={setData} />
        )}
        <HonoraryAwards
          orgId={org.id}
          memberId={data.id}
          awards={data.honorary_titles?.federation ?? []}
          otherAwards={data.honorary_titles?.own}
          otherLabel={`Verliehen ${tm.vom} (${data.club})`}
          canEdit={org.permissions.includes(PERM.membersEdit)}
          federation
          onChanged={reload}
        />
        {org.permissions.includes(PERM.cardsManage) && data.status === 'active' && (
          <div className="card card-wide">
            <h2>{t('Mitgliedsausweis')}</h2>
            <p className="muted small">
              {t('Sperren und neu erzeugen kann {nom}. Hier lässt sich der Ausweis drucken.', {
                nom: tm.nom,
              })}
            </p>
            <a
              className="button button-ghost"
              href={cardApi.orgPdfUrl(org.id, { mitglied: data.id })}
            >
              {t('Ausweis als PDF')}
            </a>
          </div>
        )}
        <div className="card card-wide">
          <h2>
            {t('Mitgliedschaft')} {tm.e_im}
          </h2>
          {data.federation && (
            <p>
              {t('Eintritt: {x} ·', {
                x: formatMemberDate(data.federation.entry_date, org.date_precision),
              })}{' '}
              {data.duration.federation?.years ?? 0}{' '}
              {t('Jahre ({rule})', { rule: data.duration.federation?.rule })}
            </p>
          )}
          <ul className="plain-list">
            {data.periods.map((p) => (
              <li key={p.id}>
                {data.club}: {formatMemberDate(p.entry_date, org.date_precision)} –{' '}
                {p.exit_date ? formatMemberDate(p.exit_date, org.date_precision) : 'heute'}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

function FederationMasterData({
  orgId,
  member,
  onSaved,
}: {
  orgId: number
  member: FedDetail
  onSaved: (m: FedDetail) => void
}) {
  const c = member.contact
  const form = useForm({
    email: c?.email ?? '',
    phone: c?.phone ?? '',
    street: c?.street ?? '',
    postal_code: c?.postal_code ?? '',
    city: c?.city ?? '',
  })
  // Kontaktdaten gehören zusammen und werden daher immer gemeinsam gespeichert
  const auto = useAutoSave(
    form,
    (_changes, values) => api.patch<FedDetail>(`${base(orgId)}/members/${member.id}/`, values),
    { enabled: !member.readonly, onSaved: (saved) => onSaved(saved as FedDetail) },
  )
  return (
    <form
      className="card card-wide"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        void auto.flush()
      }}
    >
      <div className="card-head">
        <h2>{t('Kontakt und Anschrift')}</h2>
        {!member.readonly && <SaveStatus auto={auto} />}
      </div>
      <fieldset disabled={member.readonly}>
        <div className="grid-2">
          <Field
            label={t('E-Mail')}
            type="email"
            value={form.values.email}
            error={form.errors.email}
            onChange={(e) => form.set('email', e.target.value)}
          />
          <Field
            label={t('Telefon')}
            value={form.values.phone}
            onChange={(e) => form.set('phone', e.target.value)}
          />
        </div>
        <Field
          label={t('Straße und Hausnummer')}
          value={form.values.street}
          error={form.errors.street}
          onChange={(e) => form.set('street', e.target.value)}
        />
        <div className="grid-2">
          <Field
            label="PLZ"
            value={form.values.postal_code}
            onChange={(e) => form.set('postal_code', e.target.value)}
          />
          <Field
            label={t('Ort')}
            value={form.values.city}
            onChange={(e) => form.set('city', e.target.value)}
          />
        </div>
      </fieldset>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
    </form>
  )
}

/** Person, deren Daten eine Einheit auf einer anderen Instanz pflegt (Verbund): nur Korrektur
 * vorschlagen. */
export function SuggestCorrection({
  orgId,
  member,
  owner,
  intro,
}: {
  orgId: number
  member: { id: number; last_name: string; first_name: string; birth_date: string }
  /** Einheit, die die Daten pflegt */
  owner: string
  intro: string
}) {
  const [values, setValues] = useState({
    last_name: member.last_name,
    first_name: member.first_name,
    birth_date: member.birth_date,
    message: '',
  })
  const [msg, setMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const canEdit = useActiveOrg().permissions.includes(PERM.membersEdit)

  async function send() {
    setMsg(null)
    setBusy(true)
    const data: Record<string, string> = { message: values.message }
    for (const k of ['last_name', 'first_name', 'birth_date'] as const) {
      if (values[k] !== member[k]) data[k] = values[k]
    }
    try {
      await api.post(`/api/orgs/${orgId}/peering/members/${member.id}/suggest/`, data)
      setMsg({ kind: 'success', text: t('Der Vorschlag ist an {owner} unterwegs.', { owner }) })
    } catch (e) {
      setMsg({ kind: 'error', text: errorMessage(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>{t('Angaben aus der Meldung')}</h2>
      <p className="muted small">{intro}</p>
      {canEdit && (
        <>
          <div className="grid-2">
            <Field
              label={t('Name')}
              value={values.last_name}
              onChange={(e) => setValues({ ...values, last_name: e.target.value })}
            />
            <Field
              label={t('Vorname')}
              value={values.first_name}
              onChange={(e) => setValues({ ...values, first_name: e.target.value })}
            />
          </div>
          <Field
            label={t('Geburtsdatum')}
            type="date"
            value={values.birth_date}
            onChange={(e) => setValues({ ...values, birth_date: e.target.value })}
          />
          <Field
            label={t('Nachricht an {owner}', { owner })}
            value={values.message}
            onChange={(e) => setValues({ ...values, message: e.target.value })}
          />
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void send()}
            >
              {t('Korrektur vorschlagen')}
            </button>
          </div>
        </>
      )}
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </div>
  )
}
