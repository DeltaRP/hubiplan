// Beiträge: Beitragslauf vorbereiten, festschreiben, verschicken, drucken.
import { todayIso } from '../../api/members.ts'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { billingApi } from '../../api/billing.ts'
import { ApiError } from '../../api/client.ts'
import type { BillingSettings, FeeRun, RunPreview } from '../../api/billing.ts'
import { euro } from '../../api/finance.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Field, SelectField, LoadError } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { useTerms } from '../../org/terms.ts'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { Checklist } from '../../learning/Checklist.tsx'
import { feeRunChecks } from '../../learning/checks.ts'

export function RunsPage() {
  const tm = useTerms()
  const org = useActiveOrg()
  const settings = useLoad(() => billingApi.settings(org.id), [org.id])
  const runs = useLoad(() => billingApi.runs(org.id), [org.id])
  const [creating, setCreating] = useState(false)

  if (settings.error ?? runs.error)
    return (
      <LoadError
        message={(settings.error ?? runs.error) as string}
        onRetry={() => void Promise.all([settings.reload(), runs.reload()])}
      />
    )
  if (!settings.data || !runs.data) return <p className="muted">Lädt …</p>
  const s = settings.data

  return (
    <div className="stack">
      {s.can_edit &&
        (creating ? (
          <NewRun
            settings={s}
            onCancel={() => setCreating(false)}
            onCreated={async () => {
              setCreating(false)
              await runs.reload()
            }}
          />
        ) : (
          <div>
            <button
              type="button"
              className="button button-primary"
              onClick={() => setCreating(true)}
            >
              Neuer Beitragslauf
            </button>
          </div>
        ))}
      {runs.data.length === 0 && !creating && (
        <div className="card empty-state">
          <p>Noch kein Beitragslauf.</p>
          <p className="muted small">
            {s.org_type === 'federation'
              ? `Ein Beitragslauf erstellt für einen Abrechnungszeitraum die Rechnungen an alle ${tm.pl}, berechnet aus ihren gemeldeten Mitgliedern.`
              : `Ein Beitragslauf erstellt für einen Abrechnungszeitraum die Rechnungen an alle Mitglieder und Sammelrechnungen an die ${s.department_label_plural}.`}{' '}
            Vorher bitte die <Link to="/finanzen/einstellungen/beitraege">Beitragssätze</Link>{' '}
            festlegen.
          </p>
        </div>
      )}
      {runs.data.map((run) => (
        <RunCard
          key={run.id}
          orgId={org.id}
          run={run}
          canEdit={s.can_edit}
          deptLabel={tm.Pl}
          federation={s.org_type === 'federation'}
          onChanged={runs.reload}
        />
      ))}
    </div>
  )
}

