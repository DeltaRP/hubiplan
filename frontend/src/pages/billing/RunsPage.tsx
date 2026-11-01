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
import { t, tn } from '../../i18n/index.ts'

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
  if (!settings.data || !runs.data) return <p className="muted">{t('Lädt …')}</p>
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
              {t('Neuer Beitragslauf')}
            </button>
          </div>
        ))}
      {runs.data.length === 0 && !creating && (
        <div className="card empty-state">
          <p>{t('Noch kein Beitragslauf.')}</p>
          <p className="muted small">
            {s.org_type === 'federation'
              ? t(
                  'Ein Beitragslauf erstellt für einen Abrechnungszeitraum die Rechnungen an alle {pl}, berechnet aus ihren gemeldeten Mitgliedern.',
                  { pl: tm.pl },
                )
              : t(
                  'Ein Beitragslauf erstellt für einen Abrechnungszeitraum die Rechnungen an alle Mitglieder und Sammelrechnungen an die {department_label_plural}.',
                  { department_label_plural: s.department_label_plural },
                )}{' '}
            {t('Vorher bitte die')}{' '}
            <Link to="/finanzen/einstellungen/beitraege">{t('Beitragssätze')}</Link> festlegen.
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
        {t('Neuer')} <Term k="fee_run">{t('Beitragslauf')}</Term>
      </h2>
      <div className="grid-3">
        <SelectField
          label={t('Geschäftsjahr')}
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
          label={t('Zeitraum')}
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
          label={t('Rechnungsdatum')}
          type="date"
          required
          value={invoiceDate}
          hint={t('fällig nach {due_days} Tagen', { due_days: settings.due_days })}
          onChange={(e) => setInvoiceDate(e.target.value)}
        />
      </div>
      <Why k="invoice_date" />
      {preview && (
        <div className="subcard">
          <h3>
            {t('Vorschau')} {preview.label}
          </h3>
          {preview.exists && (
            <Alert kind="error">{t('Für diesen Zeitraum gibt es schon einen Beitragslauf.')}</Alert>
          )}
          {federation ? (
            <>
              <ul>
                {(preview.clubs ?? []).map((c) => (
                  <li key={c.id}>
                    {c.name}
                    {t(': {members} gemeldete Mitglieder,', { members: c.members })} {euro(c.total)}
                  </li>
                ))}
              </ul>
              {(preview.clubs ?? []).length === 0 && (
                <p className="muted">
                  {t('Keine Rechnungen. Sind unter Beitragsregeln Beträge je Mitglied hinterlegt?')}
                </p>
              )}
              <p>
                <strong>
                  {t('Gesamt:')} {euro(preview.clubs_total ?? '0')}
                </strong>
              </p>
            </>
          ) : (
            <>
              <ul>
                <li>
                  {preview.members} {t('Rechnungen an Mitglieder, zusammen')}{' '}
                  {euro(preview.members_total ?? '0')}
                </li>
                {(preview.departments ?? []).map((d) => (
                  <li key={d.id}>
                    <Term k="collective_invoice">{t('Sammelrechnung')}</Term> {d.name}
                    {t(': {members}  Mitglieder,', { members: d.members })} {euro(d.total)}
                  </li>
                ))}
              </ul>
              <p>
                <strong>
                  {t('Gesamt:')} {euro(Number(preview.members_total ?? 0) + deptTotal)}
                </strong>
              </p>
            </>
          )}
          {!federation && settings.pro_rata && <HowTo k="calc_pro_rata" />}
          {!federation && (
            <Checklist
              title={t('Vor dem Beitragslauf')}
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
              <summary>
                {preview.skipped.length} {t('Mitglieder ohne Beitrag')}
              </summary>
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
          {t('Vorschau berechnen')}
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={busy || !preview || preview.exists}
        >
          {t('Rechnungsentwürfe erstellen')}
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          {t('Abbrechen')}
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
        <h2>
          {t('Beitragslauf')} {run.label}
        </h2>
        <span className="muted small push-right">
          {t('Rechnungsdatum {x} · fällig', { x: formatDate(run.invoice_date) })}{' '}
          {formatDate(run.due_date)}
        </span>
      </div>
      <RunSteps run={run} />
      <dl className="facts">
        <dt>{t('Entwürfe')}</dt>
        <dd>
          {s.counts.draft} ({euro(s.totals.draft)})
        </dd>
        <dt>{t('Festgeschrieben')}</dt>
        <dd>
          {active} {t('Rechnungen über')} {euro(total)}
          {!federation &&
            t(', davon {departments} an {deptLabel}', {
              departments: s.departments,
              deptLabel,
            })}{' '}
          {t('· bezahlt')} {euro(s.paid)}
        </dd>
        {!federation && (
          <>
            <dt>{t('Mitglieder')}</dt>
            <dd>{s.members}</dd>
          </>
        )}
        <dt>{t('Versand')}</dt>
        <dd>
          {s.unsent_with_email > 0
            ? t('{unsent_with_email} noch per E-Mail zu verschicken', {
                unsent_with_email: s.unsent_with_email,
              })
            : active > 0
              ? t('E-Mails versendet')
              : t('noch nichts festgeschrieben')}
          {s.without_email > 0 &&
            tn(
              ' · {n} Rechnung für den Postversand',
              ' · {n} Rechnungen für den Postversand',
              s.without_email,
            ) +
              (run.post_done_at
                ? t(' (erledigt am {x})', { x: formatDate(run.post_done_at) })
                : t(' (noch nicht als erledigt vermerkt)'))}
        </dd>
      </dl>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <div className="button-row">
        <Link className="button button-ghost" to={`/finanzen/rechnungen?lauf=${run.id}`}>
          {t('Rechnungen ansehen')}
        </Link>
        {canEdit && s.counts.draft > 0 && (
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={async () => {
              if (
                await confirmDialog({
                  title: t('{draft} Entwürfe festschreiben?', { draft: s.counts.draft }),
                  message: t(
                    'Sie bekommen dann Rechnungsnummern und lassen sich nur noch stornieren.',
                  ),
                  confirmLabel: t('Festschreiben'),
                  danger: false,
                })
              )
                void act(
                  () => billingApi.finalizeRun(orgId, run.id),
                  (r) => t('{finalized} Rechnungen festgeschrieben.', { finalized: r.finalized }),
                )
            }}
          >
            {t('Entwürfe festschreiben')}
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
                  t('{sent} Rechnungen verschickt.', { sent: r.sent }) +
                  (r.failed
                    ? t(' {failed} konnten nicht verschickt werden.', { failed: r.failed })
                    : ''),
              )
            }
          >
            {s.unsent_with_email} {t('per E-Mail verschicken')}
          </button>
        )}
        {s.without_email > 0 && active > 0 && (
          <a
            className="button button-ghost"
            href={billingApi.runPdfUrl(orgId, run.id, 'ohne_email')}
          >
            {t('Rechnungen ohne E-Mail drucken (PDF)')}
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
                    ? t('Postversand als erledigt vermerkt.')
                    : t('Vermerk zum Postversand zurückgenommen.'),
              )
            }
          >
            {run.post_done_at ? t('Postversand doch nicht erledigt') : t('Postversand erledigt')}
          </button>
        )}
        {s.counts.draft > 0 && (
          <a
            className="button button-ghost"
            href={billingApi.runPdfUrl(orgId, run.id, 'entwuerfe')}
          >
            {t('Entwürfe ansehen (PDF)')}
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
                      title: t('Handänderungen verwerfen?'),
                      message: err.message,
                      confirmLabel: t('Neu berechnen'),
                    })
                    if (!ok) return null
                    return billingApi.rebuildRun(orgId, run.id, true)
                  }
                },
                (r) =>
                  r.created
                    ? t('{created} Entwürfe neu berechnet.', { created: r.created })
                    : federation
                      ? t('Alle {pl} sind abgerechnet.', { pl: tm.pl })
                      : t('Alle Mitglieder sind abgerechnet.'),
              )
            }
          >
            {active > 0 ? t('Nachzügler abrechnen') : t('Entwürfe neu berechnen')}
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
                  title: t('Beitragslauf {label} mit allen Entwürfen löschen?', {
                    label: run.label,
                  }),
                  confirmLabel: t('Löschen'),
                })
              )
                void act(
                  () => billingApi.deleteRun(orgId, run.id),
                  () => t('Gelöscht.'),
                )
            }}
          >
            {t('Löschen')}
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
    { label: t('Vorbereiten'), done: true },
    { label: t('Entwürfe prüfen'), done: reviewed },
    { label: t('Festschreiben'), done: finalized },
    { label: t('Versenden'), done: sent },
    { label: t('Zahlungen'), done: sent && s.counts.open === 0 },
  ]
}

function RunSteps({ run }: { run: FeeRun }) {
  const steps = runSteps(run)
  const current = steps.findIndex((st) => !st.done)
  return (
    <ol className="run-steps" aria-label={t('Stand des Beitragslaufs')}>
      {steps.map((st, i) => (
        <li
          key={st.label}
          className={st.done ? 'done' : i === current ? 'current' : undefined}
          aria-current={i === current ? 'step' : undefined}
        >
          <span className="sr-only">
            {st.done ? 'erledigt: ' : i === current ? 'jetzt: ' : t('später: ')}
          </span>
          {st.label}
        </li>
      ))}
    </ol>
  )
}
