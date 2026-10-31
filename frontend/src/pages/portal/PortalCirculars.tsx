// Mitgliederbereich: empfangene Rundschreiben lesen, Informationen abbestellen.
import { useState } from 'react'
import { portalCircularApi } from '../../api/circulars.ts'
import type { ReceivedCircular } from '../../api/circulars.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox } from '../../components/ui.tsx'
import { MarkupPreview } from '../../components/circulars/MarkupEditor.tsx'

export function PortalCirculars({ accessId }: { accessId: number }) {
  const list = useLoad(() => portalCircularApi.list(accessId), [accessId])
  const settings = useLoad(() => portalCircularApi.settings(accessId), [accessId])
  const [open, setOpen] = useState<ReceivedCircular | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function show(id: number) {
    setError(null)
    if (open?.id === id) {
      setOpen(null)
      return
    }
    try {
      setOpen(await portalCircularApi.get(accessId, id))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function setOptOut(value: boolean) {
    setError(null)
    try {
      settings.setData(await portalCircularApi.setOptOut(accessId, value))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide">
      <h2>Rundschreiben</h2>
      {list.data && list.data.length === 0 && (
        <p className="muted">Du hast noch keine Rundschreiben bekommen.</p>
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
                {c.channel === 'letter' && ' · per Brief'}
                {c.channel === 'app' && ' · per App'}
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
      {settings.data && (
        <Checkbox
          label="Informationen per E-Mail erhalten (offizielle Mitteilungen kommen immer)"
          checked={!settings.data.info_opt_out}
          onChange={(on) => void setOptOut(!on)}
        />
      )}
      {(error || list.error) && <Alert kind="error">{error ?? list.error}</Alert>}
    </div>
  )
}
