// Beiträge: Rechnungen suchen, ansehen, einzeln anlegen, Zahlungen erfassen.
import { todayIso } from '../../api/members.ts'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDetailParam } from '../../components/detailParam.ts'
import { billingApi } from '../../api/billing.ts'
import { ApiError, newRequestKey } from '../../api/client.ts'
import type { BillingSettings, Invoice, InvoiceRow } from '../../api/billing.ts'
import { euro, financeApi, parseAmount } from '../../api/finance.ts'
import type { Page, PickedMember } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import {
  errorMessage,
  formatDate,
  formatDateTime,
  useAutoSave,
  useLoad,
} from '../../components/forms.ts'
import { Alert, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { useTerms } from '../../org/terms.ts'
import { Term } from '../../learning/Aids.tsx'

export function StatusBadge({
  row,
}: {
  row: Pick<InvoiceRow, 'status' | 'status_label' | 'overdue'>
}) {
  const cls = row.overdue ? 'overdue' : row.status
  return (
    <span className={`status status-${cls}`}>{row.overdue ? 'überfällig' : row.status_label}</span>
  )
}

export function InvoicesPage() {
  const tm = useTerms()
  const org = useActiveOrg()
  const [params, setParams] = useSearchParams()
  const settings = useLoad(() => billingApi.settings(org.id), [org.id])
  // Untereinheiten haben keine Beitragsläufe
  const runs = useLoad(
    () => (org.type === 'unit' ? Promise.resolve([]) : billingApi.runs(org.id)),
    [org.id, org.type],
  )
  const [search, setSearch] = useState(params.get('suche') ?? '')
  const [data, setData] = useState<Page<InvoiceRow> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const detail = useDetailParam('rechnung')
  const creating = detail.value === 'neu'
  const openId = detail.value && /^\d+$/.test(detail.value) ? Number(detail.value) : null
  const [version, setVersion] = useState(0)

  const status = params.get('status') ?? ''
  const run = params.get('lauf') ?? ''
  const overdue = params.get('ueberfaellig') === '1'
  const term = params.get('suche') ?? ''
  const page = Number(params.get('seite') ?? '1')
  const club = params.get('verein') ?? ''
  const project = params.get('veranstaltung') ?? ''

  useEffect(() => {
    let alive = true
    billingApi
      .invoices(org.id, {
        status,
        lauf: run,
        suche: term,
        ueberfaellig: overdue,
        verein: club,
        veranstaltung: project,
        page,
      })
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
  }, [org.id, status, run, term, overdue, club, project, page, version])

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('seite')
    setParams(next)
  }

  if (settings.error) return <Alert kind="error">{settings.error}</Alert>
  if (!settings.data) return <p className="muted">Lädt …</p>
  const s = settings.data
  const refresh = () => setVersion((v) => v + 1)

  return (
    <div className="stack">
      <div className="card card-wide filters">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setParam('suche', search.trim())
          }}
        >
          <input
            type="search"
            aria-label="Rechnungen durchsuchen"
            placeholder="Name, Betreff oder Rechnungsnummer"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <select
          aria-label="Status"
          value={overdue ? 'ueberfaellig' : status}
          onChange={(e) => {
            const next = new URLSearchParams(params)
            next.delete('status')
            next.delete('ueberfaellig')
            next.delete('seite')
            if (e.target.value === 'ueberfaellig') next.set('ueberfaellig', '1')
            else if (e.target.value) next.set('status', e.target.value)
            setParams(next)
          }}
        >
          <option value="">alle Status</option>
          <option value="draft">Entwürfe</option>
          <option value="open">offen</option>
          <option value="ueberfaellig">überfällig</option>
          <option value="paid">bezahlt</option>
          <option value="cancelled">storniert</option>
        </select>
        {s.org_type === 'federation' && (
          <select
            aria-label={tm.Sg}
            value={params.get('verein') ?? ''}
            onChange={(e) => setParam('verein', e.target.value)}
          >
            <option value="">alle {tm.pl}</option>
            {s.clubs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
        {org.type !== 'unit' && (
          <select
            aria-label="Beitragslauf"
            value={run}
            onChange={(e) => setParam('lauf', e.target.value)}
          >
            <option value="">alle Rechnungen</option>
            {(runs.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                Beitragslauf {r.label}
              </option>
            ))}
          </select>
        )}
        {runs.error && (
          <button type="button" className="link-button" onClick={() => void runs.reload()}>
            Beitragsläufe nicht geladen, erneut laden
          </button>
        )}
        {s.can_edit && !creating && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => detail.open('neu')}
          >
            Neue Rechnung
          </button>
        )}
      </div>

      {creating && (
        <InvoiceForm
          settings={s}
          invoice={null}
          onCancel={detail.close}
          onSaved={(inv) => {
            detail.replace(String(inv.id))
            refresh()
          }}
        />
      )}

      {openId !== null && (
        <InvoiceDetail
          key={openId}
          id={openId}
          settings={s}
          onClose={detail.close}
          onChanged={refresh}
          onDeleted={() => {
            detail.close()
            refresh()
          }}
        />
      )}

      {error && <Alert kind="error">{error}</Alert>}
      {data && (
        <div className="card card-wide">
          {data.results.length === 0 ? (
            <p className="muted">Keine Rechnungen gefunden.</p>
          ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Nummer</th>
                    <th>Empfänger</th>
                    <th>Datum</th>
                    <th>Status</th>
                    <th className="num">Betrag</th>
                    <th className="num">
                      <Term k="outstanding">offen</Term>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((r) => (
                    <tr key={r.id} className={r.id === openId ? 'row-active' : undefined}>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => detail.open(String(r.id))}
                        >
                          {r.number}
                        </button>
                      </td>
                      <td>
                        {r.recipient_name.split('\n')[0]}
                        <div className="muted small">
                          {r.subject}
                          {r.sent_at && ' · per E-Mail verschickt'}
                          {r.dunning_level > 0 && ` · ${r.dunning_level}. Mahnstufe`}
                        </div>
                      </td>
                      <td>{formatDate(r.date)}</td>
                      <td>
                        <StatusBadge row={r} />
                      </td>
                      <td className="num">{euro(r.total)}</td>
                      <td className="num">{Number(r.outstanding) ? euro(r.outstanding) : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(data.next || data.previous) && (
            <div className="button-row">
              <button
                type="button"
                className="button button-ghost"
                disabled={!data.previous}
                onClick={() =>
                  setParams({ ...Object.fromEntries(params), seite: String(page - 1) })
                }
              >
                Zurück
              </button>
              <span className="muted small">
                Seite {page} · {data.count} Rechnungen
              </span>
              <button
                type="button"
                className="button button-ghost"
                disabled={!data.next}
                onClick={() =>
                  setParams({ ...Object.fromEntries(params), seite: String(page + 1) })
                }
              >
                Weiter
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function InvoiceDetail({
  id,
  settings,
  onClose,
  onChanged,
  onDeleted,
}: {
  id: number
  settings: BillingSettings
  onClose: () => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const org = useActiveOrg()
  const { data: inv, error, setData } = useLoad(() => billingApi.invoice(org.id, id), [org.id, id])
  const [editing, setEditing] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const canEdit = settings.can_edit

  if (error) return <Alert kind="error">{error}</Alert>
  if (!inv) return <p className="muted">Lädt …</p>

  async function act(action: () => Promise<unknown>, text: string, deleted = false) {
    setBusy(true)
    setNotice(null)
    try {
      const result = await action()
      if (deleted) {
        onDeleted()
        return
      }
      if (result && typeof result === 'object' && 'id' in result) setData(result as Invoice)
      else setData(await billingApi.invoice(org.id, id))
      setNotice({ kind: 'success', text })
      onChanged()
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <InvoiceForm
        settings={settings}
        invoice={inv}
        onCancel={() => setEditing(false)}
        onSaved={(saved) => {
          setData(saved)
          setEditing(false)
          onChanged()
        }}
      />
    )
  }

  const collective = inv.recipient_kind === 'department'
  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>
          {inv.status === 'draft' ? 'Rechnungsentwurf' : `Rechnung ${inv.number}`}{' '}
          <StatusBadge row={inv} />
        </h2>
        <button type="button" className="button button-ghost push-right" onClick={onClose}>
          Schließen
        </button>
      </div>
      <div className="grid-2">
        <div>
          <p style={{ whiteSpace: 'pre-line' }}>
            <strong>{inv.recipient_name}</strong>
            {inv.recipient_address && `\n${inv.recipient_address}`}
          </p>
          <p className="muted small">{inv.recipient_email || 'keine E-Mail-Adresse bekannt'}</p>
        </div>
        <dl className="facts">
          <dt>Betreff</dt>
          <dd>{inv.subject}</dd>
          <dt>Rechnungsdatum</dt>
          <dd>{formatDate(inv.date)}</dd>
          <dt>fällig</dt>
          <dd>{formatDate(inv.due_date)}</dd>
          {inv.run_label && (
            <>
              <dt>Beitragslauf</dt>
              <dd>{inv.run_label}</dd>
            </>
          )}
          {inv.project_name && (
            <>
              <dt>Veranstaltung</dt>
              <dd>{inv.project_name}</dd>
            </>
          )}
          {inv.sent_at && (
            <>
              <dt>verschickt</dt>
              <dd>{formatDateTime(inv.sent_at)}</dd>
            </>
          )}
        </dl>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>{collective ? 'Mitglied' : 'Posten'}</th>
            <th />
            <th className="num">Betrag</th>
          </tr>
        </thead>
        <tbody>
          {inv.lines.map((l) => (
            <tr key={l.id}>
              <td>{l.text}</td>
              <td className="muted small">
                {l.detail}
                {l.vat_rate && ` · ${Number(l.vat_rate).toLocaleString('de-DE')} % USt`}
              </td>
              <td className="num">{euro(l.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th>Gesamt</th>
            <th />
            <th className="num">{euro(inv.total)}</th>
          </tr>
          {inv.vat.map((v) => (
            <tr key={v.rate} className="muted small">
              <td>
                darin {v.rate.replace('.', ',')} % <Term k="vat">Umsatzsteuer</Term>
              </td>
              <td>netto {euro(v.net)}</td>
              <td className="num">{euro(v.vat)}</td>
            </tr>
          ))}
          {Number(inv.paid) > 0 && (
            <tr>
              <th>noch offen</th>
              <th />
              <th className="num">{euro(inv.outstanding)}</th>
            </tr>
          )}
        </tfoot>
      </table>
      {inv.note && <p style={{ whiteSpace: 'pre-line' }}>{inv.note}</p>}

      {inv.dunnings.length > 0 && (
        <>
          <h3>Mahnungen</h3>
          <table className="table">
            <tbody>
              {inv.dunnings.map((d) => (
                <tr key={d.id}>
                  <td>{formatDate(d.date)}</td>
                  <td>
                    {d.name}
                    <div className="muted small">
                      zahlbar bis {formatDate(d.due_date)}
                      {Number(d.fee) > 0 && ` · Gebühr ${euro(d.fee)}`}
                      {d.sent_at ? ' · per E-Mail verschickt' : ' · nicht per E-Mail verschickt'}
                    </div>
                  </td>
                  <td className="actions">
                    <a
                      className="link-button"
                      href={billingApi.dunningPdfUrl(org.id, [d.id])}
                      target="_blank"
                      rel="noreferrer"
                    >
                      PDF
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {inv.payments.length > 0 && (
        <>
          <h3>Zahlungen</h3>
          <table className="table">
            <tbody>
              {inv.payments.map((p) => (
                <tr key={p.id}>
                  <td>{formatDate(p.date)}</td>
                  <td>
                    {p.method_label} · {p.account_name}
                    <div className="muted small">Buchung {p.booking_number}</div>
                  </td>
                  <td className="num">{euro(p.amount)}</td>
                  <td className="actions">
                    <a
                      className="link-button"
                      href={billingApi.receiptUrl(org.id, p.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Quittung
                    </a>
                    {canEdit && (
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy}
                        onClick={async () => {
                          if (
                            await confirmDialog({
                              title: 'Zahlung entfernen?',
                              message: 'Die Zahlung und ihre Buchung in der Kasse werden entfernt.',
                              confirmLabel: 'Entfernen',
                            })
                          )
                            void act(
                              () => billingApi.deletePayment(org.id, p.id),
                              'Zahlung entfernt.',
                            )
                        }}
                      >
                        Entfernen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {canEdit && inv.status === 'open' && (
        <PaymentForm
          key={inv.outstanding}
          settings={settings}
          invoice={inv}
          onSaved={(saved) => {
            setData(saved)
            setNotice({
              kind: 'success',
              text: saved.status === 'paid' ? 'Bezahlt.' : 'Teilzahlung erfasst.',
            })
            onChanged()
          }}
        />
      )}

      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <div className="button-row">
        <a
          className="button button-ghost"
          href={billingApi.pdfUrl(org.id, inv.id)}
          target="_blank"
          rel="noreferrer"
        >
          PDF ansehen
        </a>
        {canEdit && inv.status === 'draft' && (
          <>
            <button type="button" className="button button-ghost" onClick={() => setEditing(true)}>
              Bearbeiten
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() =>
                void act(() => billingApi.finalize(org.id, inv.id), 'Festgeschrieben.')
              }
            >
              Festschreiben
            </button>
            <button
              type="button"
              className="button button-danger push-right"
              disabled={busy}
              onClick={async () => {
                if (await confirmDialog({ title: 'Entwurf löschen?', confirmLabel: 'Löschen' }))
                  void act(() => billingApi.deleteInvoice(org.id, inv.id), '', true)
              }}
            >
              Löschen
            </button>
          </>
        )}
        {canEdit && inv.status === 'open' && inv.recipient_email && (
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() =>
              void act(
                () => billingApi.send(org.id, inv.id),
                `An ${inv.recipient_email} verschickt.`,
              )
            }
          >
            {inv.sent_at ? 'Erneut per E-Mail senden' : 'Per E-Mail senden'}
          </button>
        )}
        {canEdit && inv.status === 'open' && inv.payments.length === 0 && (
          <button
            type="button"
            className="button button-danger push-right"
            disabled={busy}
            onClick={async () => {
              if (
                await confirmDialog({
                  title: `Rechnung ${inv.number} stornieren?`,
                  confirmLabel: 'Stornieren',
                })
              )
                void act(() => billingApi.cancel(org.id, inv.id), 'Storniert.')
            }}
          >
            Stornieren
          </button>
        )}
      </div>
    </div>
  )
}

function PaymentForm({
  settings,
  invoice,
  onSaved,
}: {
  settings: BillingSettings
  invoice: Invoice
  onSaved: (inv: Invoice) => void
}) {
  const org = useActiveOrg()
  const bank = settings.accounts.find((a) => a.kind !== 'cash')
  const cash = settings.accounts.find((a) => a.kind === 'cash')
  const [method, setMethod] = useState<'transfer' | 'cash'>('transfer')
  const [account, setAccount] = useState(String(settings.account ?? bank?.id ?? ''))
  const [date, setDate] = useState(todayIso)
  const [amount, setAmount] = useState(invoice.outstanding.replace('.', ','))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Ein Schlüssel je Formular: erneutes Absenden bucht die Zahlung nicht doppelt
  const [requestKey] = useState(newRequestKey)
  const navigate = useNavigate()
  // Barzahlung mit unterschriebener Quittung (konzepte/digitale-quittung.md)
  const canSign = org.modules.includes('finance') && org.permissions.includes(PERM.financeEdit)

  async function sign() {
    setBusy(true)
    setError(null)
    try {
      const r = await financeApi.cashReceiptFromInvoice(org.id, invoice.id, {
        account: Number(account),
        amount: parseAmount(amount),
      })
      navigate(`/finanzen/quittungen/${r.id}`)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(
        await billingApi.addPayment(
          org.id,
          invoice.id,
          {
            date,
            amount: parseAmount(amount),
            method,
            account: Number(account),
          },
          requestKey,
        ),
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="subcard" onSubmit={save}>
      <h3>Zahlungseingang erfassen</h3>
      <div className="grid-3">
        <SelectField
          label="Zahlungsweg"
          value={method}
          onChange={(e) => {
            const m = e.target.value as 'transfer' | 'cash'
            setMethod(m)
            const fit =
              m === 'cash'
                ? cash
                : (settings.accounts.find((a) => a.id === settings.account) ?? bank)
            if (fit) setAccount(String(fit.id))
          }}
        >
          <option value="transfer">Überweisung</option>
          <option value="cash">bar</option>
        </SelectField>
        <SelectField label="Konto" value={account} onChange={(e) => setAccount(e.target.value)}>
          {settings.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </SelectField>
        <Field
          label="Datum"
          type="date"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <Field
          label="Betrag (€)"
          inputMode="decimal"
          required
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>
      <p className="muted small">Die Zahlung wird automatisch als Einnahme in der Kasse gebucht.</p>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={busy || !account}>
          Zahlung buchen
        </button>
        {method === 'cash' && canSign && (
          <button
            type="button"
            className="button button-ghost"
            disabled={busy || !account}
            onClick={() => void sign()}
          >
            Mit Unterschrift quittieren
          </button>
        )}
      </div>
      {method === 'cash' && canSign && (
        <p className="muted small">
          „Mit Unterschrift quittieren“ bucht die Zahlung erst, wenn beide auf dem Bildschirm
          unterschrieben haben. Das Datum ist dann der Tag der Unterschrift.
        </p>
      )}
    </form>
  )
}

interface LineDraft {
  id?: number
  text: string
  detail: string
  amount: string
  vat_rate: string
}

function InvoiceForm({
  settings,
  invoice,
  onCancel,
  onSaved,
}: {
  settings: BillingSettings
  invoice: Invoice | null
  onCancel: () => void
  onSaved: (inv: Invoice) => void
}) {
  const org = useActiveOrg()
  const federation = settings.org_type === 'federation'
  // Arbeitsbereich einer Untereinheit: Rechnungen nur an ihre Mitglieder
  const unit = settings.org_type === 'unit'
  const searchUnitMembers = useCallback(
    (term: string) => billingApi.members(org.id, term),
    [org.id],
  )
  // Für alle Einheiten gleich: an ein Mitglied (wenn sie eigene führt) oder an eine Untereinheit
  const canMember = settings.keeps_members ?? !federation
  const subUnits = unit ? [] : (settings.units ?? (federation ? settings.clubs : []))
  const initialUnit = invoice?.club ?? invoice?.department ?? null
  const [kind, setKind] = useState<'member' | 'unit'>(() => {
    if (invoice) return invoice.recipient_kind === 'member' ? 'member' : 'unit'
    return canMember ? 'member' : 'unit'
  })
  const [member, setMember] = useState<PickedMember | null>(null)
  const [unitId, setUnitId] = useState(initialUnit ? String(initialUnit) : '')
  const [subject, setSubject] = useState(invoice?.subject ?? 'Rechnung')
  const [date, setDate] = useState(() => invoice?.date ?? todayIso())
  const [note, setNote] = useState(invoice?.note ?? '')
  const [project, setProject] = useState(invoice?.project ? String(invoice.project) : '')
  const withProjects = org.modules.includes('finance') && org.permissions.includes(PERM.financeView)
  const projects = useLoad(
    () => (withProjects ? financeApi.projects(org.id) : Promise.resolve([])),
    [org.id, withProjects],
  )
  const usableProjects = (projects.data ?? []).filter(
    (p) => p.status !== 'done' || String(p.id) === project,
  )
  const [lines, setLines] = useState<LineDraft[]>(
    invoice?.lines.map((l) => ({
      id: l.id,
      text: l.text,
      detail: l.detail,
      amount: l.amount.replace('.', ','),
      vat_rate: l.vat_rate ?? '',
    })) ?? [{ text: '', detail: '', amount: '', vat_rate: '' }],
  )
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const keepMember = invoice?.recipient_kind === 'member' && !member

  function setLine(i: number, patch: Partial<LineDraft>) {
    setLines((ls) => ls.map((l, n) => (n === i ? { ...l, ...patch } : l)))
  }

  // Ganz leere Zusatzzeilen zählen nicht; jede angefangene Zeile muss vollständig sein.
  // Summe und gespeicherte Posten kommen aus derselben Liste.
  const filled = lines
    .map((l, i) => ({ ...l, index: i }))
    .filter((l) => l.text.trim() || l.detail.trim() || l.amount.trim())
  const lineErrors: Record<number, { text?: string; amount?: string }> = {}
  for (const l of filled) {
    const n = l.index + 1
    if (!l.text.trim())
      lineErrors[l.index] = {
        text: `Posten ${n}: Bitte eine Bezeichnung ergänzen oder den gesamten Posten entfernen.`,
      }
    const amount = parseAmount(l.amount)
    if (!amount)
      lineErrors[l.index] = {
        ...lineErrors[l.index],
        amount: 'Bitte einen Betrag eintragen (0 für einen Posten ohne Betrag).',
      }
    else if (Number.isNaN(Number(amount)))
      lineErrors[l.index] = {
        ...lineErrors[l.index],
        amount: 'Bitte einen gültigen Betrag eintragen.',
      }
  }
  const [showLineErrors, setShowLineErrors] = useState(false)
  const incompleteText =
    filled.length === 0
      ? 'Bitte mindestens einen Posten eintragen.'
      : Object.keys(lineErrors).length > 0
        ? 'Bitte die markierten Posten vervollständigen oder entfernen.'
        : null

  const data = {
    recipient_kind: kind,
    membership:
      kind === 'member' ? (member?.id ?? (keepMember ? invoice?.membership : null)) : null,
    unit: kind === 'unit' ? Number(unitId) || null : null,
    subject,
    date,
    note,
    ...(withProjects ? { project: Number(project) || null } : {}),
    lines: filled.map((l) => ({
      id: l.id ?? null,
      text: l.text,
      detail: l.detail,
      amount: parseAmount(l.amount),
      vat_rate: settings.vat_enabled && l.vat_rate ? l.vat_rate : null,
    })),
  }
  // Gleicher Inhalt, gleiches Objekt: sonst liefe das Autospeichern bei jedem Neuzeichnen an
  const dataJson = JSON.stringify(data)
  const draft = useMemo(() => JSON.parse(dataJson) as typeof data, [dataJson])
  const [, setFieldErrors] = useState<Record<string, string>>({})
  const lastSaved = useRef<Invoice | null>(null)

  // Bestehende Entwürfe speichern automatisch, neue erst mit „Entwurf anlegen“
  const auto = useAutoSave(
    { values: draft, setErrors: setFieldErrors },
    async (_changes, values) => {
      if (incompleteText) {
        setShowLineErrors(true)
        throw new ApiError(400, { detail: incompleteText })
      }
      const sent = filled.map((l) => lines[l.index])
      const saved = await billingApi.updateInvoice(org.id, invoice!.id, values)
      lastSaved.current = saved
      // Neue Posten bekommen ihre ID, damit das nächste Speichern sie nicht neu anlegt
      setLines((ls) =>
        ls.map((l) => {
          const k = sent.indexOf(l)
          const id = k >= 0 ? saved.lines[k]?.id : undefined
          return id && !l.id ? { ...l, id } : l
        }),
      )
      return saved
    },
    { enabled: invoice !== null },
  )

  async function save(e: FormEvent) {
    e.preventDefault()
    if (invoice) {
      if (await auto.flush()) onSaved(lastSaved.current ?? invoice)
      return
    }
    if (incompleteText) {
      setShowLineErrors(true)
      setError(incompleteText)
      return
    }
    setBusy(true)
    setError(null)
    try {
      onSaved(await billingApi.createInvoice(org.id, data))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const total = filled.reduce((sum, l) => sum + (Number(parseAmount(l.amount)) || 0), 0)
  const incomplete = Object.keys(lineErrors).length > 0

  return (
    <form className="card card-wide" onSubmit={save}>
      <h2>{invoice ? 'Entwurf bearbeiten' : 'Neue Rechnung'}</h2>
      {invoice && <SaveStatus auto={auto} />}
      <p className="muted small">
        Für Aufnahmegebühren, Umlagen, Uniformen und andere Einzelposten. Eine Ermäßigung trägst du
        als Posten mit Minusbetrag ein.
      </p>
      <div className="grid-3">
        {canMember && subUnits.length > 0 && (
          <SelectField
            label="Empfänger"
            value={kind}
            onChange={(e) => setKind(e.target.value as 'member' | 'unit')}
          >
            <option value="member">Mitglied</option>
            <option value="unit">{settings.department_label}</option>
          </SelectField>
        )}
        {kind === 'member' ? (
          <div>
            <MemberPicker
              orgId={org.id}
              value={member}
              onChange={setMember}
              label="Mitglied"
              search={unit ? searchUnitMembers : undefined}
            />
            {keepMember && (
              <small className="muted">bisher: {invoice?.recipient_name.split('\n')[0]}</small>
            )}
          </div>
        ) : (
          <SelectField
            label={settings.department_label}
            value={unitId}
            onChange={(e) => setUnitId(e.target.value)}
          >
            <option value="">bitte wählen</option>
            {subUnits.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </SelectField>
        )}
        <Field
          label="Rechnungsdatum"
          type="date"
          required
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <Field
        label="Betreff"
        required
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
      />
      {projects.error && (
        <LoadError
          message={`Die Veranstaltungen konnten nicht geladen werden; deine Eingaben bleiben erhalten. ${projects.error}`}
          onRetry={() => void projects.reload()}
        />
      )}
      {usableProjects.length > 0 && (
        <SelectField
          label="Veranstaltung (optional)"
          value={project}
          hint="Zahlungen werden in der Kasse dieser Veranstaltung zugeordnet"
          onChange={(e) => setProject(e.target.value)}
        >
          <option value="">keine</option>
          {usableProjects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </SelectField>
      )}
      <h3>Posten</h3>
      {lines.map((l, i) => (
        <div key={i} className={settings.vat_enabled ? 'line-row line-row-vat' : 'line-row'}>
          <Field
            label={`Posten ${i + 1}`}
            value={l.text}
            error={showLineErrors ? lineErrors[i]?.text : undefined}
            onChange={(e) => setLine(i, { text: e.target.value })}
          />
          <Field
            label="Zusatz (optional)"
            value={l.detail}
            onChange={(e) => setLine(i, { detail: e.target.value })}
          />
          <Field
            label="Betrag (€)"
            inputMode="decimal"
            value={l.amount}
            error={showLineErrors ? lineErrors[i]?.amount : undefined}
            onChange={(e) => setLine(i, { amount: e.target.value })}
          />
          {settings.vat_enabled && (
            <SelectField
              label="Umsatzsteuer"
              value={l.vat_rate ? String(Number(l.vat_rate)) : ''}
              onChange={(e) => setLine(i, { vat_rate: e.target.value })}
            >
              <option value="">keine</option>
              {[...new Set([Number(settings.vat_rate), 19, 7])].map((r) => (
                <option key={r} value={String(r)}>
                  {r.toLocaleString('de-DE')} % enthalten
                </option>
              ))}
            </SelectField>
          )}
          <button
            type="button"
            className="link-button"
            disabled={lines.length === 1}
            onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}
          >
            Entfernen
          </button>
        </div>
      ))}
      <div className="button-row">
        <button
          type="button"
          className="button button-ghost"
          onClick={() =>
            setLines((ls) => [...ls, { text: '', detail: '', amount: '', vat_rate: '' }])
          }
        >
          Posten hinzufügen
        </button>
        <strong className="push-right">
          Summe {euro(total)}
          {incomplete && <span className="muted small"> (unvollständige Posten offen)</span>}
        </strong>
      </div>
      <label className="field">
        <span>Hinweis auf der Rechnung (optional)</span>
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={invoice ? 'button button-ghost' : 'button button-primary'}
          disabled={busy}
        >
          {invoice ? 'Schließen' : 'Entwurf anlegen'}
        </button>
        {!invoice && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  )
}
