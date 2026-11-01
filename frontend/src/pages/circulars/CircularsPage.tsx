// Rundschreiben: eigener Bereich für Dachverband, Verein und Abteilung.
// Reiter „Verfassen“ (eigene Rundschreiben), „Verteiler“ (Rundschreiben aus dem
// eigenen Mailprogramm) und beim Verein „Empfangen“
// (Rundschreiben des Dachverbands an die Vorstände).
import { useState } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { DEPT_PERM } from '../../api/portal.ts'
import { circularBase, receivedApi } from '../../api/circulars.ts'
import type { CircularBase, ReceivedCircular } from '../../api/circulars.ts'
import { CircularsArea } from '../../components/circulars/CircularsArea.tsx'
import { MailingListsArea } from '../../components/circulars/MailingListsArea.tsx'
import { MarkupPreview } from '../../components/circulars/MarkupEditor.tsx'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Tabs } from '../../components/ui.tsx'
import { useOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { canWriteCirculars } from './access.ts'

const ROOT = '/rundschreiben'

/** Alte Adressen (/mitglieder/rundschreiben/…, /abteilung/rundschreiben/…) weiterleiten. */
export function MovedCirculars() {
  const rest = useParams()['*'] ?? ''
  return <Navigate to={rest ? `${ROOT}/${rest}` : ROOT} replace />
}

export function CircularsPage() {
  const { active, activeDept } = useOrg()
  let base: CircularBase | null = null
  let write = false
  let receive = false
  let subtitle = ''
  if (active && (active.type === 'club' || active.type === 'federation')) {
    base = circularBase.org(active.id)
    write = canWriteCirculars(active)
    receive = active.type === 'club'
    subtitle = active.name
  } else if (activeDept && activeDept.permissions.includes(DEPT_PERM.circularsSend)) {
    base = circularBase.dept(activeDept.id)
    write = true
    subtitle = `${activeDept.name} · ${activeDept.club_name}`
  }
  if (!base || (!write && !receive)) return <Navigate to="/" replace />
  const orgId = active?.id ?? 0
  const tabs = [
    ...(write ? [{ to: ROOT, label: 'Verfassen' }] : []),
    ...(write ? [{ to: `${ROOT}/verteiler`, label: 'Verteiler' }] : []),
    ...(receive ? [{ to: `${ROOT}/empfangen`, label: 'Empfangen' }] : []),
  ]
  return (
    <section>
      <div className="page-head">
        <h1>Rundschreiben</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {tabs.length > 1 && <Tabs items={tabs} />}
      <Routes>
        {receive && <Route path="empfangen" element={<ReceivedList orgId={orgId} />} />}
        {write && (
          <Route
            path="verteiler/*"
            element={
              <MailingListsArea base={base} root={`${ROOT}/verteiler`} circularsRoot={ROOT} />
            }
          />
        )}
        {write ? (
          <Route path="*" element={<CircularsArea base={base} root={ROOT} />} />
        ) : (
          <Route path="*" element={<Navigate to={`${ROOT}/empfangen`} replace />} />
        )}
      </Routes>
    </section>
  )
}

function ReceivedList({ orgId }: { orgId: number }) {
  const tm = useTerms()
  const list = useLoad(() => receivedApi.list(orgId), [orgId])
  const [open, setOpen] = useState<ReceivedCircular | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function show(id: number) {
    setError(null)
    if (open?.id === id) {
      setOpen(null)
      return
    }
    try {
      setOpen(await receivedApi.get(orgId, id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide">
      <h2>{tm.dv_Vom}</h2>
      <p className="muted small">
        Rundschreiben {tm.dv_gen} an die Vorstände {tm.e_gen}.
      </p>
      {list.data && list.data.length === 0 && (
        <p className="muted">Noch keine Rundschreiben empfangen.</p>
      )}
      {list.data && list.data.length > 0 && (
        <ul className="plain-list">
          {list.data.map((c) => (
            <li key={c.id}>
              <button type="button" className="link-button" onClick={() => void show(c.id)}>
                {c.subject}
              </button>{' '}
              <span className="muted small">
                {c.sender} · {formatDate(c.sent_at)}
              </span>
              {open?.id === c.id && open.body !== undefined && (
                <div className="subcard">
                  <MarkupPreview text={open.body} />
                  {open.attachments && open.attachments.length > 0 && (
                    <p>
                      Anhänge:{' '}
                      {open.attachments.map((a, i) => (
                        <span key={a.id}>
                          {i > 0 && ', '}
                          <a href={a.url} target="_blank" rel="noreferrer">
                            {a.name}
                          </a>
                        </span>
                      ))}
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {(error || list.error) && <Alert kind="error">{error ?? list.error}</Alert>}
    </div>
  )
}
