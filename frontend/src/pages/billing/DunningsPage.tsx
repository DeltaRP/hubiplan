// Beiträge: fällige Mahnungen erstellen, verschicken und drucken.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { billingApi } from '../../api/billing.ts'
import { euro } from '../../api/finance.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, LoadError } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { PERM } from '../../api/orgs.ts'
import { Term, Why } from '../../learning/Aids.tsx'

export function DunningsPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.billingEdit)
  const { data, error, reload } = useLoad(() => billingApi.dunnings(org.id), [org.id])
  const [skip, setSkip] = useState<Set<number>>(new Set())
  const [send, setSend] = useState(true)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ text: string; unsent: number[] } | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>
  const chosen = data.proposals.filter((p) => !skip.has(p.id)).map((p) => p.id)

  async function run() {
    setBusy(true)
    setFailure(null)
    try {
      const r = await billingApi.dun(org.id, chosen, send)
      setResult({
        text:
          `${r.created} Mahnungen erstellt` +
          (send ? `, ${r.sent} per E-Mail verschickt.` : '.') +
          (r.unsent.length ? ` ${r.unsent.length} bitte ausdrucken.` : ''),
        unsent: r.unsent,
      })
      setSkip(new Set())
      await reload()
    } catch (err) {
      setFailure(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      {result && (
        <Alert kind="success">
          {result.text}{' '}
          {result.unsent.length > 0 && (
            <a
              href={billingApi.dunningPdfUrl(org.id, result.unsent)}
              target="_blank"
              rel="noreferrer"
            >
              Mahnungen zum Drucken (PDF)
            </a>
          )}
        </Alert>
      )}
      {data.levels.length === 0 ? (
        <div className="card empty-state">
          <p>Noch keine Mahnstufen.</p>
          <p className="muted small">
            Lege sie unter{' '}
            <Link to="/finanzen/einstellungen/mahnstufen">Einrichtung › Mahnstufen</Link> an, zum
            Beispiel eine Zahlungserinnerung 14 Tage nach Fälligkeit.
          </p>
        </div>
      ) : data.proposals.length === 0 ? (
        <div className="card empty-state">
          <p>Keine Mahnungen fällig.</p>
          <p className="muted small">
            Hier erscheinen offene Rechnungen, sobald die nächste Mahnstufe erreicht ist.
          </p>
        </div>
      ) : (
        <div className="card card-wide">
          <h2>Fällige Mahnungen</h2>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th />
                  <th>Rechnung</th>
                  <th>Empfänger</th>
                  <th>
                    <Term k="due_date">fällig</Term> seit
                  </th>
                  <th>
                    nächste <Term k="dunning_level">Stufe</Term>
                  </th>
                  <th className="num">
                    <Term k="outstanding">offen</Term>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.proposals.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${p.number} mahnen`}
                        checked={!skip.has(p.id)}
                        disabled={!canEdit}
                        onChange={(e) => {
                          const next = new Set(skip)
                          if (e.target.checked) next.delete(p.id)
                          else next.add(p.id)
                          setSkip(next)
                        }}
                      />
                    </td>
                    <td>{p.number}</td>
                    <td>
                      {p.recipient_name.split('\n')[0]}
                      <div className="muted small">
                        {p.recipient_email || 'keine E-Mail, wird gedruckt'}
                      </div>
                    </td>
                    <td>
                      {formatDate(p.due_date)}
                      <div className="muted small">{p.days_overdue} Tage</div>
                    </td>
                    <td>
                      {p.next_level_name}
                      {Number(p.fee) > 0 && <div className="muted small">Gebühr {euro(p.fee)}</div>}
                    </td>
                    <td className="num">{euro(p.outstanding)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {canEdit && (
            <>
              <Checkbox
                label="per E-Mail verschicken, wo eine Adresse bekannt ist"
                checked={send}
                onChange={setSend}
              />
              <Why k="dunning_send" />
              {failure && <Alert kind="error">{failure}</Alert>}
              <div className="button-row">
                <button
                  type="button"
                  className="button button-primary"
                  disabled={busy || chosen.length === 0}
                  onClick={() => void run()}
                >
                  {send
                    ? `${chosen.length} Mahnungen erstellen und per E-Mail versenden`
                    : `${chosen.length} Mahnungen erstellen (ohne Versand)`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
