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
import { t } from '../../i18n/index.ts'

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
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const chosen = data.proposals.filter((p) => !skip.has(p.id)).map((p) => p.id)

  async function run() {
    setBusy(true)
    setFailure(null)
    try {
      const r = await billingApi.dun(org.id, chosen, send)
      setResult({
        text:
          t('{created} Mahnungen erstellt', { created: r.created }) +
          (send ? t(', {sent} per E-Mail verschickt.', { sent: r.sent }) : '.') +
          (r.unsent.length ? t(' {n} bitte ausdrucken.', { n: r.unsent.length }) : ''),
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
              {t('Mahnungen zum Drucken (PDF)')}
            </a>
          )}
        </Alert>
      )}
      {data.levels.length === 0 ? (
        <div className="card empty-state">
          <p>{t('Noch keine Mahnstufen.')}</p>
          <p className="muted small">
            {t('Lege sie unter')}{' '}
            <Link to="/finanzen/einstellungen/mahnstufen">{t('Einrichtung › Mahnstufen')}</Link>{' '}
            {t('an, zum Beispiel eine Zahlungserinnerung 14 Tage nach Fälligkeit.')}
          </p>
        </div>
      ) : data.proposals.length === 0 ? (
        <div className="card empty-state">
          <p>{t('Keine Mahnungen fällig.')}</p>
          <p className="muted small">
            {t('Hier erscheinen offene Rechnungen, sobald die nächste Mahnstufe erreicht ist.')}
          </p>
        </div>
      ) : (
        <div className="card card-wide">
          <h2>{t('Fällige Mahnungen')}</h2>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th />
                  <th>{t('Rechnung')}</th>
                  <th>{t('Empfänger')}</th>
                  <th>
                    <Term k="due_date">{t('fällig')}</Term> seit
                  </th>
                  <th>
                    {t('nächste')} <Term k="dunning_level">{t('Stufe')}</Term>
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
                        aria-label={t('{number} mahnen', { number: p.number })}
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
                        {p.recipient_email || t('keine E-Mail, wird gedruckt')}
                      </div>
                    </td>
                    <td>
                      {formatDate(p.due_date)}
                      <div className="muted small">
                        {p.days_overdue} {t('Tage')}
                      </div>
                    </td>
                    <td>
                      {p.next_level_name}
                      {Number(p.fee) > 0 && (
                        <div className="muted small">
                          {t('Gebühr')} {euro(p.fee)}
                        </div>
                      )}
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
                label={t('per E-Mail verschicken, wo eine Adresse bekannt ist')}
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
                    ? t('{n} Mahnungen erstellen und per E-Mail versenden', { n: chosen.length })
                    : t('{n} Mahnungen erstellen (ohne Versand)', { n: chosen.length })}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
