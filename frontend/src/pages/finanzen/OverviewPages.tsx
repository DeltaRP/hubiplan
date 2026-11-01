// Finanzen: Übersicht (Startseite des Bereichs) und Auswertung je Geschäftsjahr.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { billingApi } from '../../api/billing.ts'
import { euro, financeApi } from '../../api/finance.ts'
import { PERM } from '../../api/orgs.ts'
import type { Overview } from '../../api/finance.ts'
import { formatDate, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import type { FinanceAccess } from './access.ts'
import { HowTo, Term } from '../../learning/Aids.tsx'
import type { TermKey } from '../../learning/content.ts'

/** Steuerliche Bereiche und ihre Begriffe im Glossar */
const AREA_TERMS: Record<string, TermKey> = {
  ideal: 'ideal_area',
  assets: 'asset_management',
  purpose: 'purpose_operation',
  business: 'commercial_operation',
}

/** Kassenzahlen eines Geschäftsjahres; ohne Auswahl das laufende. */
function useFinanceYear() {
  const org = useActiveOrg()
  const [year, setYear] = useState<number | null>(null)
  const settings = useLoad(() => financeApi.settings(org.id), [org.id])
  const current = year ?? settings.data?.current_year ?? null
  const overview = useLoad(
    () => (current === null ? Promise.resolve(null) : financeApi.overview(org.id, current)),
    [org.id, current],
  )
  return { org, data: overview.data, error: settings.error ?? overview.error, setYear }
}

function YearSelect({ data, onChange }: { data: Overview; onChange: (y: number) => void }) {
  return (
    <select
      aria-label="Geschäftsjahr"
      value={data.year}
      onChange={(e) => onChange(Number(e.target.value))}
    >
      {data.years.map((y) => (
        <option key={y.year} value={y.year}>
          Geschäftsjahr {y.label}
        </option>
      ))}
    </select>
  )
}

function NoAccounts({ canEdit }: { canEdit: boolean }) {
  return (
    <div className="card empty-state">
      <p>Noch keine Konten angelegt.</p>
      {canEdit && (
        <p>
          <Link to="/finanzen/einstellungen/konten">Erstes Konto anlegen</Link> – zum Beispiel
          Girokonto und Barkasse mit ihrem Anfangsbestand.
        </p>
      )}
    </div>
  )
}

/** Arbeitsschritte im Jahreslauf, mit direktem Weg zur jeweiligen Liste (H-AF-01). */
function financeSteps(a: FinanceAccess): { title: string; text: string; to: string }[] {
  const steps: { title: string; text: string; to: string }[] = []
  if (a.billingEdit || a.financeEdit)
    steps.push({
      title: 'Einrichten',
      text: a.billing ? 'Beitragssätze, Zahlungsangaben, Konten' : 'Konten und Kategorien',
      to: '/finanzen/einstellungen',
    })
  if (a.billing)
    steps.push({
      title: 'Beiträge abrechnen',
      text: a.feeRuns
        ? 'Beitragslauf anlegen, prüfen, festschreiben, versenden'
        : 'Rechnungen schreiben',
      to: a.feeRuns ? '/finanzen/rechnungen/beitragslaeufe' : '/finanzen/rechnungen',
    })
  if (a.billing)
    steps.push({
      title: 'Zahlungen verarbeiten',
      text: a.sepa ? 'Lastschrift einziehen, Eingänge buchen, mahnen' : 'Eingänge buchen, mahnen',
      to: a.sepa ? '/finanzen/lastschrift' : '/finanzen/rechnungen?status=open',
    })
  if (a.finance)
    steps.push({
      title: 'Buchen',
      text: 'Einnahmen und Ausgaben mit Beleg erfassen',
      to: '/finanzen/kassenbuch',
    })
  if (a.finance)
    steps.push({
      title: 'Jahr abschließen',
      text: 'Kassenbericht und Jahresabschluss',
      to: '/finanzen/abschluss',
    })
  return steps
}

function FinanceSteps({ access }: { access: FinanceAccess }) {
  const steps = financeSteps(access)
  if (steps.length < 2) return null
  return (
    <nav className="card card-wide" aria-labelledby="finanz-schritte">
      <h2 id="finanz-schritte">Arbeitsschritte</h2>
      <ol className="step-links">
        {steps.map((st) => (
          <li key={st.title}>
            <Link to={st.to}>
              <strong>{st.title}</strong>
              <span className="muted small">{st.text}</span>
            </Link>
          </li>
        ))}
      </ol>
    </nav>
  )
}

export function FinanceOverview({ access: a }: { access: FinanceAccess }) {
  return (
    <div className="stack">
      <FinanceSteps access={a} />
      {a.billing && <BillingSummary feeRuns={a.feeRuns} />}
      {a.received && <ReceivedSummary />}
      {a.finance && <CashSummary canEdit={a.financeEdit} />}
    </div>
  )
}

function BillingSummary({ feeRuns }: { feeRuns: boolean }) {
  const org = useActiveOrg()
  const { data, error } = useLoad(() => billingApi.overview(org.id), [org.id])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>

  const todo: { to: string; text: string }[] = []
  if (data.drafts.count > 0)
    todo.push({
      to: '/finanzen/rechnungen?status=draft',
      text: `${data.drafts.count} ${data.drafts.count === 1 ? 'Entwurf' : 'Entwürfe'} über ${euro(data.drafts.amount)} noch nicht festgeschrieben`,
    })
  if (data.dunnings_due > 0)
    todo.push({
      to: '/finanzen/rechnungen/mahnungen',
      text: `${data.dunnings_due} ${data.dunnings_due === 1 ? 'Rechnung ist' : 'Rechnungen sind'} zu mahnen`,
    })
  if (data.sepa_enabled && data.debits_ready > 0)
    todo.push({
      to: '/finanzen/lastschrift',
      text: `${data.debits_ready} ${data.debits_ready === 1 ? 'Rechnung kann' : 'Rechnungen können'} per Lastschrift eingezogen werden`,
    })
  for (const d of data.debits_pending)
    todo.push({
      to: '/finanzen/lastschrift',
      text: `Lastschrift zum ${formatDate(d.collection_date)} über ${euro(d.total)} noch nicht als bezahlt gebucht`,
    })

  return (
    <>
      <div className="tiles tiles-figures">
        <div className="card tile">
          <h2>Offene Rechnungen</h2>
          <p className="amount-big">{euro(data.open.amount)}</p>
          <Link className="small" to="/finanzen/rechnungen?status=open">
            {data.open.count} {data.open.count === 1 ? 'Rechnung' : 'Rechnungen'} ansehen
          </Link>
        </div>
        <div className="card tile">
          <h2>
            Davon <Term k="overdue">überfällig</Term>
          </h2>
          <p className={`amount-big${data.overdue.count > 0 ? ' amount-out' : ''}`}>
            {euro(data.overdue.amount)}
          </p>
          <Link className="small" to="/finanzen/rechnungen?status=open&ueberfaellig=1">
            {data.overdue.count} {data.overdue.count === 1 ? 'Rechnung' : 'Rechnungen'} ansehen
          </Link>
        </div>
        {feeRuns && (
          <div className="card tile">
            <h2>Letzter Beitragslauf</h2>
            <p className="amount-big">{data.last_run ? data.last_run.label : '–'}</p>
            <Link className="small" to="/finanzen/rechnungen/beitragslaeufe">
              {data.can_edit ? 'Beitragslauf starten' : 'Beitragsläufe ansehen'}
            </Link>
          </div>
        )}
      </div>
      <div className="card card-wide">
        <h2>Zu erledigen</h2>
        {todo.length === 0 ? (
          <p className="muted">Gerade ist nichts offen.</p>
        ) : (
          <ul className="todo-list">
            {todo.map((tm) => (
              <li key={tm.text}>
                <Link to={tm.to}>{tm.text}</Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  )
}

function ReceivedSummary() {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => billingApi.received(org.id), [org.id])
  if (error)
    return (
      <LoadError
        message={`Rechnungen vom Dachverband konnten nicht geladen werden (${error}).`}
        onRetry={reload}
      />
    )
  if (!data?.federation) return null
  const open = data.invoices.filter((i) => i.status === 'open' && Number(i.outstanding) > 0)
  if (open.length === 0) return null
  const sum = open.reduce((s, i) => s + Number(i.outstanding), 0)
  return (
    <Alert kind="info">
      {open.length === 1 ? 'Eine Rechnung' : `${open.length} Rechnungen`} von {data.federation}{' '}
      {open.length === 1 ? 'ist' : 'sind'} offen ({euro(sum.toFixed(2))}).{' '}
      <Link to="/finanzen/rechnungen/dachverband">Ansehen</Link>
    </Alert>
  )
}

function CashSummary({ canEdit }: { canEdit: boolean }) {
  const { data, error, setYear } = useFinanceYear()
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  if (data.accounts.length === 0) return <NoAccounts canEdit={canEdit} />
  const tm = data.totals
  return (
    <>
      <div className="card card-wide filters">
        <YearSelect data={data} onChange={setYear} />
        <span className="muted small">
          {formatDate(data.start_date)} bis {formatDate(data.end_date)} · {data.booking_count}{' '}
          Buchungen
        </span>
        <Link className="button button-ghost push-right" to="/finanzen/abschluss">
          Auswertung & Kassenbericht
        </Link>
      </div>
      <div className="tiles tiles-figures">
        <div className="card tile">
          <h2>Einnahmen {data.label}</h2>
          <p className="amount-big amount-in">{euro(tm.income)}</p>
        </div>
        <div className="card tile">
          <h2>Ausgaben {data.label}</h2>
          <p className="amount-big amount-out">{euro(tm.expense)}</p>
        </div>
        <div className="card tile">
          <h2>
            <Term k="result">Ergebnis</Term> {data.label}
          </h2>
          <p className={`amount-big ${Number(tm.result) < 0 ? 'amount-out' : 'amount-in'}`}>
            {euro(tm.result)}
          </p>
        </div>
      </div>
      <div className="card card-wide">
        <h2>Kontostände</h2>
        <table className="table">
          <tbody>
            {data.accounts.map((acc) => (
              <tr key={acc.id}>
                <td>
                  <Link to={`/finanzen/kassenbuch?konto=${acc.id}&jahr=${data.year}`}>
                    {acc.name}
                  </Link>
                  <div className="muted small">
                    {acc.kind_label}
                    {!acc.is_active && ' · inaktiv'}
                  </div>
                </td>
                <td className="num">
                  <strong>{euro(acc.end)}</strong>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th>Summe</th>
              <th className="num">{euro(tm.end)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
    </>
  )
}

/** Abschluss & Berichte › Auswertung: Konten, Kategorien, steuerliche Bereiche, Kassenbericht. */
export function EvaluationPage() {
  const { org, data, error, setYear } = useFinanceYear()
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  if (data.accounts.length === 0)
    return <NoAccounts canEdit={org.permissions.includes(PERM.financeEdit)} />
  const tm = data.totals
  return (
    <div className="stack">
      <div className="card card-wide filters">
        <YearSelect data={data} onChange={setYear} />
        <span className="muted small">
          {formatDate(data.start_date)} bis {formatDate(data.end_date)} · {data.booking_count}{' '}
          Buchungen
        </span>
        <a
          className="button button-ghost push-right"
          href={financeApi.reportUrl(org.id, data.year)}
          target="_blank"
          rel="noreferrer"
        >
          Kassenbericht (PDF)
        </a>
      </div>

      <div className="card card-wide">
        <h2>Konten</h2>
        <HowTo k="calc_closing_balance" />
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Konto</th>
                <th className="num">
                  <Term k="opening_balance_term">Anfangsbestand</Term>
                </th>
                <th className="num">Einnahmen</th>
                <th className="num">Ausgaben</th>
                <th className="num">
                  <Term k="transfer">Umbuchungen</Term>
                </th>
                <th className="num">
                  <Term k="closing_balance">Endbestand</Term>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link to={`/finanzen/kassenbuch?konto=${a.id}&jahr=${data.year}`}>
                      {a.name}
                    </Link>
                    <div className="muted small">
                      {a.kind_label}
                      {!a.is_active && ' · inaktiv'}
                    </div>
                  </td>
                  <td className="num">{euro(a.start)}</td>
                  <td className="num">{euro(a.income)}</td>
                  <td className="num">{euro(a.expense)}</td>
                  <td className="num">{euro(Number(a.transfer_in) - Number(a.transfer_out))}</td>
                  <td className="num">
                    <strong>{euro(a.end)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>Summe</th>
                <th className="num">{euro(tm.start)}</th>
                <th className="num">{euro(tm.income)}</th>
                <th className="num">{euro(tm.expense)}</th>
                <th />
                <th className="num">{euro(tm.end)}</th>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <div className="card card-wide">
        <h2>Nach Kategorie</h2>
        {data.categories.length === 0 ? (
          <p className="muted">Keine Einnahmen oder Ausgaben in {data.label}.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Kategorie</th>
                <th className="num">Einnahmen</th>
                <th className="num">Ausgaben</th>
                <th className="num">
                  <Term k="balance">Saldo</Term>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.categories.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/finanzen/kassenbuch?kategorie=${c.id}&jahr=${data.year}`}>
                      {c.name}
                    </Link>
                  </td>
                  <td className="num">{euro(c.income)}</td>
                  <td className="num">{euro(c.expense)}</td>
                  <td className="num">{euro(Number(c.income) - Number(c.expense))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data.tax_areas_enabled && data.tax_areas.length > 0 && (
        <div className="card card-wide">
          <h2>Nach steuerlichem Bereich</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Bereich</th>
                <th className="num">Einnahmen</th>
                <th className="num">Ausgaben</th>
                <th className="num">Ergebnis</th>
              </tr>
            </thead>
            <tbody>
              {data.tax_areas.map((a) => (
                <tr key={a.area || 'ohne'}>
                  <td>
                    {a.area && AREA_TERMS[a.area] ? (
                      <Term k={AREA_TERMS[a.area]}>{a.label}</Term>
                    ) : (
                      a.label
                    )}
                  </td>
                  <td className="num">{euro(a.income)}</td>
                  <td className="num">{euro(a.expense)}</td>
                  <td className="num">{euro(Number(a.income) - Number(a.expense))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
