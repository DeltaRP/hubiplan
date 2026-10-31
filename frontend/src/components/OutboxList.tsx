// Liste versendeter Mails (Postausgang bzw. Test-Postfach).
import { useState } from 'react'
import type { ListQuery, Paged } from '../api/client.ts'
import type { OutgoingMail } from '../api/portal.ts'
import { ListSearch, Pager } from './ListControls.tsx'
import { Alert } from './ui.tsx'
import { useLoad } from './forms.ts'

const STATUS = [
  ['', 'alle'],
  ['sent', 'versendet'],
  ['stored', 'nur gespeichert'],
  ['failed', 'fehlgeschlagen'],
] as const

/** Postausgang mit Suche (Empfänger, Betreff), Zeitraum, Status und Seiten. */
export function OutboxBrowser({
  load,
  deps,
  attachmentUrl,
  showOrg = false,
}: {
  load: (query: ListQuery) => Promise<Paged<OutgoingMail>>
  deps: unknown[]
  attachmentUrl: (mail: number, index: number) => string
  showOrg?: boolean
}) {
  const [query, setQuery] = useState<ListQuery>({})
  const { data, error } = useLoad(() => load(query), [...deps, JSON.stringify(query)])
  const searching = !!(query.q || query.von || query.bis || query.status)
  return (
    <>
      <ListSearch query={query} onChange={setQuery} placeholder="Empfänger oder Betreff">
        <label className="field">
          <span>Status</span>
          <select
            value={query.status ?? ''}
            onChange={(e) => setQuery({ ...query, status: e.target.value, seite: 1 })}
          >
            {STATUS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </ListSearch>
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">Lädt …</p>}
      {data &&
        (data.results.length === 0 && searching ? (
          <p className="muted">Keine passenden Mails.</p>
        ) : (
          <>
            <OutboxList mails={data.results} attachmentUrl={attachmentUrl} showOrg={showOrg} />
            {data.count > 0 && (
              <Pager data={data} noun="Mails" onPage={(seite) => setQuery({ ...query, seite })} />
            )}
          </>
        ))}
    </>
  )
}
import { formatDateTime } from './forms.ts'

export function OutboxList({
  mails,
  attachmentUrl,
  showOrg = false,
}: {
  mails: OutgoingMail[]
  attachmentUrl: (mail: number, index: number) => string
  showOrg?: boolean
}) {
  const [open, setOpen] = useState<number | null>(null)
  if (mails.length === 0) return <p className="muted">Noch keine Mails.</p>
  return (
    <ul className="audit-list">
      {mails.map((m) => (
        <li key={m.id}>
          <button
            type="button"
            className="link-button"
            aria-expanded={open === m.id}
            onClick={() => setOpen(open === m.id ? null : m.id)}
          >
            <strong>{m.subject}</strong>
          </button>
          <div className="muted small">
            {formatDateTime(m.created_at)} · an {m.to}
            {showOrg && m.organization_name && ` · ${m.organization_name}`} · {m.status_label}
            {m.attachments.length > 0 && ` · ${m.attachments.length} Anhang`}
          </div>
          {open === m.id && (
            <div className="subcard">
              <pre className="mail-body">{m.body}</pre>
              {m.attachments.map((a) => (
                <p key={a.index} className="small">
                  <a href={attachmentUrl(m.id, a.index)}>📎 {a.name}</a> ({Math.ceil(a.size / 1024)}{' '}
                  KB)
                </p>
              ))}
              {m.error && <p className="field-error small">{m.error}</p>}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
