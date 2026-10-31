// Finanzen › Lastschriften: Lastschriftläufe mit Datei für die Bank, SEPA-Mandate.
import { todayIso } from '../../api/members.ts'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { billingApi, sepaApi } from '../../api/billing.ts'
import type { DebitProposals, DebitRun, Mandate } from '../../api/billing.ts'
import { ApiError } from '../../api/client.ts'
import { euro } from '../../api/finance.ts'
import type { MemberRow } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Field, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { useTerms } from '../../org/terms.ts'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { Checklist } from '../../learning/Checklist.tsx'
import { debitChecks } from '../../learning/checks.ts'

/** So viele Läufe zeigt die Seite zunächst; ältere erst auf Wunsch. */
const RUNS_SHOWN = 10

type Notice = { kind: 'success' | 'error'; text: string } | null

function nextWorkday(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}

export function DebitsPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.billingEdit)
  const proposals = useLoad(() => sepaApi.proposals(org.id), [org.id])
  const runs = useLoad(() => sepaApi.runs(org.id), [org.id])
  const [showAll, setShowAll] = useState(false)
  const reload = async () => {
    await Promise.all([proposals.reload(), runs.reload()])
  }

  if (proposals.error ?? runs.error)
    return <Alert kind="error">{proposals.error ?? runs.error}</Alert>
  if (!proposals.data || !runs.data) return <p className="muted">Lädt …</p>
  const p = proposals.data
  const ready = !!p.creditor_id && p.account_has_iban

  return (
    <div className="stack">
      {!ready && (
        <Alert kind="error">
          Für Lastschriften fehlen noch {!p.creditor_id && 'die Gläubiger-Identifikationsnummer'}
          {!p.creditor_id && !p.account_has_iban && ' und '}
          {!p.account_has_iban && 'ein Konto mit IBAN'}. Beides steht unter{' '}
          <Link to="/finanzen/einstellungen/rechnung">Einrichtung › Rechnung & Zahlung</Link>.
        </Alert>
      )}
      {ready && canEdit && <NewRun orgId={org.id} proposals={p} onCreated={reload} />}
      {(showAll ? runs.data : runs.data.slice(0, RUNS_SHOWN)).map((run) => (
        <RunCard key={run.id} orgId={org.id} run={run} canEdit={canEdit} onChanged={reload} />
      ))}
      {!showAll && runs.data.length > RUNS_SHOWN && (
        <button type="button" className="button button-ghost" onClick={() => setShowAll(true)}>
          Ältere Lastschriftläufe anzeigen ({runs.data.length - RUNS_SHOWN})
        </button>
      )}
    </div>
  )
}

