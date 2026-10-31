// Zuwendungsbestätigungen (Spendenbescheinigungen) nach amtlichem Muster.
// Für Einheiten mit Kasse; ausgestellt wird nur mit Schalter „steuerbegünstigt mit
// eigenem Bescheid“ und gültigem Bescheid. Regeln im Backend
// (finance/donations.py).
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Route, Routes } from 'react-router-dom'
import { donationApi } from '../../api/donations.ts'
import type {
  Donation,
  DonationInput,
  DonationKind,
  DonationSettings,
  GoodsOrigin,
} from '../../api/donations.ts'
import { ApiError } from '../../api/client.ts'
import { euro, parseAmount } from '../../api/finance.ts'
import type { MemberRow } from '../../api/members.ts'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { Alert, Checkbox, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { RangePager } from '../../components/ListControls.tsx'
import { confirmDiscard, useChangesGuard } from '../../components/leaveGuard.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { Term, Why } from '../../learning/Aids.tsx'
import { Checklist } from '../../learning/Checklist.tsx'
import { donationChecks } from '../../learning/checks.ts'

const KIND_LABEL: Record<DonationKind, string> = {
  money: 'Geldzuwendung',
  fee: 'Mitgliedsbeitrag',
  goods: 'Sachzuwendung',
}

const ORIGIN_LABEL: Record<Exclude<GoodsOrigin, ''>, string> = {
  private: 'aus dem Privatvermögen',
  business: 'aus dem Betriebsvermögen',
  unknown: 'keine Angaben trotz Nachfrage',
}

function thisYear() {
  return new Date().getFullYear()
}

/** Heutiges Datum in Ortszeit (nicht UTC), auch kurz nach Mitternacht (UX-Audit 31.10. N09) */
function today() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Jahre für die Auswahl: alle mit Daten, dazu das laufende und das gewählte (UX-Audit 31.10. N01) */
function yearOptions(withData: number[] | null, selected: number): number[] {
  const all = new Set<number>([thisYear(), selected, ...(withData ?? [])])
  if (!withData) for (let i = 1; i < 6; i++) all.add(thisYear() - i)
  return [...all].sort((a, b) => b - a)
}

const PAGE_SIZE = 100

/** „1–100 von 340“ mit Blättern; nichts, wenn alles auf eine Seite passt */
function PageNav({
  page,
  count,
  onPage,
  noun,
}: {
  page: number
  count: number
  onPage: (p: number) => void
  noun: string
}) {
  return <RangePager page={page} size={PAGE_SIZE} total={count} onPage={onPage} noun={noun} />
}

// Felder mit eigener Fehleranzeige im Formular; alle anderen Fehler stehen gesammelt darunter
const SHOWN_FIELDS = new Set([
  'kind',
  'date',
  'amount',
  'donor_name',
  'goods_description',
  'goods_origin',
])

function fieldErrors(err: unknown): Record<string, string> {
  return err instanceof ApiError ? err.fieldErrors : {}
}

export function DonationsArea({ canEdit }: { canEdit: boolean }) {
  return (
    <Routes>
      <Route index element={<DonationsList canEdit={canEdit} />} />
      <Route path="bestaetigungen" element={<StatementsList canEdit={canEdit} />} />
      <Route path="einstellungen" element={<DonationSettingsForm canEdit={canEdit} />} />
    </Routes>
  )
}

// --- Zuwendungen ---

function DonationsList({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const [year, setYear] = useState(thisYear())
  const [onlyOpen, setOnlyOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<Donation | 'new' | null>(null)
  const [editDirty, setEditDirty] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const settings = useLoad(() => donationApi.settings(org.id), [org.id])
  const years = useLoad(() => donationApi.years(org.id).catch(() => null), [org.id])
  const list = useLoad(
    () =>
      donationApi.list(org.id, { jahr: year, offen: onlyOpen, page: page > 1 ? page : undefined }),
    [org.id, year, onlyOpen, page],
  )
  // Zahlen für die Prüfliste (blockiert nie)
  const checks = useLoad(
    () => donationApi.checks(org.id, year).catch(() => null),
    [org.id, year, list.data],
  )
  // Ohne geladene Einstellungen ist nicht bekannt, ob Ausstellen möglich ist (UX-Audit 31.10. N05)
  const problems = settings.data?.problems ?? []
  const settingsReady = !!settings.data

  /** Anderen Eintrag öffnen, ohne ungespeicherte Eingaben still zu ersetzen (W01) */
  async function edit(next: Donation | 'new') {
    if (editing !== null && !(await confirmDiscard(editDirty))) return
    setEditDirty(false)
    setEditing(next)
  }

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setMessage(null)
    try {
      setMessage({ kind: 'success', text: await action() })
      setSelected([])
      await list.reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function importBookings() {
    await run(async () => {
      const { created } = await donationApi.importBookings(org.id, year)
      return created
        ? `${created} Einnahmen aus Spenden-Kategorien übernommen.`
        : `Keine neuen Einnahmen ${year} in Kategorien mit Kennzeichen „Spenden“.`
    })
  }

  async function issueSelected() {
    const signer = await promptDialog({
      title: 'Zuwendungsbestätigung ausstellen',
      message:
        'Mehrere Zuwendungen eines Zuwendenden aus einem Jahr ergeben eine Sammelbestätigung. Das PDF wird als Doppel gespeichert.',
      label: 'Unterschrift durch (Name)',
      confirmLabel: 'Ausstellen',
    })
    if (signer === null) return
    await run(async () => {
      const st = await donationApi.issue(org.id, selected, signer)
      return `Bestätigung ${st.number} für ${st.donor_name} ausgestellt.`
    })
  }

  async function yearEnd() {
    // Vorschau kontrolliert laden: Fehler sichtbar, Knopf gesperrt (UX-Audit 31.10. N05)
    setBusy(true)
    setMessage(null)
    let preview
    try {
      preview = await donationApi.yearEnd(org.id, year)
    } catch (err) {
      setMessage({
        kind: 'error',
        text: `Die Vorschau konnte nicht geladen werden (${errorMessage(err)}). Bitte erneut versuchen.`,
      })
      return
    } finally {
      setBusy(false)
    }
    if (preview.problems.length > 0) {
      setMessage({
        kind: 'error',
        text: `Noch keine Bestätigungen möglich: ${preview.problems.join(' ')} Bitte unter „Einstellungen“ ergänzen.`,
      })
      await settings.reload()
      return
    }
    // Ohne vollständigen Namen und Anschrift wird nicht bestätigt (Audit 31.10., Fachfrage 5)
    const ready = preview.donors.filter((d) => !d.incomplete)
    const missing = preview.donors.filter((d) => d.incomplete)
    const missingText =
      missing.length > 0
        ? ` Noch offen, weil Angaben fehlen: ${missing.map((d) => `${d.donor_name} (${d.incomplete})`).join(', ')}.`
        : ''
    if (ready.length === 0) {
      setMessage(
        missing.length > 0
          ? { kind: 'error', text: `Keine Bestätigung möglich.${missingText}` }
          : { kind: 'success', text: `Für ${year} sind alle Geldzuwendungen bestätigt.` },
      )
      return
    }
    const sum = ready.reduce((s, d) => s + Number(d.total), 0)
    const signer = await promptDialog({
      title: `Bestätigungen für ${year} ausstellen?`,
      message: `${ready.length} Zuwendende, zusammen ${euro(sum)}. Je Zuwendendem eine Bestätigung (bei mehreren Zuwendungen eine Sammelbestätigung). Sachzuwendungen bleiben offen und werden einzeln bestätigt.${missingText}`,
      label: 'Unterschrift durch (Name)',
      confirmLabel: 'Alle ausstellen',
    })
    if (signer === null) return
    await run(async () => {
      const { created } = await donationApi.issueYearEnd(org.id, year, signer)
      return `${created} Bestätigungen ausgestellt. Sie stehen unter „Bestätigungen“.`
    })
  }

  async function remove(d: Donation) {
    const ok = await confirmDialog({
      title: 'Zuwendung löschen?',
      message: `${euro(d.amount)} von ${d.donor_name} am ${formatDate(d.date)}`,
      confirmLabel: 'Löschen',
      danger: true,
    })
    if (ok) await run(async () => (await donationApi.remove(org.id, d.id), 'Gelöscht.'))
  }

  const count = list.data?.count ?? 0

  const rows = list.data?.results ?? []
  const openRows = rows.filter((d) => !d.statement)
  const toggle = (id: number, on: boolean) =>
    setSelected((s) => (on ? [...s, id] : s.filter((x) => x !== id)))

  return (
    <div className="card card-wide">
      {settings.error && (
        <LoadError
          message={`Die Angaben zur Steuerbegünstigung konnten nicht geladen werden (${settings.error}). Ausstellen ist erst danach möglich.`}
          onRetry={() => void settings.reload()}
        />
      )}
      {problems.length > 0 && (
        <Alert kind="info">
          Noch keine Bestätigungen möglich: {problems.join(' ')} Bitte unter „Einstellungen“
          ergänzen.
        </Alert>
      )}
      <div className="filters">
        <SelectField
          label="Jahr"
          value={year}
          onChange={(e) => {
            setYear(Number(e.target.value))
            setPage(1)
            setSelected([])
          }}
        >
          {yearOptions(years.data, year).map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </SelectField>
        <Checkbox
          label="nur noch nicht bestätigte"
          checked={onlyOpen}
          onChange={(on) => {
            setOnlyOpen(on)
            setPage(1)
          }}
        />
      </div>
      {canEdit && editing === null && (
        <div className="button-row">
          <button type="button" className="button button-primary" onClick={() => void edit('new')}>
            Zuwendung erfassen
          </button>
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={importBookings}
          >
            Aus dem Kassenbuch übernehmen
          </button>
          <button
            type="button"
            className="button button-ghost"
            disabled={busy || !settingsReady || problems.length > 0}
            onClick={yearEnd}
          >
            Jahresende: alle bestätigen
          </button>
          {selected.length > 0 && (
            <button
              type="button"
              className="button button-primary"
              disabled={busy || !settingsReady || problems.length > 0}
              onClick={issueSelected}
            >
              {selected.length === 1 ? 'Bestätigung ausstellen' : 'Sammelbestätigung ausstellen'}
            </button>
          )}
        </div>
      )}
      <p className="muted small">
        Übernehmen holt Einnahmen aus Kategorien mit dem Kennzeichen „Spenden“ (Finanzen ›
        Einrichtung › Kategorien). Name und Anschrift kommen aus dem Mitglied oder dem Zahler. Bis
        300 € genügt dem Spender oft der{' '}
        <Term k="simplified_proof">vereinfachte Zuwendungsnachweis</Term>.
      </p>
      <div className="aid-row">
        <Why k="donation_year_end" />
        <Why k="donation_liability" />
      </div>
      {canEdit && checks.data && (
        <Checklist
          title={`Vor den Jahresbestätigungen ${year}`}
          items={donationChecks({ problems, ...checks.data })}
        />
      )}
      {editing !== null && (
        <DonationForm
          key={editing === 'new' ? 'new' : editing.id}
          initial={editing === 'new' ? null : editing}
          settings={settings.data}
          onDirty={setEditDirty}
          onCancel={() => {
            setEditDirty(false)
            setEditing(null)
          }}
          onDone={async (text) => {
            setEditDirty(false)
            setEditing(null)
            setMessage({ kind: 'success', text })
            await list.reload()
          }}
        />
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {list.error && <LoadError message={list.error} onRetry={() => void list.reload()} />}
      {!list.data ? (
        !list.error && <p className="muted">Lädt …</p>
      ) : rows.length === 0 ? (
        <p className="muted">Keine Zuwendungen {year}.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              {canEdit && <th aria-label="Auswahl" />}
              <th>Datum</th>
              <th>Zuwendender</th>
              <th>Art</th>
              <th className="num">Betrag</th>
              <th>Bestätigung</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                {canEdit && (
                  <td>
                    {!d.statement && (
                      <input
                        type="checkbox"
                        aria-label={`${d.donor_name} ${formatDate(d.date)} auswählen`}
                        checked={selected.includes(d.id)}
                        onChange={(e) => toggle(d.id, e.target.checked)}
                      />
                    )}
                  </td>
                )}
                <td>{formatDate(d.date)}</td>
                <td>
                  <strong>{d.donor_name}</strong>
                  {d.booking_number && (
                    <span className="muted small"> · Buchung {d.booking_number}</span>
                  )}
                </td>
                <td>
                  {d.kind_label}
                  {d.waiver && (
                    <span className="muted small"> · Verzicht auf Aufwendungsersatz</span>
                  )}
                </td>
                <td className="num">{euro(d.amount)}</td>
                <td>{d.statement_number ?? <span className="muted">offen</span>}</td>
                <td className="actions">
                  {canEdit && !d.statement && (
                    <>
                      <button type="button" className="link-button" onClick={() => void edit(d)}>
                        Ändern
                      </button>{' '}
                      <button type="button" className="link-button" onClick={() => void remove(d)}>
                        Löschen
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <PageNav page={page} count={count} onPage={setPage} noun="Zuwendungen" />
      {canEdit && openRows.length > 1 && selected.length === 0 && (
        <p className="muted small">
          Mehrere Zuwendungen eines Zuwendenden ankreuzen ergibt eine Sammelbestätigung.
        </p>
      )}
    </div>
  )
}

function DonationForm({
  initial,
  settings,
  onDirty,
  onCancel,
  onDone,
}: {
  initial: Donation | null
  settings: DonationSettings | null
  onDirty: (dirty: boolean) => void
  onCancel: () => void
  onDone: (text: string) => Promise<void>
}) {
  const org = useActiveOrg()
  const [v, setV] = useState<Partial<DonationInput>>(
    initial ?? {
      date: today(),
      kind: 'money',
      waiver: false,
      membership: null,
      donor_name: '',
      donor_address: '',
      goods_description: '',
      goods_origin: '',
      goods_documents: false,
      note: '',
    },
  )
  const [amountText, setAmountText] = useState(initial ? initial.amount.replace('.', ',') : '')
  const [member, setMember] = useState<MemberRow | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof DonationInput>(k: K, value: DonationInput[K]) =>
    setV((old) => ({ ...old, [k]: value }))
  const goods = v.kind === 'goods'
  // Ungespeicherte Eingaben schützen (UX-Audit 31.10. W01)
  const [saved, setSaved] = useState(false)
  const { dirty } = useChangesGuard([v, amountText], !saved)
  useEffect(() => onDirty(dirty), [dirty, onDirty])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    setFailure(null)
    const data = { ...v, amount: parseAmount(amountText) }
    try {
      if (initial) await donationApi.update(org.id, initial.id, data)
      else await donationApi.create(org.id, data)
      setSaved(true)
      await onDone(initial ? 'Zuwendung geändert.' : 'Zuwendung erfasst.')
    } catch (err) {
      setErrors(fieldErrors(err))
      setFailure(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="subcard" onSubmit={submit}>
      <h3>{initial ? 'Zuwendung ändern' : 'Zuwendung erfassen'}</h3>
      <div className="grid-3">
        <SelectField
          label="Art"
          value={v.kind}
          onChange={(e) => {
            const kind = e.target.value as DonationKind
            // Verzicht gibt es nur bei Geld: beim Wechsel zur Sache mit abschalten (N04)
            setV((old) => ({ ...old, kind, waiver: kind === 'goods' ? false : old.waiver }))
          }}
          error={errors.kind}
        >
          <option value="money">{KIND_LABEL.money}</option>
          {(settings?.fees_allowed || v.kind === 'fee') && (
            <option value="fee">{KIND_LABEL.fee}</option>
          )}
          <option value="goods">{KIND_LABEL.goods}</option>
        </SelectField>
        <Field
          label="Tag der Zuwendung"
          type="date"
          value={v.date ?? ''}
          onChange={(e) => set('date', e.target.value)}
          error={errors.date}
          required
        />
        <Field
          label={goods ? 'Wert in €' : 'Betrag in €'}
          inputMode="decimal"
          value={amountText}
          onChange={(e) => setAmountText(e.target.value)}
          error={errors.amount}
          required
        />
      </div>
      {!initial && (
        <MemberPicker
          orgId={org.id}
          value={member}
          onChange={(m) => {
            setMember(m)
            set('membership', m?.id ?? null)
            // Name und Anschrift ergänzt der Server aus dem Mitglied
            if (m) setV((old) => ({ ...old, membership: m.id, donor_name: '', donor_address: '' }))
          }}
          label="Mitglied (optional)"
        />
      )}
      {!member && (
        <div className="grid-2">
          <Field
            label="Name des Zuwendenden"
            value={v.donor_name ?? ''}
            onChange={(e) => set('donor_name', e.target.value)}
            error={errors.donor_name}
            maxLength={200}
            required={!v.membership}
          />
          <label className="field">
            <span>Anschrift</span>
            <textarea
              rows={2}
              value={v.donor_address ?? ''}
              maxLength={500}
              onChange={(e) => set('donor_address', e.target.value)}
            />
          </label>
        </div>
      )}
      {goods ? (
        <>
          <label className={`field${errors.goods_description ? ' field-invalid' : ''}`}>
            <span>Genaue Bezeichnung der Sache (Alter, Zustand, Kaufpreis)</span>
            <textarea
              rows={2}
              value={v.goods_description ?? ''}
              maxLength={1000}
              onChange={(e) => set('goods_description', e.target.value)}
            />
            {errors.goods_description && (
              <small className="field-error">{errors.goods_description}</small>
            )}
          </label>
          <SelectField
            label="Herkunft"
            value={v.goods_origin ?? ''}
            onChange={(e) => set('goods_origin', e.target.value as GoodsOrigin)}
            error={errors.goods_origin}
          >
            <option value="">bitte wählen</option>
            {Object.entries(ORIGIN_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </SelectField>
          <Checkbox
            label="Unterlagen zur Wertermittlung liegen vor (z. B. Rechnung, Gutachten)"
            checked={!!v.goods_documents}
            onChange={(on) => set('goods_documents', on)}
          />
          <Why k="donation_goods" />
        </>
      ) : (
        <Checkbox
          label="Verzicht auf Erstattung von Aufwendungen"
          hint="z. B. Fahrtkosten, auf deren Erstattung jemand verzichtet"
          checked={!!v.waiver}
          onChange={(on) => set('waiver', on)}
        />
      )}
      {!goods && (
        <>
          <p className="muted small">
            Ein solcher Verzicht ist eine <Term k="expense_donation">Aufwandsspende</Term>.
          </p>
          <Why k="donation_waiver" />
        </>
      )}
      <Field
        label="Notiz (nur intern)"
        value={v.note ?? ''}
        maxLength={300}
        onChange={(e) => set('note', e.target.value)}
      />
      {failure && <Alert kind="error">{failure}</Alert>}
      {Object.entries(errors)
        .filter(([key]) => !SHOWN_FIELDS.has(key))
        .map(([key, text]) => (
          // Fehler ohne sichtbares Feld trotzdem zeigen (UX-Audit 31.10. N04)
          <Alert key={key} kind="error">
            {text}
          </Alert>
        ))}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={busy}>
          Speichern
        </button>
        <button
          type="button"
          className="button button-ghost"
          onClick={() => void confirmDiscard(dirty).then((ok) => ok && onCancel())}
        >
          Abbrechen
        </button>
      </div>
    </form>
  )
}

// --- Bestätigungen ---

function StatementsList({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const [year, setYear] = useState(thisYear())
  const [page, setPage] = useState(1)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const years = useLoad(() => donationApi.statementYears(org.id).catch(() => null), [org.id])
  const list = useLoad(
    () => donationApi.statements(org.id, { jahr: year, page: page > 1 ? page : undefined }),
    [org.id, year, page],
  )

  async function cancel(id: number, number: string) {
    const reason = await promptDialog({
      title: `Bestätigung ${number} stornieren?`,
      message:
        'Das Doppel bleibt gespeichert, die Zuwendungen werden wieder frei. Bitte das Original vom Zuwendenden zurückfordern.',
      label: 'Grund',
      confirmLabel: 'Stornieren',
      danger: true,
    })
    if (reason === null) return
    try {
      await donationApi.cancel(org.id, id, reason)
      setMessage({ kind: 'success', text: `${number} storniert.` })
      await list.reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const rows = list.data?.results ?? []
  return (
    <div className="card card-wide">
      <div className="filters">
        <SelectField
          label="Ausgestellt"
          value={year}
          onChange={(e) => {
            setYear(Number(e.target.value))
            setPage(1)
          }}
        >
          {yearOptions(years.data, year).map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </SelectField>
      </div>
      <p className="muted small">
        Jede <Term k="donation_receipt">Zuwendungsbestätigung</Term> wird als Doppel gespeichert (§
        50 Abs. 7 EStDV) und lässt sich jederzeit wieder herunterladen. Fehlerhafte Bestätigungen
        stornieren und neu ausstellen.
      </p>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {list.error && <LoadError message={list.error} onRetry={() => void list.reload()} />}
      {!list.data ? (
        !list.error && <p className="muted">Lädt …</p>
      ) : rows.length === 0 ? (
        <p className="muted">Keine Bestätigungen {year}.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Nummer</th>
              <th>ausgestellt</th>
              <th>Zuwendender</th>
              <th>Art</th>
              <th className="num">Betrag</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className={s.cancelled_at ? 'muted' : undefined}>
                <td>
                  <strong>{s.number}</strong>
                  {s.cancelled_at && (
                    <span className="field-error small"> · storniert ({s.cancel_reason})</span>
                  )}
                </td>
                <td>{formatDate(s.issued_on)}</td>
                <td>{s.donor_name}</td>
                <td>{s.goods ? 'Sachzuwendung' : s.kind_label}</td>
                <td className="num">{euro(s.total)}</td>
                <td className="actions">
                  <a href={donationApi.pdfUrl(org.id, s.id)} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                  {canEdit && !s.cancelled_at && (
                    <>
                      {' '}
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => void cancel(s.id, s.number)}
                      >
                        Stornieren
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <PageNav page={page} count={list.data?.count ?? 0} onPage={setPage} noun="Bestätigungen" />
    </div>
  )
}

// --- Einstellungen ---

function DonationSettingsForm({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const load = useLoad(() => donationApi.settings(org.id), [org.id])
  if (load.error) return <LoadError message={load.error} onRetry={() => void load.reload()} />
  if (!load.data) return <p className="muted">Lädt …</p>
  return <SettingsEditor key={org.id} initial={load.data} canEdit={canEdit} />
}

function SettingsEditor({ initial, canEdit }: { initial: DonationSettings; canEdit: boolean }) {
  const org = useActiveOrg()
  const [v, setV] = useState(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof DonationSettings>(k: K, value: DonationSettings[K]) =>
    setV((old) => ({ ...old, [k]: value }))
  const exemption = v.notice === 'exemption'
  // Ungespeicherte Angaben schützen (UX-Audit 31.10. W01)
  const guard = useChangesGuard(v, canEdit)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    setMessage(null)
    try {
      const saved = await donationApi.saveSettings(org.id, {
        purposes: v.purposes,
        notice: v.notice,
        tax_office: v.tax_office,
        tax_number: v.tax_number,
        notice_date: v.notice_date || null,
        assessment_period: v.assessment_period,
        fees_allowed: v.fees_allowed,
        place: v.place,
      })
      setV(saved)
      guard.markSaved()
      setMessage({ kind: 'success', text: 'Gespeichert.' })
    } catch (err) {
      setErrors(fieldErrors(err))
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card card-wide" onSubmit={submit}>
      <h2>Angaben zur Steuerbegünstigung</h2>
      <p className="muted small">
        Diese Angaben stehen auf jeder Bestätigung. Sie stammen aus dem letzten Bescheid des
        Finanzamts. Ein <Term k="exemption_notice">Freistellungsbescheid</Term> reicht 5 Jahre, eine{' '}
        <Term k="statute_notice">Feststellung nach § 60a AO</Term> 3 Jahre (§ 63 Abs. 5 AO); danach
        stellt HUBIplan keine Bestätigungen mehr aus.
      </p>
      <Why k="donation_notice" />
      {v.problems.length > 0 ? (
        <Alert kind="info">{v.problems.join(' ')}</Alert>
      ) : (
        v.valid_until && (
          <Alert kind="success">
            Bestätigungen möglich bis {formatDate(v.valid_until)} (danach neuen Bescheid eintragen).
          </Alert>
        )
      )}
      <fieldset disabled={!canEdit}>
        <Checkbox
          label="Steuerbegünstigt mit eigenem Bescheid des Finanzamts"
          hint="gilt auch für nicht eingetragene Vereine; unselbständige Untereinheiten haben meist keinen eigenen Bescheid"
          checked={v.enabled}
          onChange={(on) => set('enabled', on)}
        />
        <Why k="donation_enabled" />
        <SelectField
          label="Art des Bescheids"
          value={v.notice}
          onChange={(e) => set('notice', e.target.value as DonationSettings['notice'])}
        >
          <option value="exemption">
            Freistellungsbescheid bzw. Anlage zum Körperschaftsteuerbescheid
          </option>
          <option value="statute">
            Feststellung der Satzungsmäßigkeit nach § 60a AO (neu gegründet)
          </option>
        </SelectField>
        <label className={`field${errors.purposes ? ' field-invalid' : ''}`}>
          <span>Begünstigte Zwecke (wie im Bescheid)</span>
          <textarea
            rows={2}
            value={v.purposes}
            maxLength={1000}
            placeholder="z. B. des traditionellen Brauchtums einschließlich des Schützenwesens"
            onChange={(e) => set('purposes', e.target.value)}
          />
          <small className="muted">
            Steht im Satz „Wir sind wegen Förderung … befreit“ und „nur zur Förderung … verwendet“.
          </small>
        </label>
        <div className="grid-3">
          <Field
            label="Finanzamt"
            value={v.tax_office}
            onChange={(e) => set('tax_office', e.target.value)}
            error={errors.tax_office}
            maxLength={200}
          />
          <Field
            label="Steuernummer"
            value={v.tax_number}
            onChange={(e) => set('tax_number', e.target.value)}
            error={errors.tax_number}
            maxLength={50}
          />
          <Field
            label="Datum des Bescheids"
            type="date"
            value={v.notice_date ?? ''}
            onChange={(e) => set('notice_date', e.target.value || null)}
            error={errors.notice_date}
          />
        </div>
        <div className="grid-2">
          {exemption && (
            <Field
              label="Letzter Veranlagungszeitraum"
              value={v.assessment_period}
              placeholder="z. B. 2022 bis 2024"
              onChange={(e) => set('assessment_period', e.target.value)}
              error={errors.assessment_period}
              maxLength={50}
            />
          )}
          <Field
            label="Ort der Ausstellung"
            value={v.place}
            onChange={(e) => set('place', e.target.value)}
            maxLength={100}
          />
        </div>
        <Checkbox
          label="Auch Mitgliedsbeiträge bestätigen"
          hint="nur, wenn die Beiträge abziehbar sind; bei Sport-, Heimat- und Brauchtumsvereinen meist nicht (§ 10b Abs. 1 Satz 8 EStG)"
          checked={v.fees_allowed}
          onChange={(on) => set('fees_allowed', on)}
        />
      </fieldset>
      <Why k="donation_fees" />
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {canEdit && (
        <div className="button-row">
          <button type="submit" className="button button-primary" disabled={busy}>
            Speichern
          </button>
        </div>
      )}
    </form>
  )
}
