// Verein: Rechnungen des Dachverbands an den Verein.
import { billingApi } from '../../api/billing.ts'
import { euro } from '../../api/finance.ts'
import { formatDate, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { StatusBadge } from './InvoicesPage.tsx'

export function ReceivedPage() {
  const org = useActiveOrg()
  const terms = useTerms()
  const { data, error } = useLoad(() => billingApi.received(org.id), [org.id])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  if (!data.federation)
    return (
      <div className="card empty-state">
        <p>{terms.e_Nom} gehört zu keiner übergeordneten Einheit.</p>
      </div>
    )
  return (
    <div className="card card-wide">
      <h2>Rechnungen von {data.federation}</h2>
      {data.invoices.length === 0 ? (
        <p className="muted">Noch keine Rechnungen.</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Nummer</th>
                <th>Betreff</th>
                <th>fällig</th>
                <th>Status</th>
                <th className="num">Betrag</th>
                <th className="num">offen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.invoices.map((inv) => (
                <tr key={inv.id}>
                  <td>{inv.number}</td>
                  <td>
                    {inv.subject}
                    <div className="muted small">
                      {inv.lines.map((l) => `${l.text} ${l.detail}`.trim()).join(' · ')}
                      {inv.dunnings.length > 0 &&
                        ` · ${inv.dunnings[inv.dunnings.length - 1].name} vom ${formatDate(
                          inv.dunnings[inv.dunnings.length - 1].date,
                        )}`}
                    </div>
                  </td>
                  <td>{formatDate(inv.due_date)}</td>
                  <td>
                    <StatusBadge row={inv} />
                  </td>
                  <td className="num">{euro(inv.total)}</td>
                  <td className="num">{Number(inv.outstanding) ? euro(inv.outstanding) : '–'}</td>
                  <td className="actions">
                    <a
                      className="link-button"
                      href={billingApi.receivedPdfUrl(org.id, inv.id)}
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
        </div>
      )}
      <p className="muted small">
        Die Zahlung an {terms.dv_akk} buchst du wie jede Ausgabe in der Kasse.
      </p>
    </div>
  )
}
