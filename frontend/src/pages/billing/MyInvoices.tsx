// Rechnungen im Abteilungsbereich (Sammelrechnungen) und im Mitgliederbereich.
import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { portalBillingApi } from '../../api/billing.ts'
import { ApiError } from '../../api/client.ts'
import { euro } from '../../api/finance.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field } from '../../components/ui.tsx'
import { StatusBadge } from './InvoicesPage.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { useTerms } from '../../org/terms.ts'

export function DeptInvoices({ deptId }: { deptId: number }) {
  const { data, error } = useLoad(() => portalBillingApi.deptInvoices(deptId), [deptId])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  if (data.length === 0)
    return (
      <div className="card empty-state">
        <p>Noch keine Sammelrechnungen.</p>
      </div>
    )
  return (
    <div className="stack">
      {data.map((inv) => (
        <div key={inv.id} className="card card-wide">
          <div className="card-head">
            <h2>
              {inv.number} <StatusBadge row={inv} />
            </h2>
            <a
              className="button button-ghost push-right"
              href={portalBillingApi.deptPdfUrl(deptId, inv.id)}
              target="_blank"
              rel="noreferrer"
            >
              PDF
            </a>
          </div>
          <p>
            {inv.subject} · vom {formatDate(inv.date)} · fällig {formatDate(inv.due_date)}
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Mitglied</th>
                <th />
                <th className="num">Beitrag</th>
              </tr>
            </thead>
            <tbody>
              {inv.lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.text}</td>
                  <td className="muted small">{l.detail}</td>
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
              {Number(inv.paid) > 0 && (
                <tr>
                  <th>bezahlt</th>
                  <th />
                  <th className="num">{euro(inv.paid)}</th>
                </tr>
              )}
            </tfoot>
          </table>
        </div>
      ))}
    </div>
  )
}

export function PortalInvoices({ accessId, empty }: { accessId: number; empty?: ReactNode }) {
  const t = useTerms()
  const { data, error } = useLoad(() => portalBillingApi.invoices(accessId), [accessId])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return null
  if (data.invoices.length === 0 && data.collective.length === 0) return empty ?? null
  return (
    <div className="card card-wide">
      <h2>Meine Rechnungen</h2>
      {data.invoices.length > 0 && (
        <table className="table">
          <tbody>
            {data.invoices.map((inv) => (
              <tr key={inv.id}>
                <td>
                  <a
                    href={portalBillingApi.pdfUrl(accessId, inv.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {inv.number}
                  </a>
                  <div className="muted small">
                    {inv.issuer_name && `${inv.issuer_name} · `}
                    {inv.subject} · fällig {formatDate(inv.due_date)}
                  </div>
                </td>
                <td>
                  <StatusBadge row={inv} />
                </td>
                <td className="num">
                  {euro(inv.total)}
                  {Number(inv.paid) > 0 && Number(inv.outstanding) > 0 && (
                    <div className="muted small">offen {euro(inv.outstanding)}</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.collective.length > 0 && (
        <>
          <p className="muted small">Diese Beiträge laufen über die Sammelrechnung {t.deines}:</p>
          <ul>
            {data.collective.map((c) => (
              <li key={c.id}>
                {c.subject} ({c.department_name}): {euro(c.amount)} · {c.status_label}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function PortalMandate({ accessId }: { accessId: number }) {
  const { data, error, setData } = useLoad(() => portalBillingApi.mandate(accessId), [accessId])
  const [holder, setHolder] = useState('')
  const [iban, setIban] = useState('')
  const [bic, setBic] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data || !data.available) return null
  const m = data.mandate

  async function grant(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setNotice(null)
    setFieldErrors({})
    try {
      setData(await portalBillingApi.grantMandate(accessId, { holder, iban, bic, consent }))
      setNotice({
        kind: 'success',
        text: 'Danke, das Mandat ist erteilt. Du bekommst eine Bestätigung per E-Mail.',
      })
    } catch (err) {
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors)
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function revoke() {
    if (
      !(await confirmDialog({
        title: 'Lastschriftmandat widerrufen?',
        message: 'Beiträge musst du dann überweisen.',
        confirmLabel: 'Widerrufen',
      }))
    )
      return
    setBusy(true)
    try {
      await portalBillingApi.revokeMandate(accessId)
      setData(await portalBillingApi.mandate(accessId))
      setNotice({ kind: 'success', text: 'Das Mandat ist widerrufen.' })
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>SEPA-Lastschrift</h2>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      {m ? (
        <>
          <p>{data.club_name} zieht deine Beiträge per Lastschrift von deinem Konto ein.</p>
          <dl className="facts">
            <dt>Kontoinhaber</dt>
            <dd>{m.holder}</dd>
            <dt>IBAN</dt>
            <dd>{m.iban_masked}</dd>
            <dt>Mandatsreferenz</dt>
            <dd>{m.reference}</dd>
            <dt>erteilt am</dt>
            <dd>{formatDate(m.signed_on)}</dd>
          </dl>
          <button
            type="button"
            className="button button-ghost"
            disabled={busy}
            onClick={() => void revoke()}
          >
            Mandat widerrufen
          </button>
        </>
      ) : (
        <form onSubmit={grant}>
          <p className="muted small">
            Statt zu überweisen kannst du {data.club_name} erlauben, deine Beiträge einzuziehen. Vor
            jedem Einzug bekommst du eine Ankündigung.
          </p>
          <div className="grid-3">
            <Field
              label="Kontoinhaber"
              required
              value={holder}
              error={fieldErrors.holder}
              onChange={(e) => setHolder(e.target.value)}
            />
            <Field
              label="IBAN"
              required
              value={iban}
              error={fieldErrors.iban}
              onChange={(e) => setIban(e.target.value)}
            />
            <Field
              label="BIC (optional)"
              value={bic}
              error={fieldErrors.bic}
              onChange={(e) => setBic(e.target.value)}
            />
          </div>
          <p className="small">{data.text}</p>
          <Checkbox
            label="Ich erteile dieses SEPA-Lastschriftmandat."
            checked={consent}
            onChange={setConsent}
          />
          <button type="submit" className="button button-primary" disabled={busy || !consent}>
            Mandat erteilen
          </button>
        </form>
      )}
    </div>
  )
}
