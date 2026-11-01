// Kasse: Buchungen erfassen, suchen und mit Belegen versehen.
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useDetailParam } from '../../components/detailParam.ts'
import { euro, financeApi, parseAmount } from '../../api/finance.ts'
import type {
  Account,
  Booking,
  BookingFilter,
  BookingKind,
  Category,
  EInvoiceInfo,
  Project,
  Receipt,
} from '../../api/finance.ts'
import type { MemberRow, Page } from '../../api/members.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import type { Department } from '../../api/orgs.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { errorMessage, formatDate, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { ApiError } from '../../api/client.ts'
import { useTerms } from '../../org/terms.ts'
import { Term, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

/** Wer das Geld bekommt (Ausgabe) bzw. zahlt (Einnahme). */
function partnerLabel(kind: BookingKind): string {
  return kind === 'expense' ? t('Empfänger') : t('Zahler')
}

const KIND_LABEL: Record<BookingKind, string> = {
  income: t('Einnahme'),
  expense: t('Ausgabe'),
  transfer: t('Umbuchung'),
}

const KIND_PARAM: Record<BookingKind, string> = {
  income: 'einnahme',
  expense: 'ausgabe',
  transfer: 'umbuchung',
}
const NEW_KIND: Record<string, BookingKind> = {
  einnahme: 'income',
  ausgabe: 'expense',
  umbuchung: 'transfer',
}

export function BookingsPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.financeEdit)
  const [params, setParams] = useSearchParams()
  const settings = useLoad(() => financeApi.settings(org.id), [org.id])
  const accounts = useLoad(() => financeApi.accounts(org.id), [org.id])
  const categories = useLoad(() => financeApi.categories(org.id), [org.id])
  const projects = useLoad(() => financeApi.projects(org.id), [org.id])
  const departments = useLoad(
    () => (org.type === 'club' ? orgApi.departments(org.id) : Promise.resolve([])),
    [org.id, org.type],
  )
  const partners = useLoad(() => financeApi.counterparties(org.id), [org.id])
  const [search, setSearch] = useState(params.get('suche') ?? '')
  const [partner, setPartner] = useState(params.get('partner') ?? '')
  const [data, setData] = useState<Page<Booking> | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Geöffnete Buchung in der Adresse: ?buchung=12 bzw. ?buchung=neu-ausgabe
  const detail = useDetailParam('buchung')
  const [loaded, setLoaded] = useState<Booking | null>(null)
  const [missing, setMissing] = useState<string | null>(null)
  const openedId = detail.value && /^\d+$/.test(detail.value) ? Number(detail.value) : null
  const newKind = detail.value?.startsWith('neu-') ? NEW_KIND[detail.value.slice(4)] : undefined
  const editing: Booking | BookingKind | null =
    newKind ??
    (openedId !== null
      ? (data?.results.find((b) => b.id === openedId) ?? (loaded?.id === openedId ? loaded : null))
      : null)
  function setEditing(b: Booking | BookingKind | null, replace = false) {
    if (b === null) return detail.close()
    if (typeof b !== 'string') setLoaded(b)
    const v = typeof b === 'string' ? `neu-${KIND_PARAM[b]}` : String(b.id)
    if (replace) detail.replace(v)
    else detail.open(v)
  }
  const [version, setVersion] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)

  const year = params.get('jahr') ?? (settings.data ? String(settings.data.current_year) : '')
  const filter: BookingFilter = {
    jahr: year,
    konto: params.get('konto') ?? '',
    kategorie: params.get('kategorie') ?? '',
    art: params.get('art') ?? '',
    bereich: params.get('bereich') ?? '',
    suche: params.get('suche') ?? '',
    partner: params.get('partner') ?? '',
    ohne_beleg: params.get('ohne_beleg') === '1',
    veranstaltung: params.get('veranstaltung') ?? '',
    page: Number(params.get('seite') ?? 1),
  }
  const filterKey = JSON.stringify(filter)

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    // Neue Filter beginnen auf Seite 1; Blättern selbst behält die Seite
    if (key !== 'seite') next.delete('seite')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    const tm = setTimeout(() => {
      if ((params.get('suche') ?? '') !== search) setFilter('suche', search)
    }, 300)
    return () => clearTimeout(tm)
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  useEffect(() => {
    const tm = setTimeout(() => {
      if ((params.get('partner') ?? '') !== partner.trim()) setFilter('partner', partner.trim())
    }, 400)
    return () => clearTimeout(tm)
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [partner])

  // Direkt aufgerufene Buchung (Link, Neuladen), die nicht auf der aktuellen Seite steht
  useEffect(() => {
    if (openedId === null || loaded?.id === openedId) return
    if (data?.results.some((b) => b.id === openedId)) return
    let alive = true
    financeApi
      .booking(org.id, openedId)
      .then((b) => {
        if (alive) {
          setLoaded(b)
          setMissing(null)
        }
      })
      .catch((err) => alive && setMissing(errorMessage(err)))
    return () => {
      alive = false
    }
  }, [org.id, openedId, loaded, data])

  useEffect(() => {
    if (!year) return
    let alive = true
    financeApi
      .bookings(org.id, JSON.parse(filterKey) as BookingFilter)
      .then((d) => {
        if (alive) {
          setData(d)
          setError(null)
        }
      })
      .catch((err) => alive && setError(errorMessage(err)))
    return () => {
      alive = false
    }
  }, [org.id, filterKey, year, version])

  const loadError = settings.error ?? accounts.error ?? categories.error
  if (loadError) return <Alert kind="error">{loadError}</Alert>
  if (!settings.data || !accounts.data || !categories.data)
    return <p className="muted">{t('Lädt …')}</p>

  const refresh = () => {
    setVersion((v) => v + 1)
    void accounts.reload()
    void partners.reload()
  }
  const pages = data ? Math.max(1, Math.ceil(data.count / 100)) : 1

  if (accounts.data.length === 0) {
    return (
      <div className="card empty-state">
        <p>
          {t('Zum Buchen muss zuerst ein Konto eingerichtet werden:')}{' '}
          <Link to="/finanzen/einstellungen/konten">{t('Finanzen → Einrichtung → Konten')}</Link>.
        </p>
      </div>
    )
  }

  return (
    <div className="stack">
      {canEdit && editing === null && (
        <div className="button-row">
          <button
            type="button"
            className="button button-primary"
            onClick={() => setEditing('income')}
          >
            {t('Einnahme')}
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={() => setEditing('expense')}
          >
            {t('Ausgabe')}
          </button>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setEditing('transfer')}
          >
            {t('Umbuchung')}
          </button>
        </div>
      )}
      {openedId !== null && editing === null && missing && (
        <Alert kind="error">
          {t('Die Buchung lässt sich nicht öffnen:')} {missing}
        </Alert>
      )}
      {editing !== null && (
        <BookingForm
          key={typeof editing === 'string' ? `${editing}-${version}` : editing.id}
          orgId={org.id}
          isClub={org.type === 'club'}
          booking={typeof editing === 'string' ? null : editing}
          kind={typeof editing === 'string' ? editing : editing.kind}
          accounts={accounts.data}
          categories={categories.data}
          departments={departments.data ?? []}
          projects={projects.data ?? []}
          canEdit={canEdit}
          onSaved={(b, again) => {
            refresh()
            if (again) setVersion((v) => v + 1)
            setEditing(again ? b.kind : b, true)
          }}
          onClose={() => {
            setEditing(null)
            refresh()
          }}
        />
      )}

      <div className="card card-wide filters">
        <input
          type="search"
          className="search-input"
          placeholder={t('Suchen: Text, Empfänger/Zahler, Belegnummer, Betrag oder Nummer')}
          aria-label={t('Buchungen suchen')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <input
          type="search"
          list="booking-partners-filter"
          placeholder={t('Empfänger/Zahler')}
          aria-label={t('Empfänger/Zahler')}
          value={partner}
          onChange={(e) => setPartner(e.target.value)}
        />
        <datalist id="booking-partners-filter">
          {(partners.data ?? []).map((p) => (
            <option key={p.name} value={p.name} />
          ))}
        </datalist>
        <select
          aria-label={t('Geschäftsjahr')}
          value={year}
          onChange={(e) => setFilter('jahr', e.target.value)}
        >
          {settings.data.years.map((y) => (
            <option key={y.year} value={y.year}>
              {y.label}
            </option>
          ))}
          <option value="alle">{t('alle Jahre')}</option>
        </select>
        <select
          aria-label={t('Konto')}
          value={filter.konto}
          onChange={(e) => setFilter('konto', e.target.value)}
        >
          <option value="">{t('alle Konten')}</option>
          {accounts.data.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t('Kategorie')}
          value={filter.kategorie}
          onChange={(e) => setFilter('kategorie', e.target.value)}
        >
          <option value="">{t('alle Kategorien')}</option>
          {categories.data.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          aria-label={t('Art')}
          value={filter.art}
          onChange={(e) => setFilter('art', e.target.value)}
        >
          <option value="">{t('alle Arten')}</option>
          {Object.entries(KIND_LABEL).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        {settings.data.tax_areas_enabled && (
          <select
            aria-label={t('steuerlicher Bereich')}
            value={filter.bereich}
            onChange={(e) => setFilter('bereich', e.target.value)}
          >
            <option value="">{t('alle Bereiche')}</option>
            {settings.data.tax_areas.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
            <option value="-">{t('ohne Zuordnung')}</option>
          </select>
        )}
        {(projects.data?.length ?? 0) > 0 && (
          <select
            aria-label={t('Veranstaltung')}
            value={filter.veranstaltung}
            onChange={(e) => setFilter('veranstaltung', e.target.value)}
          >
            <option value="">{t('alle Veranstaltungen')}</option>
            <option value="-">{t('ohne Veranstaltung')}</option>
            {projects.data!.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        {canEdit && year && year !== 'alle' && (
          <button
            type="button"
            className="button button-ghost"
            onClick={async () => {
              const label = settings.data!.years.find((y) => String(y.year) === year)?.label
              if (
                await confirmDialog({
                  title: t('Buchungen neu nummerieren?'),
                  message: t(
                    'Alle Buchungen im Geschäftsjahr {x} werden nach Datum neu durchnummeriert.',
                    { x: label ?? year },
                  ),
                  confirmLabel: t('Neu nummerieren'),
                  danger: false,
                })
              ) {
                financeApi
                  .renumber(org.id, Number(year))
                  .then((r) => {
                    setNotice(t('{changed} Buchungsnummern geändert.', { changed: r.changed }))
                    refresh()
                  })
                  .catch((err) => setError(errorMessage(err)))
              }
            }}
          >
            {t('Neu nummerieren')}
          </button>
        )}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={filter.ohne_beleg}
            onChange={(e) => setFilter('ohne_beleg', e.target.checked ? '1' : '')}
          />
          <span>{t('ohne Beleg')}</span>
        </label>
      </div>

      <div className="card card-wide">
        {error && <Alert kind="error">{error}</Alert>}
        {notice && <Alert kind="success">{notice}</Alert>}
        {!data ? (
          <p className="muted">{t('Lädt …')}</p>
        ) : data.results.length === 0 ? (
          <p className="muted">{t('Keine Buchungen gefunden.')}</p>
        ) : (
          <>
            <p className="muted small">
              {data.count} {t('Buchungen')}
            </p>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Nr.</th>
                    <th>{t('Datum')}</th>
                    <th>{t('Text')}</th>
                    <th>{t('Konto')}</th>
                    <th>{t('Kategorie')}</th>
                    <th className="num">{t('Betrag')}</th>
                    <th>
                      <Term k="receipt">{t('Beleg')}</Term>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((b) => (
                    <BookingRow
                      key={b.id}
                      booking={b}
                      account={filter.konto ? Number(filter.konto) : null}
                      onOpen={() => setEditing(b)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            {pages > 1 && (
              <div className="button-row">
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={filter.page! <= 1}
                  onClick={() =>
                    setFilter('seite', filter.page! > 2 ? String(filter.page! - 1) : '')
                  }
                >
                  {t('Zurück')}
                </button>
                <span className="muted small">
                  {t('Seite {page} von', { page: filter.page })} {pages}
                </span>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={filter.page! >= pages}
                  onClick={() => setFilter('seite', String(filter.page! + 1))}
                >
                  {t('Weiter')}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function signedAmount(b: Booking, account: number | null): number {
  const amount = Number(b.amount)
  if (b.kind === 'income') return amount
  if (b.kind === 'expense') return -amount
  if (account !== null) return b.to_account === account ? amount : -amount
  return amount
}

function BookingRow({
  booking: b,
  account,
  onOpen,
}: {
  booking: Booking
  account: number | null
  onOpen: () => void
}) {
  const value = signedAmount(b, account)
  const visible = b.receipts.filter((r) => !r.hidden_at).length
  return (
    <tr className={b.cancelled_by ? 'booking-cancelled' : undefined}>
      <td>
        <button type="button" className="link-button" onClick={onOpen}>
          {b.display_number}
        </button>
        {b.fixed && (
          <span className="muted" title="festgeschrieben" aria-label="festgeschrieben">
            {' '}
            🔒
          </span>
        )}
      </td>
      <td>{formatDate(b.date)}</td>
      <td>
        {b.text}
        {b.cancelled_by && (
          <div className="small">
            {t('storniert durch')} {b.cancelled_by.number}
          </div>
        )}
        <div className="muted small">
          {[
            b.counterparty
              ? t('{x}: {counterparty}', { x: partnerLabel(b.kind), counterparty: b.counterparty })
              : null,
            b.reference,
            b.member_name,
            b.department_name,
            b.project_name,
          ]
            .filter(Boolean)
            .join(' · ')}
        </div>
      </td>
      <td>
        {b.kind === 'transfer'
          ? t('{account_name} → {to_account_name}', {
              account_name: b.account_name,
              to_account_name: b.to_account_name,
            })
          : b.account_name}
      </td>
      <td>
        {b.kind === 'transfer' ? <span className="muted">{t('Umbuchung')}</span> : b.category_name}
      </td>
      <td
        className={`num ${
          b.kind === 'transfer' && account === null ? '' : value < 0 ? 'amount-out' : 'amount-in'
        }`}
      >
        {euro(b.kind === 'transfer' && account === null ? Number(b.amount) : value)}
      </td>
      <td>{visible > 0 ? t('📎 {visible}', { visible }) : <span className="muted">–</span>}</td>
    </tr>
  )
}

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function BookingForm({
  orgId,
  isClub,
  booking,
  kind,
  accounts,
  categories,
  departments,
  projects,
  canEdit,
  onSaved,
  onClose,
}: {
  orgId: number
  isClub: boolean
  booking: Booking | null
  kind: BookingKind
  accounts: Account[]
  categories: Category[]
  departments: Department[]
  projects: Project[]
  canEdit: boolean
  onSaved: (b: Booking, again: boolean) => void
  onClose: () => void
}) {
  const tm = useTerms()
  const activeAccounts = accounts.filter((a) => a.is_active || a.id === booking?.account)
  const usable = categories.filter(
    (c) => (c.is_active || c.id === booking?.category) && (c.kind === 'both' || c.kind === kind),
  )
  const form = useForm({
    number: booking ? String(booking.number) : '',
    date: booking?.date ?? today(),
    amount: booking ? booking.amount.replace('.', ',') : '',
    account: String(booking?.account ?? activeAccounts[0]?.id ?? ''),
    to_account: String(booking?.to_account ?? ''),
    category: String(booking?.category ?? ''),
    text: booking?.text ?? '',
    reference: booking?.reference ?? '',
    counterparty: booking?.counterparty ?? '',
    department: String(booking?.department ?? ''),
    project: String(booking?.project ?? ''),
  })
  const usableProjects = projects.filter((p) => p.status !== 'done' || p.id === booking?.project)
  const [member, setMember] = useState<MemberRow | null>(
    booking?.membership
      ? ({
          id: booking.membership,
          last_name: booking.member_name?.split(', ')[0] ?? '',
          first_name: booking.member_name?.split(', ')[1] ?? '',
        } as MemberRow)
      : null,
  )
  const [again, setAgain] = useState(false)
  // E-Rechnung: gelesene Angaben füllen das Formular, die Datei wird nach dem Buchen Beleg
  const [einvoice, setEinvoice] = useState<{ file: File; info: EInvoiceInfo } | null>(null)
  const [einvoiceError, setEinvoiceError] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<string[]>([])
  useEffect(() => {
    if (kind === 'transfer') return
    let alive = true
    financeApi
      .counterparties(orgId, kind)
      .then((rows) => alive && setSuggestions(rows.map((r) => r.name)))
      .catch(() => alive && setSuggestions([]))
    return () => {
      alive = false
    }
  }, [orgId, kind])
  // Bei Ausgaben ist meist ein Geschäft der Empfänger: Mitglied und Abteilung eingeklappt
  const assignedOpen = kind === 'income' || !!booking?.membership || !!booking?.department

  function pickMember(m: MemberRow | null) {
    setMember(m)
    if (m && !v.counterparty.trim()) set('counterparty', `${m.first_name} ${m.last_name}`.trim())
  }
  const { values: v, errors, set } = form
  const readOnly = !canEdit
  // Festgeschrieben oder Teil eines Stornos: nur noch die Veranstaltung ist änderbar
  const locked = !!booking && (booking.fixed || !!booking.cancels || !!booking.cancelled_by)

  function payloadOf(x: typeof v & { membership: number | null }): Record<string, unknown> {
    return {
      date: x.date,
      ...(booking && x.number ? { number: Number(x.number) } : {}),
      kind,
      amount: parseAmount(x.amount),
      account: Number(x.account),
      to_account: kind === 'transfer' && x.to_account ? Number(x.to_account) : null,
      category: kind !== 'transfer' && x.category ? Number(x.category) : null,
      text: x.text,
      reference: x.reference,
      counterparty: kind === 'transfer' ? '' : x.counterparty,
      membership: x.membership,
      department: x.department ? Number(x.department) : null,
      project: kind !== 'transfer' && x.project ? Number(x.project) : null,
    }
  }

  // Bestehende Buchungen speichern automatisch, neue erst mit „Buchen“
  const auto = useAutoSave(
    { values: { ...v, membership: member?.id ?? null }, setErrors: form.setErrors },
    (_changes, values) => financeApi.updateBooking(orgId, booking!.id, payloadOf(values)),
    {
      enabled: booking !== null && canEdit,
      onSaved: (saved) => onSaved(saved as Booking, false),
    },
  )

  async function save(e: FormEvent) {
    e.preventDefault()
    if (booking) {
      if (!(await auto.flush())) return
      onClose()
      return
    }
    const saved = await form.submit(() =>
      financeApi.createBooking(orgId, payloadOf({ ...v, membership: member?.id ?? null })),
    )
    if (!saved) return
    if (einvoice) {
      try {
        await financeApi.uploadReceipt(orgId, (saved as Booking).id, einvoice.file)
      } catch (err) {
        setEinvoiceError(
          t('Gebucht, aber die E-Rechnung ist nicht angehängt: {x}. ', { x: errorMessage(err) }) +
            t('Bitte in der Buchung unter Belege erneut hinzufügen.'),
        )
        return
      }
    }
    onSaved(saved as Booking, again)
  }

  async function readEinvoice(file: File | undefined) {
    if (!file) return
    setEinvoiceError(null)
    try {
      const { einvoice: info, suggestion: s } = await financeApi.readEinvoice(orgId, file)
      if (s.date) set('date', s.date)
      set('amount', s.amount.replace('.', ','))
      set('counterparty', s.counterparty)
      set('reference', s.reference)
      set('text', s.text)
      setEinvoice({ file, info })
    } catch (err) {
      setEinvoice(null)
      setEinvoiceError(errorMessage(err))
    }
  }

  // Felder speichern automatisch; Schließen wartet nur auf die letzte Änderung
  async function close() {
    if (booking && canEdit && !(await auto.flush())) return
    onClose()
  }

  async function remove() {
    if (
      !booking ||
      !(await confirmDialog({
        title: t('Buchung {display_number} löschen?', { display_number: booking.display_number }),
        message: t('Löschen geht nur am Tag der Erfassung. Danach bitte stornieren.'),
        confirmLabel: t('Löschen'),
      }))
    )
      return
    const ok = await form.submit(() => financeApi.deleteBooking(orgId, booking.id))
    if (ok !== undefined) onClose()
  }

  async function storno() {
    if (!booking) return
    const reason = await promptDialog({
      title: t('Buchung {display_number} stornieren?', { display_number: booking.display_number }),
      message:
        t('Es entsteht eine Gegenbuchung mit heutigem Datum über denselben Betrag. Die Buchung ') +
        t('bleibt sichtbar und unverändert. Eine richtige Buchung legst du danach neu an.'),
      label: t('Grund'),
      confirmLabel: t('Stornieren'),
    })
    if (reason === null) return
    const saved = await form.submit(() => financeApi.stornoBooking(orgId, booking.id, reason))
    if (saved) onSaved(saved as Booking, false)
  }

  const title = booking
    ? t('{x} {display_number}', { x: KIND_LABEL[kind], display_number: booking.display_number })
    : t('Neue {x}', { x: KIND_LABEL[kind] })

  return (
    <div className="card card-wide">
      <form onSubmit={save}>
        <div className="card-head">
          <h2>{title}</h2>
          <button type="button" className="button button-ghost push-right" onClick={close}>
            {t('Schließen')}
          </button>
        </div>
        {booking?.cancelled_by && (
          <Alert kind="info">
            {t('Storniert durch Buchung {number} vom  {x}:', {
              number: booking.cancelled_by.number,
              x: formatDate(booking.cancelled_by.date),
            })}{' '}
            {booking.cancelled_by.reason}
          </Alert>
        )}
        {booking?.cancels && (
          <Alert kind="info">
            {t('Storno von Buchung {number}:', { number: booking.cancels.number })}{' '}
            {booking.cancel_reason}
          </Alert>
        )}
        {booking?.fixed && !booking.cancels && !booking.cancelled_by && (
          <>
            <Alert kind="info">
              {t(
                'Die Buchung ist festgeschrieben und lässt sich nicht mehr ändern. Ist sie falsch, bitte stornieren und neu buchen.',
              )}
            </Alert>
            <Why k="booking_fixed" />
          </>
        )}
        {!booking && kind === 'expense' && canEdit && (
          <div className="einvoice-read">
            <label className="button button-ghost file-button">
              {t('E-Rechnung einlesen (XML oder ZUGFeRD-PDF)')}
              <input
                type="file"
                accept=".xml,application/xml,text/xml,application/pdf"
                className="file-input"
                onChange={(e) => {
                  void readEinvoice(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </label>
            {einvoice && (
              <Alert kind="info">
                {t(
                  'E-Rechnung {number} von {seller} über  {x} gelesen. Bitte Konto und Kategorie wählen; die Datei wird beim Buchen als Beleg angehängt.',
                  {
                    number: einvoice.info.number,
                    seller: einvoice.info.seller,
                    x: euro(einvoice.info.payable),
                  },
                )}
              </Alert>
            )}
            {einvoiceError && <Alert kind="error">{einvoiceError}</Alert>}
            <p className="muted small">
              {t('Eine')} <Term k="e_invoice">{t('E-Rechnung')}</Term>{' '}
              {t('füllt die Buchung vor und wird unverändert als Beleg aufbewahrt.')}
            </p>
          </div>
        )}
        <fieldset disabled={readOnly || form.busy || locked}>
          <div className="grid-3">
            {booking && (
              <Field
                label={t('Buchungsnummer')}
                type="number"
                min={1}
                required
                value={v.number}
                error={errors.number}
                hint={t('Korrektur möglich, solange die Nummer frei ist')}
                onChange={(e) => set('number', e.target.value)}
              />
            )}
            <Field
              label={t('Datum')}
              type="date"
              required
              value={v.date}
              error={errors.date}
              onChange={(e) => set('date', e.target.value)}
            />
            <Field
              label={t('Betrag (€)')}
              inputMode="decimal"
              required
              placeholder="0,00"
              value={v.amount}
              error={errors.amount}
              onChange={(e) => set('amount', e.target.value)}
            />
            {kind !== 'transfer' && (
              <Field
                label={
                  kind === 'expense' ? t('Empfänger (Geschäft, Dienstleister …)') : t('Zahler')
                }
                list="booking-partner-suggestions"
                autoComplete="off"
                placeholder={
                  kind === 'expense' ? t('z. B. Getränkehandel') : t('z. B. Name oder Firma')
                }
                value={v.counterparty}
                error={errors.counterparty}
                onChange={(e) => set('counterparty', e.target.value)}
              />
            )}
            <SelectField
              label={kind === 'transfer' ? t('von Konto') : t('Konto')}
              value={v.account}
              error={errors.account}
              onChange={(e) => set('account', e.target.value)}
            >
              {activeAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </SelectField>
            {kind === 'transfer' ? (
              <SelectField
                label={t('auf Konto')}
                value={v.to_account}
                error={errors.to_account}
                onChange={(e) => set('to_account', e.target.value)}
              >
                <option value="">{t('bitte wählen')}</option>
                {activeAccounts
                  .filter((a) => String(a.id) !== v.account)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </SelectField>
            ) : (
              <SelectField
                label={t('Kategorie')}
                value={v.category}
                error={errors.category}
                onChange={(e) => set('category', e.target.value)}
              >
                <option value="">{t('bitte wählen')}</option>
                {usable.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </SelectField>
            )}
            <Field
              label={t('Buchungstext')}
              required
              value={v.text}
              error={errors.text}
              onChange={(e) => set('text', e.target.value)}
            />
            <Field
              label={t('Belegnummer/Referenz')}
              value={v.reference}
              error={errors.reference}
              onChange={(e) => set('reference', e.target.value)}
            />
          </div>
          {kind !== 'transfer' && usableProjects.length > 0 && !locked && (
            <div className="grid-2">
              <SelectField
                label={t('Veranstaltung (optional)')}
                value={v.project}
                error={errors.project}
                onChange={(e) => set('project', e.target.value)}
              >
                <option value="">keine</option>
                {usableProjects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </SelectField>
            </div>
          )}
          <datalist id="booking-partner-suggestions">
            {suggestions.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          {kind !== 'transfer' && isClub && (
            <details className="booking-assign" open={assignedOpen}>
              <summary>
                {t('Mitglied oder {sg} zuordnen', { sg: tm.sg })}{' '}
                <span className="muted">(optional)</span>
              </summary>
              <div className="grid-2">
                <MemberPicker orgId={orgId} value={member} onChange={pickMember} />
                {departments.length > 0 && (
                  <SelectField
                    label={t('{sg} (optional)', { sg: tm.sg })}
                    value={v.department}
                    onChange={(e) => set('department', e.target.value)}
                  >
                    <option value="">keine</option>
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {unitName(d)}
                      </option>
                    ))}
                  </SelectField>
                )}
              </div>
            </details>
          )}
          {usable.length === 0 && kind !== 'transfer' && (
            <Alert kind="info">
              {kind === 'income'
                ? t('Für Einnahmen gibt es noch keine Kategorie. Bitte unter')
                : t('Für Ausgaben gibt es noch keine Kategorie. Bitte unter')}{' '}
              <Link to="/finanzen/einstellungen/kategorien">
                {t('Finanzen → Einrichtung → Kategorien')}
              </Link>{' '}
              {t('anlegen.')}
            </Alert>
          )}
        </fieldset>
        {locked && canEdit && kind !== 'transfer' && usableProjects.length > 0 && (
          <div className="grid-2">
            <SelectField
              label={t('Veranstaltung (optional)')}
              value={v.project}
              error={errors.project}
              disabled={form.busy}
              onChange={(e) => set('project', e.target.value)}
            >
              <option value="">keine</option>
              {usableProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </SelectField>
          </div>
        )}
        {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
        {booking && canEdit && <SaveStatus auto={auto} />}
        {canEdit && (
          <div className="button-row">
            {!booking && (
              <button type="submit" className="button button-primary" disabled={form.busy}>
                {t('Buchen')}
              </button>
            )}
            {!booking && (
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={again}
                  onChange={(e) => setAgain(e.target.checked)}
                />
                <span>
                  {t('danach nächste')} {KIND_LABEL[kind]} erfassen
                </span>
              </label>
            )}
            {booking && !booking.cancels && !booking.cancelled_by && (
              <button
                type="button"
                className="button button-ghost push-right"
                disabled={form.busy}
                onClick={() => void storno()}
              >
                {t('Stornieren')}
              </button>
            )}
            {booking?.deletable && (
              <button type="button" className="button button-danger" onClick={remove}>
                {t('Löschen')}
              </button>
            )}
          </div>
        )}
      </form>
      {booking ? (
        <Receipts orgId={orgId} booking={booking} canEdit={canEdit} />
      ) : (
        <p className="muted small">{t('Belege kannst du nach dem Speichern anhängen.')}</p>
      )}
    </div>
  )
}

/** Vor weniger als 15 Minuten hochgeladen: darf noch gelöscht werden (sonst ausblenden). */
function justUploaded(createdAt: string): boolean {
  return Date.now() - Date.parse(createdAt) < 15 * 60 * 1000
}

function Receipts({
  orgId,
  booking,
  canEdit,
}: {
  orgId: number
  booking: Booking
  canEdit: boolean
}) {
  const [items, setItems] = useState(booking.receipts)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function upload(files: FileList | null) {
    if (!files?.length) return
    setBusy(true)
    setError(null)
    // Jede Datei einzeln: Gespeichertes sofort zeigen, Fehler je Datei nennen
    const list = Array.from(files)
    const failed: string[] = []
    let done = 0
    for (const file of list) {
      try {
        const receipt = await financeApi.uploadReceipt(orgId, booking.id, file)
        setItems((prev) => [...prev, receipt])
        done++
      } catch (err) {
        failed.push(t('{name}: {x}', { name: file.name, x: errorMessage(err) }))
      }
    }
    if (failed.length) {
      setError(
        (list.length > 1
          ? t('{done} von {n} Belegen hochgeladen. ', { done, n: list.length })
          : '') + t('Nicht hochgeladen – bitte erneut auswählen: {x}', { x: failed.join('; ') }),
      )
    }
    setBusy(false)
  }

  async function hide(id: number) {
    const reason = await promptDialog({
      title: t('Beleg ausblenden?'),
      message:
        t(
          'Belege werden aufbewahrt (§ 147 AO) und nicht gelöscht. Der Beleg verschwindet aus der ',
        ) + t('Liste „mit Beleg“, bleibt aber gespeichert und steht im Datenexport.'),
      label: t('Grund'),
      confirmLabel: t('Ausblenden'),
    })
    if (reason === null) return
    try {
      const hidden = (await financeApi.deleteReceipt(orgId, id, reason)) as Receipt
      setItems((prev) => prev.map((r) => (r.id === id ? hidden : r)))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove(r: Receipt) {
    setError(null)
    // Gerade hochgeladen: löschen (Fehlgriff); sonst nur ausblenden
    const recent = justUploaded(r.created_at) && !booking.fixed
    if (!recent) return hide(r.id)
    if (!(await confirmDialog({ title: t('Beleg entfernen?'), confirmLabel: t('Entfernen') })))
      return
    try {
      await financeApi.deleteReceipt(orgId, r.id)
      setItems((prev) => prev.filter((x) => x.id !== r.id))
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) return hide(r.id)
      setError(errorMessage(err))
    }
  }

  return (
    <div className="subcard">
      <h3>{t('Belege')}</h3>
      <Why k="receipts" />
      {items.length === 0 ? (
        <p className="muted small">{t('Noch kein Beleg.')}</p>
      ) : (
        <ul className="plain-list">
          {items.map((r) => (
            <li key={r.id} className={r.hidden_at ? 'muted' : undefined}>
              <a href={financeApi.receiptUrl(orgId, r.id)} target="_blank" rel="noreferrer">
                📎 {r.name}
              </a>{' '}
              <span className="muted small">({Math.ceil(r.size / 1024)} KB)</span>
              {r.einvoice?.number && (
                <span className="small">
                  {' '}
                  {t('· E-Rechnung')} {r.einvoice.number}
                  {r.einvoice.seller ? t(' von {seller}', { seller: r.einvoice.seller }) : ''}
                  {r.einvoice.payable ? t(' über {x}', { x: euro(r.einvoice.payable) }) : ''}
                  {r.content_type === 'application/xml' && (
                    <>
                      {' '}
                      <a
                        href={financeApi.receiptViewUrl(orgId, r.id)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t('lesbare Ansicht')}
                      </a>
                    </>
                  )}
                </span>
              )}
              {r.hidden_at ? (
                <span className="small">
                  {' '}
                  {t('– ausgeblendet:')} {r.hidden_reason}
                </span>
              ) : (
                canEdit && (
                  <button type="button" className="link-button" onClick={() => void remove(r)}>
                    entfernen
                  </button>
                )
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <label className="button button-ghost file-button">
          {busy ? t('Lädt hoch …') : t('Foto, PDF oder E-Rechnung hinzufügen')}
          <input
            type="file"
            accept="application/pdf,image/*,.xml,application/xml,text/xml"
            multiple
            className="file-input"
            disabled={busy}
            onChange={(e) => {
              void upload(e.target.files)
              e.target.value = ''
            }}
          />
        </label>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