function NewRun({
  orgId,
  proposals,
  onCreated,
}: {
  orgId: number
  proposals: DebitProposals
  onCreated: () => Promise<void>
}) {
  const [skip, setSkip] = useState<Set<number>>(new Set())
  const [date, setDate] = useState(nextWorkday(proposals.earliest))
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)
  const chosen = proposals.invoices.filter((i) => !skip.has(i.id))
  const total = chosen.reduce((sum, i) => sum + Number(i.outstanding), 0)
  const checks = debitChecks({
    creditorId: proposals.creditor_id,
    creditorValid: proposals.creditor_valid ?? !!proposals.creditor_id,
    date,
    earliest: proposals.earliest,
    prenotificationDays: proposals.prenotification_days,
    invoices: chosen,
    expiringSoon: proposals.expiring_soon,
  })

  async function create(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setNotice(null)
    try {
      const run = await sepaApi.createRun(
        orgId,
        chosen.map((i) => i.id),
        date,
      )
      const unsent = run.items.length - (run.prenotified ?? 0)
      setNotice({
        kind: 'success',
        text:
          `Lastschriftlauf über ${euro(run.total)} erstellt, ${run.prenotified ?? 0} Ankündigungen per E-Mail verschickt.` +
          (unsent ? ` ${unsent} Ankündigungen bitte ausdrucken.` : ''),
      })
      setSkip(new Set())
      await onCreated()
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card card-wide" onSubmit={create}>
      <h2>Neuer Lastschriftlauf</h2>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <Why k="sepa_use" />
      {proposals.invoices.length === 0 ? (
        <p className="muted">
          Keine offenen Rechnungen mit gültigem Mandat. Mandate erfasst du im Reiter{' '}
          <Link to="/finanzen/lastschrift/mandate">SEPA-Mandate</Link>, oder die Mitglieder erteilen
          sie im Mitgliederbereich.
        </p>
      ) : (
        <>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th />
                  <th>Rechnung</th>
                  <th>Zahler</th>
                  <th>
                    <Term k="mandate">Mandat</Term>
                  </th>
                  <th className="num">Betrag</th>
                </tr>
              </thead>
              <tbody>
                {proposals.invoices.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${i.number} einziehen`}
                        checked={!skip.has(i.id)}
                        onChange={(e) => {
                          const next = new Set(skip)
                          if (e.target.checked) next.delete(i.id)
                          else next.add(i.id)
                          setSkip(next)
                        }}
                      />
                    </td>
                    <td>
                      {i.number}
                      <div className="muted small">{i.subject}</div>
                    </td>
                    <td>
                      {i.holder}
                      <div className="muted small">{i.iban_masked}</div>
                    </td>
                    <td className="small">{i.mandate}</td>
                    <td className="num">{euro(i.outstanding)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid-3">
            <Field
              label="Einzugsdatum"
              type="date"
              required
              min={proposals.earliest}
              value={date}
              hint={`frühestens ${formatDate(proposals.earliest)} (Vorabankündigung ${proposals.prenotification_days} Tage)`}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <div className="aid-row">
            <Why k="collection_date" />
            <HowTo k="calc_earliest_collection" />
          </div>
          <Checklist title="Vor dem Lastschriftlauf" items={checks} />
          <div className="button-row">
            <button
              type="submit"
              className="button button-primary"
              disabled={busy || chosen.length === 0}
            >
              {chosen.length} Lastschriften über {euro(total)} erstellen
            </button>
          </div>
          <p className="muted small">
            Die Zahler bekommen die <Term k="prenotification_term">Vorabankündigung</Term> per
            E-Mail. Danach lädst du die <Term k="bank_file">Datei für die Bank</Term> herunter und
            reichst sie im Online-Banking ein. Eingezogen wird mit eurer{' '}
            <Term k="creditor_id">Gläubiger-ID</Term>.
          </p>
        </>
      )}
    </form>
  )
}

function RunCard({
  orgId,
  run,
  canEdit,
  onChanged,
}: {
  orgId: number
  run: DebitRun
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)
  // Einzelne Lastschriften erst beim Aufklappen erzeugen (Läufe können groß sein)
  const [open, setOpen] = useState(false)
  const unsent = run.items.filter((i) => !i.prenotified_at).length
  const problems = run.problems ?? []

  async function act(action: () => Promise<DebitRun>, text: (r: DebitRun) => string) {
    setBusy(true)
    setNotice(null)
    try {
      const r = await action()
      setNotice({ kind: 'success', text: text(r) })
      await onChanged()
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Lastschrift zum {formatDate(run.collection_date)}</h2>
        <span
          className={`status status-${run.status === 'booked' ? 'paid' : run.status === 'cancelled' ? 'cancelled' : 'open'}`}
        >
          {run.status_label}
        </span>
        <span className="muted small push-right">
          {run.items.length} Lastschriften · {euro(run.total)} · {run.account_name}
        </span>
      </div>
      <details onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>Einzelne Lastschriften</summary>
        {open && (
          <table className="table">
            <tbody>
              {run.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.invoice_number}</td>
                  <td>
                    {i.payer}
                    <div className="muted small">
                      {i.mandate_reference} ·{' '}
                      {i.sequence === 'FRST' ? 'Erstlastschrift' : 'Folgelastschrift'}
                      {i.prenotified_at ? ' · angekündigt per E-Mail' : ' · Ankündigung drucken'}
                    </div>
                  </td>
                  <td className="num">{euro(i.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      {problems.length > 0 && (
        <Alert kind="error">
          Die Datei für die Bank passt nicht mehr zum Stand: {problems.join('; ')}. Bitte den Lauf
          verwerfen und neu erstellen.
        </Alert>
      )}
      {run.status !== 'cancelled' && (
        <div className="button-row">
          {problems.length === 0 && (
            <a className="button button-primary" href={sepaApi.xmlUrl(orgId, run.id)}>
              Datei für die Bank (SEPA-XML)
            </a>
          )}
          {unsent > 0 && (
            <a
              className="button button-ghost"
              href={sepaApi.prenotificationsUrl(orgId, run.id)}
              target="_blank"
              rel="noreferrer"
            >
              {unsent} Ankündigungen drucken
            </a>
          )}
          {canEdit && run.status === 'created' && (
            <>
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={async () => {
                  if (
                    await confirmDialog({
                      title: 'Hat die Bank die Lastschriften eingezogen?',
                      message:
                        'Dann werden die Zahlungen gebucht und die Rechnungen als bezahlt markiert.',
                      confirmLabel: 'Zahlungen buchen',
                      danger: false,
                    })
                  )
                    void act(
                      () => sepaApi.bookRun(orgId, run.id),
                      (r) => `${r.booked} Zahlungen gebucht.`,
                    )
                }}
              >
                Als eingezogen buchen
              </button>
              <button
                type="button"
                className="button button-danger push-right"
                disabled={busy}
                onClick={async () => {
                  if (
                    await confirmDialog({
                      title: 'Lastschriftlauf verwerfen?',
                      message: 'Die Rechnungen bleiben offen.',
                      confirmLabel: 'Verwerfen',
                    })
                  )
                    void act(
                      () => sepaApi.cancelRun(orgId, run.id),
                      () => 'Verworfen.',
                    )
                }}
              >
                Verwerfen
              </button>
            </>
          )}
        </div>
      )}
      {run.status === 'booked' && (
        <p className="muted small">
          Kommt eine Lastschrift zurück, entferne die Zahlung an der Rechnung. Die Buchung in der
          Kasse verschwindet dann mit.
        </p>
      )}
    </div>
  )
}

export function MandatesPage() {
  const org = useActiveOrg()
  return <MandatesCard orgId={org.id} canEdit={org.permissions.includes(PERM.billingEdit)} />
}

function MandatesCard({ orgId, canEdit }: { orgId: number; canEdit: boolean }) {
  const settings = useLoad(() => billingApi.settings(orgId), [orgId])
  const [term, setTerm] = useState('')
  const [search, setSearch] = useState('')
  const { data, error, reload } = useLoad(
    () => sepaApi.mandates(orgId, { suche: search }),
    [orgId, search],
  )
  const [adding, setAdding] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)

  async function revoke(m: Mandate) {
    if (
      !(await confirmDialog({
        title: `Mandat ${m.reference} als widerrufen markieren?`,
        confirmLabel: 'Widerrufen',
      }))
    )
      return
    try {
      await sepaApi.revokeMandate(orgId, m.id)
      setNotice({ kind: 'success', text: 'Widerrufen.' })
      await reload()
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>
          <Term k="mandate">Mandate</Term>
        </h2>
        {canEdit && !adding && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setAdding(true)}
          >
            Mandat erfassen
          </button>
        )}
      </div>
      {adding && settings.data && (
        <MandateForm
          orgId={orgId}
          federation={settings.data.org_type === 'federation'}
          clubs={settings.data.clubs}
          onCancel={() => setAdding(false)}
          onSaved={async (m) => {
            setAdding(false)
            setNotice({ kind: 'success', text: `Mandat ${m.reference} gespeichert.` })
            await reload()
          }}
        />
      )}
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault()
          setSearch(term.trim())
        }}
      >
        <input
          type="search"
          aria-label="Mandate durchsuchen"
          placeholder="Name, Kontoinhaber oder Mandatsreferenz"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
      </form>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
      <HowTo k="calc_mandate_expiry" />
      {data && data.results.length === 0 && <p className="muted">Keine Mandate.</p>}
      {data && data.results.length > 0 && (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Zahler</th>
                <th>
                  <Term k="mandate_reference">Mandatsreferenz</Term>
                </th>
                <th>
                  <Term k="iban_bic">Konto</Term>
                </th>
                <th>erteilt</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.results.map((m) => (
                <tr key={m.id} className={m.status === 'active' ? undefined : 'muted'}>
                  <td>{m.payer_name}</td>
                  <td className="small">{m.reference}</td>
                  <td>
                    {m.holder}
                    <div className="muted small">{m.iban_masked}</div>
                  </td>
                  <td>
                    {formatDate(m.signed_on)}
                    <div className="muted small">{m.source_label}</div>
                  </td>
                  <td>
                    {m.expired ? (
                      <Term k="mandate_expiry">verfallen (36 Monate ungenutzt)</Term>
                    ) : (
                      m.status_label
                    )}
                    {m.last_used_on && (
                      <div className="muted small">zuletzt {formatDate(m.last_used_on)}</div>
                    )}
                  </td>
                  <td className="actions">
                    {canEdit && m.status === 'active' && (
                      <button type="button" className="link-button" onClick={() => void revoke(m)}>
                        Widerrufen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function MandateForm({
  orgId,
  federation,
  clubs,
  onCancel,
  onSaved,
}: {
  orgId: number
  federation: boolean
  clubs: { id: number; name: string }[]
  onCancel: () => void
  onSaved: (m: Mandate) => Promise<void>
}) {
  const tm = useTerms()
  const [member, setMember] = useState<MemberRow | null>(null)
  const [club, setClub] = useState('')
  const [holder, setHolder] = useState('')
  const [iban, setIban] = useState('')
  const [bic, setBic] = useState('')
  const [signedOn, setSignedOn] = useState(todayIso)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setErrors({})
    try {
      await onSaved(
        await sepaApi.createMandate(orgId, {
          membership: federation ? null : (member?.id ?? null),
          club: federation ? Number(club) || null : null,
          holder,
          iban,
          bic,
          signed_on: signedOn,
        }),
      )
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors)
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="subcard" onSubmit={save}>
      <h3>Schriftliches Mandat erfassen</h3>
      <Why k="paper_mandate" />
      <div className="grid-3">
        {federation ? (
          <SelectField
            label={tm.Sg}
            value={club}
            error={errors.club}
            onChange={(e) => setClub(e.target.value)}
          >
            <option value="">bitte wählen</option>
            {clubs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
        ) : (
          <MemberPicker
            orgId={orgId}
            value={member}
            onChange={(m) => {
              setMember(m)
              if (m && !holder) setHolder(`${m.first_name} ${m.last_name}`)
            }}
            label="Mitglied"
          />
        )}
        <Field
          label="Kontoinhaber"
          required
          value={holder}
          error={errors.holder}
          onChange={(e) => setHolder(e.target.value)}
        />
        <Field
          label="IBAN"
          required
          value={iban}
          error={errors.iban}
          onChange={(e) => setIban(e.target.value)}
        />
        <Field
          label="BIC (optional)"
          value={bic}
          error={errors.bic}
          onChange={(e) => setBic(e.target.value)}
        />
        <Field
          label="unterschrieben am"
          type="date"
          required
          value={signedOn}
          error={errors.signed_on}
          onChange={(e) => setSignedOn(e.target.value)}
        />
      </div>
      <p className="muted small">
        Das unterschriebene Formular bitte aufbewahren. Ein neues Mandat ersetzt ein älteres des
        gleichen Zahlers.
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={busy}>
          Speichern
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          Abbrechen
        </button>
      </div>
    </form>
  )
}
