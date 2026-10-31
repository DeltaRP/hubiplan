// Kontoauszüge (CAMT.053) einlesen und Umsätze zuordnen. Regeln für die Vorschläge
// stehen im Backend (finance/bank_import.py).
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { bankApi } from '../../api/bank.ts'
import type { BankLine, BankLineStatus, BankStatement } from '../../api/bank.ts'
import { euro, financeApi } from '../../api/finance.ts'
import type { Account, Category } from '../../api/finance.ts'
import type { MemberRow } from '../../api/members.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { Alert, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { RangePager } from '../../components/ListControls.tsx'
import { confirmDiscard, useChangesGuard } from '../../components/leaveGuard.ts'
import { billingApi } from '../../api/billing.ts'
import type { InvoiceRow } from '../../api/billing.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { HowTo, Term } from '../../learning/Aids.tsx'

type Message = { kind: 'success' | 'error'; text: string } | null

export function BankStatementsPage({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const [statementPage, setStatementPage] = useState(1)
  const statements = useLoad(
    () => bankApi.statements(org.id, statementPage),
    [org.id, statementPage],
  )
  const accounts = useLoad(() => financeApi.accounts(org.id), [org.id])
  const categories = useLoad(() => financeApi.categories(org.id), [org.id])
  const [selected, setSelected] = useState<number | null>(null)
  const [message, setMessage] = useState<Message>(null)
  const list = statements.data?.results ?? []
  const current = list.find((s) => s.id === selected) ?? list[0] ?? null

  async function removeStatement(st: BankStatement) {
    const ok = await confirmDialog({
      title: 'Kontoauszug entfernen?',
      message: `${st.file_name}: Die ${st.line_count} Umsätze werden entfernt. Das geht nur, solange nichts daraus gebucht ist.`,
      confirmLabel: 'Entfernen',
      danger: true,
    })
    if (!ok) return
    try {
      await bankApi.removeStatement(org.id, st.id)
      setSelected(null)
      await statements.reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <>
      {canEdit && accounts.data && (
        <UploadForm
          accounts={accounts.data.filter((a) => a.is_active && a.kind !== 'cash')}
          onDone={async (text, first) => {
            setMessage({ kind: 'success', text })
            await statements.reload()
            if (first) setSelected(first)
          }}
        />
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {statements.error && (
        <LoadError message={statements.error} onRetry={() => void statements.reload()} />
      )}
      {!statements.data ? (
        !statements.error && <p className="muted">Lädt …</p>
      ) : list.length === 0 ? (
        <p className="muted">Noch keine Kontoauszüge eingelesen.</p>
      ) : (
        <div className="card card-wide">
          <h2>Eingelesene Auszüge</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Auszug</th>
                <th>Konto</th>
                <th>Zeitraum</th>
                <th className="num">Umsätze</th>
                <th className="num">offen</th>
                <th>Saldo</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((st) => (
                <tr key={st.id} className={current?.id === st.id ? 'row-selected' : undefined}>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setSelected(st.id)}
                    >
                      {st.reference || st.file_name}
                    </button>
                    {st.duplicate_count > 0 && (
                      <span className="muted small"> · {st.duplicate_count} schon eingelesen</span>
                    )}
                  </td>
                  <td>{st.account_name}</td>
                  <td>
                    {formatDate(st.date_from)} – {formatDate(st.date_to)}
                  </td>
                  <td className="num">{st.line_count}</td>
                  <td className="num">{st.open_count}</td>
                  <td>
                    {st.balance ? (
                      st.balance.ok ? (
                        <span>stimmt ({euro(st.balance.bank)})</span>
                      ) : (
                        <span className="field-error">
                          Bank {euro(st.balance.bank)}, Kassenbuch {euro(st.balance.book)}
                        </span>
                      )
                    ) : (
                      '–'
                    )}
                  </td>
                  <td className="actions">
                    {canEdit && (
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => void removeStatement(st)}
                      >
                        Entfernen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* Alle Auszüge erreichbar, nicht nur die neuesten 50 (UX-Audit 31.10. N01) */}
          <RangePager
            page={statementPage}
            size={50}
            total={statements.data.count}
            onPage={(p) => {
              setStatementPage(p)
              setSelected(null)
            }}
            noun="Auszügen"
          />
        </div>
      )}
      {current && (
        <LinesCard
          key={current.id}
          statement={current}
          canEdit={canEdit}
          categories={categories.data ?? []}
          onChanged={() => void statements.reload()}
        />
      )}
    </>
  )
}

function UploadForm({
  accounts,
  onDone,
}: {
  accounts: Account[]
  onDone: (text: string, firstId: number | null) => Promise<void>
}) {
  const org = useActiveOrg()
  const [file, setFile] = useState<File | null>(null)
  const [account, setAccount] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [inputKey, setInputKey] = useState(0)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const r = await bankApi.upload(org.id, file, account)
      const dup = r.duplicates ? ` ${r.duplicates} waren schon eingelesen.` : ''
      setFile(null)
      setInputKey((k) => k + 1)
      await onDone(`${r.lines} Umsätze eingelesen.${dup}`, r.statements[0]?.id ?? null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card card-wide" onSubmit={submit}>
      <h2>Kontoauszug einlesen</h2>
      <p className="muted small">
        Im Online-Banking die Umsätze als{' '}
        <strong>
          <Term k="camt">CAMT.053</Term>
        </strong>{' '}
        (auch „CAMT-Export“, XML oder ZIP) herunterladen und hier hochladen. HUBIplan erkennt das
        Konto an der IBAN, schlägt passende Rechnungen und schon vorhandene Buchungen vor, erkennt{' '}
        <Term k="return_debit">Rücklastschriften</Term> und liest keinen Umsatz zweimal ein.
      </p>
      <HowTo k="how_bank_match" />
      <div className="grid-2">
        <label className="field">
          <span>Datei (XML oder ZIP)</span>
          <input
            key={inputKey}
            type="file"
            accept=".xml,.zip,application/xml,text/xml,application/zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <SelectField
          label="Konto"
          value={account ?? ''}
          onChange={(e) => setAccount(e.target.value ? Number(e.target.value) : null)}
          hint="nur nötig, wenn beim Konto keine IBAN eingetragen ist"
        >
          <option value="">an der IBAN erkennen</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </SelectField>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={!file || busy}>
          {busy ? 'Liest ein …' : 'Einlesen'}
        </button>
      </div>
    </form>
  )
}

function suggestionText(l: BankLine): string | null {
  const text = suggestionBase(l)
  // Nur nach Betrag und Datum gefunden: einzeln prüfen (Audit 31.10. FIN31-03)
  return text && l.suggestion !== 'return' && !l.suggestion_sure
    ? `${text} (nur Betrag und Datum passen, bitte prüfen)`
    : text
}

function suggestionBase(l: BankLine): string | null {
  const s = l.suggested
  switch (l.suggestion) {
    case 'invoice':
      return s.invoice
        ? `Zahlung zu ${s.invoice.number} (${s.invoice.recipient}, offen ${euro(s.invoice.outstanding)})`
        : null
    case 'debit_run':
      return s.run ? `Lastschriftlauf vom ${formatDate(s.run.date)} buchen` : null
    case 'booked':
      return s.booking ? `schon im Kassenbuch: ${s.booking.number} ${s.booking.text}` : null
    case 'return':
      return s.invoice
        ? `Rücklastschrift zu ${s.invoice.number}: als Ausgabe buchen und bei der Rechnung die Zahlung entfernen`
        : null
    default:
      return null
  }
}

function LinesCard({
  statement,
  canEdit,
  categories,
  onChanged,
}: {
  statement: BankStatement
  canEdit: boolean
  categories: Category[]
  onChanged: () => void
}) {
  const org = useActiveOrg()
  const [status, setStatus] = useState<BankLineStatus | ''>('open')
  const [page, setPage] = useState(1)
  const [booking, setBooking] = useState<number | null>(null)
  const [invoiceFor, setInvoiceFor] = useState<number | null>(null)
  const [formDirty, setFormDirty] = useState(false)
  const [message, setMessage] = useState<Message>(null)
  const [busy, setBusy] = useState(false)
  const size = 1000
  const lines = useLoad(
    () => bankApi.lines(org.id, { auszug: statement.id, status, page, size }),
    [org.id, statement.id, status, page],
  )
  const rows = lines.data?.results ?? []
  const total = lines.data?.count ?? 0
  // Wenn nicht alle Umsätze auf der Seite stehen, ist die Zahl nur ein Teil: dann ohne Zahl
  // ankündigen, dass alle Vorschläge des Auszugs übernommen werden (UX-Audit 31.10. N02)
  const complete = total <= rows.length
  const withSuggestion = rows.filter(
    (l) => l.status === 'open' && l.suggestion && l.suggestion !== 'return' && l.suggestion_sure,
  ).length

  /** Nur ein Formular je Auszug offen; Wechsel fragt bei ungespeicherten Eingaben (W01) */
  async function openForm(kind: 'booking' | 'invoice', id: number) {
    if ((booking !== null || invoiceFor !== null) && !(await confirmDiscard(formDirty))) return
    setFormDirty(false)
    setBooking(kind === 'booking' ? id : null)
    setInvoiceFor(kind === 'invoice' ? id : null)
  }
  function closeForms() {
    setFormDirty(false)
    setBooking(null)
    setInvoiceFor(null)
  }

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setMessage(null)
    try {
      setMessage({ kind: 'success', text: await action() })
      closeForms()
      await lines.reload()
      onChanged()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function applyAll() {
    const ok = await confirmDialog({
      title: complete
        ? `${withSuggestion} Vorschläge übernehmen?`
        : 'Alle Vorschläge dieses Auszugs übernehmen?',
      message: complete
        ? 'Rechnungen werden als bezahlt gebucht, Lastschriftläufe gebucht und schon vorhandene Buchungen zugeordnet.'
        : `Der Auszug hat ${total} Umsätze in dieser Ansicht; übernommen werden alle sicheren Vorschläge, auch auf den anderen Seiten.`,
      confirmLabel: 'Übernehmen',
      danger: false,
    })
    if (!ok) return
    setBusy(true)
    setMessage(null)
    try {
      const r = await bankApi.applySuggestions(org.id, statement.id)
      // Teilerfolg nicht als Erfolg gestalten (UX-Audit 31.10. N02)
      setMessage(
        r.failed.length
          ? {
              kind: 'error',
              text: `${r.done} übernommen, ${r.failed.length} nicht übernommen: ${r.failed.join('; ')}`,
            }
          : { kind: 'success', text: `${r.done} Vorschläge übernommen.` },
      )
      closeForms()
      await lines.reload()
      onChanged()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Umsätze {statement.reference || statement.file_name}</h2>
        {canEdit && withSuggestion > 0 && (
          <button
            type="button"
            className="button button-primary push-right"
            disabled={busy}
            onClick={() => void applyAll()}
          >
            {complete
              ? `Alle ${withSuggestion} Vorschläge übernehmen`
              : 'Alle Vorschläge übernehmen'}
          </button>
        )}
      </div>
      <div className="filters">
        <SelectField
          label="Zeigen"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as BankLineStatus | '')
            setPage(1)
          }}
        >
          <option value="open">offene</option>
          <option value="done">erledigte</option>
          <option value="ignored">übergangene</option>
          <option value="">alle</option>
        </SelectField>
      </div>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {lines.error && <LoadError message={lines.error} onRetry={() => void lines.reload()} />}
      {!lines.data ? (
        !lines.error && <p className="muted">Lädt …</p>
      ) : rows.length === 0 ? (
        <p className="muted">
          {status === 'open' ? 'Alles erledigt.' : 'Keine Umsätze in dieser Ansicht.'}
        </p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Datum</th>
              <th>Gegenseite und Verwendungszweck</th>
              <th className="num">Betrag</th>
              <th>Vorschlag bzw. Stand</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((l) => {
              const hint = suggestionText(l)
              return (
                <tr key={l.id}>
                  <td>{formatDate(l.date)}</td>
                  <td>
                    <strong>
                      {l.name || (l.batch_count > 1 ? `Sammelbuchung (${l.batch_count})` : '–')}
                    </strong>
                    <br />
                    <span className="small">{l.purpose}</span>
                    {l.details.length > 1 && (
                      <ul className="small">
                        {l.details.map((d, i) => (
                          <li key={i}>
                            {d.amount ? euro(d.amount) : '–'} {d.name}
                            {d.purpose ? `: ${d.purpose}` : ''}
                          </li>
                        ))}
                      </ul>
                    )}
                    {invoiceFor === l.id && (
                      <InvoiceAssignForm
                        line={l}
                        onDirty={setFormDirty}
                        onCancel={closeForms}
                        onSubmit={(invoice) =>
                          run(async () => {
                            await bankApi.assign(org.id, l.id, {
                              action: 'invoice',
                              invoice: invoice.id,
                            })
                            return `Als Zahlung zu ${invoice.number} gebucht.`
                          })
                        }
                      />
                    )}
                    {booking === l.id && (
                      <BookingForm
                        line={l}
                        categories={categories}
                        onDirty={setFormDirty}
                        onCancel={closeForms}
                        onSubmit={(data) =>
                          run(async () => {
                            const r = await bankApi.assign(org.id, l.id, {
                              action: 'booking',
                              ...data,
                            })
                            return `Gebucht als ${r.booking_number}.`
                          })
                        }
                      />
                    )}
                  </td>
                  <td className={`num${l.credit ? '' : ' field-error'}`}>
                    {l.credit ? '' : '−'}
                    {euro(l.amount)}
                  </td>
                  <td className="small">
                    {l.status === 'open'
                      ? (hint ?? <span className="muted">kein Vorschlag</span>)
                      : l.booking_number
                        ? `${l.status_label}: ${l.booking_number}`
                        : l.status_label}
                  </td>
                  <td className="actions">
                    {canEdit && l.status === 'open' && booking !== l.id && invoiceFor !== l.id && (
                      <>
                        {l.suggestion && l.suggestion !== 'return' && (
                          <>
                            <button
                              type="button"
                              className="link-button"
                              disabled={busy}
                              onClick={() =>
                                void run(async () => {
                                  await bankApi.assign(org.id, l.id, { action: 'suggestion' })
                                  return 'Vorschlag übernommen.'
                                })
                              }
                            >
                              Übernehmen
                            </button>{' '}
                          </>
                        )}
                        {l.credit && l.batch_count <= 1 && (
                          <>
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => void openForm('invoice', l.id)}
                            >
                              Rechnung zuordnen
                            </button>{' '}
                          </>
                        )}
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => void openForm('booking', l.id)}
                        >
                          Neue Buchung
                        </button>{' '}
                        <button
                          type="button"
                          className="link-button"
                          disabled={busy}
                          onClick={() =>
                            void run(async () => {
                              await bankApi.assign(org.id, l.id, { action: 'ignore' })
                              return 'Übergangen.'
                            })
                          }
                        >
                          Übergehen
                        </button>
                      </>
                    )}
                    {canEdit && l.status === 'ignored' && (
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await bankApi.assign(org.id, l.id, { action: 'reopen' })
                            return 'Wieder offen.'
                          })
                        }
                      >
                        Wieder öffnen
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <RangePager page={page} size={size} total={total} onPage={setPage} noun="Umsätzen" />
      <p className="muted small">
        „Rechnung zuordnen“ bucht den Eingang als Zahlung einer offenen Rechnung. „Neue Buchung“
        legt eine Buchung im Kassenbuch an, ohne Rechnung. „Übergehen“ für Umsätze, die schon anders
        erfasst sind. Gebuchte Umsätze korrigierst du im Kassenbuch.
      </p>
    </div>
  )
}

function BookingForm({
  line,
  categories,
  onDirty,
  onCancel,
  onSubmit,
}: {
  line: BankLine
  categories: Category[]
  onDirty: (dirty: boolean) => void
  onCancel: () => void
  onSubmit: (data: { category: number; membership: number | null; text: string }) => Promise<void>
}) {
  const org = useActiveOrg()
  const kind = line.credit ? 'income' : 'expense'
  const cats = categories.filter((c) => c.is_active && (c.kind === kind || c.kind === 'both'))
  const [category, setCategory] = useState<number | null>(null)
  const [member, setMember] = useState<MemberRow | null>(null)
  const [text, setText] = useState(line.purpose.slice(0, 200))
  const suggested = line.suggested.membership
  // Eingaben bis zum Buchen schützen (UX-Audit 31.10. W01)
  const { dirty } = useChangesGuard([category, member?.id ?? null, text])
  useEffect(() => onDirty(dirty), [dirty, onDirty])

  return (
    <div className="subcard">
      <SelectField
        label={line.credit ? 'Kategorie (Einnahme)' : 'Kategorie (Ausgabe)'}
        value={category ?? ''}
        onChange={(e) => setCategory(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">bitte wählen</option>
        {cats.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </SelectField>
      <Field
        label="Buchungstext"
        value={text}
        maxLength={200}
        onChange={(e) => setText(e.target.value)}
      />
      <MemberPicker
        orgId={org.id}
        value={member}
        onChange={setMember}
        label={
          suggested ? `Mitglied (optional, erkannt: ${suggested.name})` : 'Mitglied (optional)'
        }
      />
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={!category}
          onClick={() =>
            category &&
            void onSubmit({ category, membership: member?.id ?? suggested?.id ?? null, text })
          }
        >
          Buchen
        </button>
        <button
          type="button"
          className="button button-ghost"
          onClick={() => void confirmDiscard(dirty).then((ok) => ok && onCancel())}
        >
          Abbrechen
        </button>
      </div>
    </div>
  )
}

/** Eingang einer offenen Rechnung zuordnen (UX-Audit 31.10. N03) */
function InvoiceAssignForm({
  line,
  onDirty,
  onCancel,
  onSubmit,
}: {
  line: BankLine
  onDirty: (dirty: boolean) => void
  onCancel: () => void
  onSubmit: (invoice: InvoiceRow) => Promise<void>
}) {
  const org = useActiveOrg()
  const [term, setTerm] = useState(line.name)
  const [query, setQuery] = useState(line.name)
  const [chosen, setChosen] = useState<InvoiceRow | null>(null)
  const found = useLoad(
    () => billingApi.invoices(org.id, { status: 'open', suche: query.trim() }),
    [org.id, query],
  )
  const { dirty } = useChangesGuard(chosen?.id ?? null)
  useEffect(() => onDirty(dirty), [dirty, onDirty])
  const rows = found.data?.results ?? []
  const diff = chosen ? Number(line.amount) - Number(chosen.outstanding) : 0

  return (
    <div className="subcard">
      <form
        className="inline-add"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          setQuery(term)
        }}
      >
        <input
          type="search"
          aria-label="Offene Rechnung suchen (Nummer oder Name)"
          placeholder="Nummer oder Name"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <button type="submit" className="button button-ghost">
          Suchen
        </button>
      </form>
      {found.error && <LoadError message={found.error} onRetry={() => void found.reload()} />}
      {!found.data && !found.error && <p className="muted small">Lädt …</p>}
      {found.data && rows.length === 0 && (
        <p className="muted small">Keine offene Rechnung gefunden.</p>
      )}
      {rows.length > 0 && (
        <fieldset>
          <legend className="small">Offene Rechnung wählen</legend>
          {rows.slice(0, 20).map((inv) => (
            <label key={inv.id} className="checkbox">
              <input
                type="radio"
                name={`invoice-${line.id}`}
                checked={chosen?.id === inv.id}
                onChange={() => setChosen(inv)}
              />
              <span>
                {inv.number} · {inv.recipient_name} · offen {euro(inv.outstanding)}
                <span className="muted small"> · {formatDate(inv.date)}</span>
              </span>
            </label>
          ))}
          {found.data && found.data.count > 20 && (
            <p className="muted small">
              {found.data.count} Treffer, die ersten 20 stehen hier. Bitte genauer suchen.
            </p>
          )}
        </fieldset>
      )}
      {chosen && Math.abs(diff) >= 0.005 && (
        <p className="small">
          {diff < 0
            ? `Teilzahlung: Es bleiben ${euro(String(-diff))} offen.`
            : `Der Eingang ist ${euro(String(diff))} höher als der offene Betrag.`}
        </p>
      )}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={!chosen}
          onClick={() => chosen && void onSubmit(chosen)}
        >
          Zuordnen
        </button>
        <button
          type="button"
          className="button button-ghost"
          onClick={() => void confirmDiscard(dirty).then((ok) => ok && onCancel())}
        >
          Abbrechen
        </button>
      </div>
    </div>
  )
}