function NewRun({
  settings,
  onCancel,
  onCreated,
}: {
  settings: BillingSettings
  onCancel: () => void
  onCreated: () => void
}) {
  const org = useActiveOrg()
  const [year, setYear] = useState(settings.current_year)
  const periods = settings.periods[String(year)] ?? []
  const [period, setPeriod] = useState(1)
  const [invoiceDate, setInvoiceDate] = useState(todayIso)
  const [preview, setPreview] = useState<RunPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function check() {
    setError(null)
    try {
      setPreview(await billingApi.preview(org.id, year, period))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await billingApi.createRun(org.id, { year, period, invoice_date: invoiceDate })
      onCreated()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const deptTotal = (preview?.departments ?? []).reduce((sum, d) => sum + Number(d.total), 0)
  const federation = settings.org_type === 'federation'

  return (
    <form className="card card-wide" onSubmit={create}>
      <h2>
        Neuer <Term k="fee_run">Beitragslauf</Term>
      </h2>
      <div className="grid-3">
        <SelectField
          label="Geschäftsjahr"
          value={year}
          onChange={(e) => {
            setYear(Number(e.target.value))
            setPeriod(1)
            setPreview(null)
          }}
        >
          {settings.years.map((y) => (
            <option key={y.year} value={y.year}>
              {y.label}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Zeitraum"
          value={period}
          onChange={(e) => {
            setPeriod(Number(e.target.value))
            setPreview(null)
          }}
        >
          {periods.map((p) => (
            <option key={p.index} value={p.index}>
              {p.label} ({formatDate(p.start)} bis {formatDate(p.end)})
            </option>
          ))}
        </SelectField>
        <Field
          label="Rechnungsdatum"
          type="date"
          required
          value={invoiceDate}
          hint={`fällig nach ${settings.due_days} Tagen`}
          onChange={(e) => setInvoiceDate(e.target.value)}
        />
      </div>
      <Why k="invoice_date" />
      {preview && (
        <div className="subcard">
          <h3>Vorschau {preview.label}</h3>
          {preview.exists && (
            <Alert kind="error">Für diesen Zeitraum gibt es schon einen Beitragslauf.</Alert>
          )}
          {federation ? (
            <>
              <ul>
                {(preview.clubs ?? []).map((c) => (
                  <li key={c.id}>
                    {c.name}: {c.members} gemeldete Mitglieder, {euro(c.total)}
                  </li>
                ))}
              </ul>
              {(preview.clubs ?? []).length === 0 && (
                <p className="muted">
                  Keine Rechnungen. Sind unter Beitragsregeln Beträge je Mitglied hinterlegt?
                </p>
              )}
              <p>
                <strong>Gesamt: {euro(preview.clubs_total ?? '0')}</strong>
              </p>
            </>
          ) : (
            <>
              <ul>
                <li>
                  {preview.members} Rechnungen an Mitglieder, zusammen{' '}
                  {euro(preview.members_total ?? '0')}
                </li>
                {(preview.departments ?? []).map((d) => (
                  <li key={d.id}>
                    <Term k="collective_invoice">Sammelrechnung</Term> {d.name}: {d.members}{' '}
                    Mitglieder, {euro(d.total)}
                  </li>
                ))}
              </ul>
              <p>
                <strong>Gesamt: {euro(Number(preview.members_total ?? 0) + deptTotal)}</strong>
              </p>
            </>
          )}
          {!federation && settings.pro_rata && <HowTo k="calc_pro_rata" />}
          {!federation && (
            <Checklist
              title="Vor dem Beitragslauf"
              items={feeRunChecks({
                skipped: preview.skipped ?? [],
                members: preview.members ?? 0,
                dueDays: settings.due_days,
                accountWithIban: settings.accounts.some(
                  (a) => a.id === settings.account && a.has_iban,
                ),
                sepaEnabled: settings.sepa_enabled,
                checks: preview.checks,
              })}
            />
          )}
          {preview.skipped && preview.skipped.length > 0 && (
            <details>
              <summary>{preview.skipped.length} Mitglieder ohne Beitrag</summary>
              <ul className="small">
                {preview.skipped.map((s) => (
                  <li key={s.membership}>
                    {s.name}: {s.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="button" className="button button-ghost" onClick={() => void check()}>
          Vorschau berechnen
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={busy || !preview || preview.exists}
        >
          Rechnungsentwürfe erstellen
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          Abbrechen
        </button>
      </div>
    </form>
  )
}

function RunCard({
  orgId,
  run,
  canEdit,
  deptLabel,
  federation,
  onChanged,
}: {
  orgId: number
  run: FeeRun
  canEdit: boolean
  deptLabel: string
  federation: boolean
  onChanged: () => Promise<void>
}) {
  const tm = useTerms()
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const s = run.summary
  const active = s.counts.open + s.counts.paid
  const total = Number(s.totals.open) + Number(s.totals.paid)

  async function act(action: () => Promise<FeeRun | unknown>, text: (r: FeeRun) => string) {
    setBusy(true)
    setNotice(null)
    try {
      const result = (await action()) as FeeRun | null
      // null: bewusst abgebrochen, keine Meldung (UI-Audit NAF-08)
      if (result === null) return
      await onChanged()
      setNotice({ kind: 'success', text: text(result) })
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Beitragslauf {run.label}</h2>
        <span className="muted small push-right">
          Rechnungsdatum {formatDate(run.invoice_date)} · fällig {formatDate(run.due_date)}
        </span>
      </div>
      <RunSteps run={run} />
      <dl className="facts">
        <dt>Entwürfe</dt>
        <dd>
          {s.counts.draft} ({euro(s.totals.draft)})
        </dd>
        <dt>Festgeschrieben</dt>
        <dd>
          {active} Rechnungen über {euro(total)}
          {!federation && `, davon ${s.departments} an ${deptLabel}`} · bezahlt {euro(s.paid)}
        </dd>
        {!federation && (
          <>
            <dt>Mitglieder</dt>
            <dd>{s.members}</dd>
          </>
        )}
        <dt>Versand</dt>
        <dd>
          {s.unsent_with_email > 0
            ? `${s.unsent_with_email} noch per E-Mail zu verschicken`
            : active > 0
              ? 'E-Mails versendet'
              : 'noch nichts festgeschrieben'}
          {s.without_email > 0 &&
            ` · ${s.without_email} ${s.without_email === 1 ? 'Rechnung' : 'Rechnungen'} für den Postversand` +
              (run.post_done_at
                ? ` (erledigt am ${formatDate(run.post_done_at)})`
                : ' (noch nicht als erledigt vermerkt)')}
        </dd>
      </dl>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <div className="button-row">
        <Link className="button button-ghost" to={`/finanzen/rechnungen?lauf=${run.id}`}>
          Rechnungen ansehen
        </Link>
        {canEdit && s.counts.draft > 0 && (
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={async () => {
              if (
                await confirmDialog({
                  title: `${s.counts.draft} Entwürfe festschreiben?`,
                  message:
                    'Sie bekommen dann Rechnungsnummern und lassen sich nur noch stornieren.',
                  confirmLabel: 'Festschreiben',
                  danger: false,
                })
              )
                void act(
                  () => billingApi.finalizeRun(orgId, run.id),
                  (r) => `${r.finalized} Rechnungen festgeschrieben.`,
                )
            }}
          >
            Entwürfe festschreiben
          </button>
        )}
        {canEdit && s.unsent_with_email > 0 && (
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() =>
              void act(
                () => billingApi.sendRun(orgId, run.id),
                (r) =>
                  `${r.sent} Rechnungen verschickt.` +
                  (r.failed ? ` ${r.failed} konnten nicht verschickt werden.` : ''),
              )
            }
          >
            {s.unsent_with_email} per E-Mail verschicken
          </button>
        )}
        {s.without_email > 0 && active > 0 && (
          <a
            className="button button-ghost"
            href={billingApi.runPdfUrl(orgId, run.id, 'ohne_email')}
          >
            Rechnungen ohne E-Mail drucken (PDF)
          </a>
        )}
        {canEdit && s.without_email > 0 && active > 0 && (
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() =>
              void act(
                () => billingApi.postDone(orgId, run.id, !run.post_done_at),
                (r) =>
                  r.post_done_at
                    ? 'Postversand als erledigt vermerkt.'
                    : 'Vermerk zum Postversand zurückgenommen.',
              )
            }
          >
            {run.post_done_at ? 'Postversand doch nicht erledigt' : 'Postversand erledigt'}
          </button>
        )}
        {s.counts.draft > 0 && (
          <a
            className="button button-ghost"
            href={billingApi.runPdfUrl(orgId, run.id, 'entwuerfe')}
          >
            Entwürfe ansehen (PDF)
          </a>
        )}
        {canEdit && (
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() =>
              void act(
                async () => {
                  try {
                    return await billingApi.rebuildRun(orgId, run.id)
                  } catch (err) {
                    // Von Hand geänderte Entwürfe: erst nachfragen
                    if (!(err instanceof ApiError) || err.status !== 409) throw err
                    const ok = await confirmDialog({
                      title: 'Handänderungen verwerfen?',
                      message: err.message,
                      confirmLabel: 'Neu berechnen',
                    })
                    if (!ok) return null
                    return billingApi.rebuildRun(orgId, run.id, true)
                  }
                },
                (r) =>
                  r.created
                    ? `${r.created} Entwürfe neu berechnet.`
                    : federation
                      ? `Alle ${tm.pl} sind abgerechnet.`
                      : 'Alle Mitglieder sind abgerechnet.',
              )
            }
          >
            {active > 0 ? 'Nachzügler abrechnen' : 'Entwürfe neu berechnen'}
          </button>
        )}
        {canEdit && active === 0 && (
          <button
            type="button"
            className="button button-danger push-right"
            disabled={busy}
            onClick={async () => {
              if (
                await confirmDialog({
                  title: `Beitragslauf ${run.label} mit allen Entwürfen löschen?`,
                  confirmLabel: 'Löschen',
                })
              )
                void act(
                  () => billingApi.deleteRun(orgId, run.id),
                  () => 'Gelöscht.',
                )
            }}
          >
            Löschen
          </button>
        )}
      </div>
    </div>
  )
}

/** Stand eines Beitragslaufs als Schrittfolge (H-AF-01). */
function runSteps(run: FeeRun): { label: string; done: boolean }[] {
  const s = run.summary
  const active = s.counts.open + s.counts.paid
  const reviewed = active > 0
  const finalized = active > 0 && s.counts.draft === 0
  // Versendet erst, wenn auch die Post raus ist (UI-Audit NAF-06)
  const sent =
    finalized && s.unsent_with_email === 0 && (s.without_email === 0 || !!run.post_done_at)
  return [
    { label: 'Vorbereiten', done: true },
    { label: 'Entwürfe prüfen', done: reviewed },
    { label: 'Festschreiben', done: finalized },
    { label: 'Versenden', done: sent },
    { label: 'Zahlungen', done: sent && s.counts.open === 0 },
  ]
}

function RunSteps({ run }: { run: FeeRun }) {
  const steps = runSteps(run)
  const current = steps.findIndex((st) => !st.done)
  return (
    <ol className="run-steps" aria-label="Stand des Beitragslaufs">
      {steps.map((st, i) => (
        <li
          key={st.label}
          className={st.done ? 'done' : i === current ? 'current' : undefined}
          aria-current={i === current ? 'step' : undefined}
        >
          <span className="sr-only">
            {st.done ? 'erledigt: ' : i === current ? 'jetzt: ' : 'später: '}
          </span>
          {st.label}
        </li>
      ))}
    </ol>
  )
}
