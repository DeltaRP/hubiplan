// Termin ansehen; mit Recht auch bearbeiten, einzelne Serientermine ändern, Anhänge.
import { useRef, useState } from 'react'
import { eventApi } from '../../api/events.ts'
import type { CalendarBase, EventCategory, EventDetail, Occurrence } from '../../api/events.ts'
import { errorMessage, useLoad } from '../forms.ts'
import { Alert, Field } from '../ui.tsx'
import { EventForm } from './EventForm.tsx'
import { MyResponsePanel, ResponsesPanel } from './Rsvp.tsx'
import { EventProjectPanel } from './EventProject.tsx'
import { berlin, formatDay, formatRange, toApi } from './time.ts'
import { confirmDialog, promptDialog } from '../dialog.ts'
import { Modal } from '../Modal.tsx'
import type { CloseGuard } from './EventForm.tsx'
import { t } from '../../i18n/index.ts'

export { Modal }

const MAX_BYTES = 15 * 1024 * 1024

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? t('{x} MB', { x: (bytes / 1024 / 1024).toFixed(1).replace('.', ',') })
    : t('{x} KB', { x: Math.max(1, Math.round(bytes / 1024)) })
}

export function VisibilityBadge({ visibility }: { visibility: string }) {
  if (visibility === 'members') return null
  return (
    <span className={`badge badge-${visibility}`}>
      {visibility === 'public' ? t('öffentlich') : t('nur Vorstand')}
    </span>
  )
}

/** Neuen Termin anlegen (Dialog). */
export function NewEventDialog({
  base,
  date,
  categories,
  rsvpAllowed,
  onClose,
  onSaved,
}: {
  base: CalendarBase
  date: string
  categories: EventCategory[]
  rsvpAllowed?: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const guard = useRef<CloseGuard | null>(null)
  return (
    <Modal
      title={t('Neuer Termin')}
      onClose={onClose}
      beforeClose={() => guard.current?.() ?? true}
    >
      <EventForm
        guardRef={guard}
        base={base}
        event={null}
        date={date}
        categories={categories}
        rsvpAllowed={rsvpAllowed}
        onCancel={onClose}
        onSaved={onSaved}
      />
    </Modal>
  )
}

/** Einzelnen Termin einer Serie verschieben oder absagen. */
function OccurrencePanel({
  base,
  event,
  occurrence,
  onChanged,
}: {
  base: CalendarBase
  event: EventDetail
  occurrence: Occurrence
  onChanged: (event: EventDetail) => void
}) {
  const s = berlin(occurrence.starts_at)
  const e = berlin(occurrence.ends_at)
  const [mode, setMode] = useState<'none' | 'move'>('none')
  const [date, setDate] = useState(s.date)
  const [start, setStart] = useState(s.time)
  const [end, setEnd] = useState(e.time)
  const [note, setNote] = useState(occurrence.note)
  const [error, setError] = useState<string | null>(null)
  const exception = event.exceptions.find(
    (x) => new Date(x.original_start).getTime() === new Date(occurrence.original_start).getTime(),
  )

  async function run(action: () => Promise<EventDetail>) {
    setError(null)
    try {
      onChanged(await action())
      setMode('none')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const original = occurrence.original_start
  return (
    <div className="subcard stack-sm">
      <strong>{t('Nur dieser Termin ({x})', { x: formatDay(berlin(original).date) })}</strong>
      {error && <Alert kind="error">{error}</Alert>}
      {mode === 'move' ? (
        <div className="stack-sm">
          <div className="grid-3">
            <Field
              label={t('Neues Datum')}
              type="date"
              value={date}
              onChange={(x) => setDate(x.target.value)}
            />
            {!event.all_day && (
              <>
                <Field
                  label={t('Beginn')}
                  type="time"
                  value={start}
                  onChange={(x) => setStart(x.target.value)}
                />
                <Field
                  label={t('Ende')}
                  type="time"
                  value={end}
                  onChange={(x) => setEnd(x.target.value)}
                />
              </>
            )}
          </div>
          <Field label={t('Hinweis')} value={note} onChange={(x) => setNote(x.target.value)} />
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              onClick={() =>
                run(() =>
                  eventApi.setOccurrence(base, event.id, {
                    original_start: original,
                    starts_at: toApi(date, event.all_day ? '00:00' : start),
                    ends_at: event.all_day ? null : toApi(date, end),
                    note,
                  }),
                )
              }
            >
              {t('Verschieben')}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setMode('none')}>
              {t('Abbrechen')}
            </button>
          </div>
        </div>
      ) : (
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={() => setMode('move')}>
            {t('Verschieben')}
          </button>
          {!occurrence.is_cancelled && (
            <button
              type="button"
              className="button button-ghost"
              onClick={async () => {
                const reason = await promptDialog({
                  title: t('Diesen Termin absagen?'),
                  label: t('Hinweis zur Absage (optional)'),
                  confirmLabel: t('Absagen'),
                  danger: true,
                })
                if (reason === null) return
                void run(() =>
                  eventApi.setOccurrence(base, event.id, {
                    original_start: original,
                    is_cancelled: true,
                    note: reason,
                  }),
                )
              }}
            >
              {t('Nur diesen absagen')}
            </button>
          )}
          {exception && (
            <button
              type="button"
              className="button button-ghost"
              onClick={() => run(() => eventApi.resetOccurrence(base, event.id, original))}
            >
              {t('Wie in der Serie')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function EventDialog({
  base,
  occurrence,
  categories,
  rsvpAllowed,
  onClose,
  onChanged,
}: {
  base: CalendarBase
  occurrence: Occurrence
  categories: EventCategory[]
  rsvpAllowed?: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { data, error, setData } = useLoad(
    () => eventApi.get(base, occurrence.event_id),
    [base, occurrence.event_id],
  )
  const [editing, setEditing] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [inputKey, setInputKey] = useState(0)
  const guard = useRef<CloseGuard | null>(null)

  function changed(event: EventDetail) {
    setData(event)
    onChanged()
  }

  async function upload(file: File) {
    if (file.size > MAX_BYTES) {
      setMessage({ kind: 'error', text: t('Die Datei ist größer als 15 MB.') })
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      changed(await eventApi.upload(base, occurrence.event_id, file))
      setInputKey((k) => k + 1)
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  const title = data?.title ?? occurrence.title
  return (
    <Modal
      title={editing ? t('Termin bearbeiten') : title}
      onClose={onClose}
      beforeClose={() => (editing ? (guard.current?.() ?? true) : true)}
    >
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">{t('Lädt …')}</p>}
      {data && editing && (
        <EventForm
          guardRef={guard}
          base={base}
          event={data}
          date={berlin(data.starts_at).date}
          categories={categories}
          rsvpAllowed={rsvpAllowed}
          onCancel={() => setEditing(false)}
          onSaved={(saved) => {
            changed(saved)
            setEditing(false)
          }}
        />
      )}
      {data && !editing && (
        <div className="stack">
          {message && <Alert kind={message.kind}>{message.text}</Alert>}
          {occurrence.is_cancelled && (
            <Alert kind="error">
              {t('Abgesagt')}
              {occurrence.note ? t(': {note}', { note: occurrence.note }) : ''}
            </Alert>
          )}
          <dl className="event-facts">
            <dt>{t('Wann')}</dt>
            <dd>
              {formatRange(occurrence.starts_at, occurrence.ends_at, occurrence.all_day)}
              {occurrence.is_moved && <span className="badge"> verschoben</span>}
              {data.repeat !== 'none' && (
                <div className="muted small">
                  {t('Serie:')} {data.repeat_label}
                  {data.repeat_interval > 1 && ` (alle ${data.repeat_interval})`}
                  {data.repeat_until && t(' bis {x}', { x: formatDay(data.repeat_until, false) })}
                </div>
              )}
            </dd>
            {(data.location || data.address) && (
              <>
                <dt>{t('Ort')}</dt>
                <dd>
                  {data.location}
                  {data.address && <div className="muted small">{data.address}</div>}
                </dd>
              </>
            )}
            <dt>{t('Kalender')}</dt>
            <dd>
              {data.owner} <VisibilityBadge visibility={data.visibility} />
            </dd>
            {data.category && (
              <>
                <dt>{t('Kategorie')}</dt>
                <dd>
                  <span className="event-dot" style={{ background: data.category.color }} />{' '}
                  {data.category.name}
                </dd>
              </>
            )}
            {data.changed_at && (
              <>
                <dt>{t('Geändert')}</dt>
                <dd>
                  {t('Zeit oder Ort geändert am')} {formatDay(berlin(data.changed_at).date, false)}
                </dd>
              </>
            )}
          </dl>
          {data.description && <p className="event-description">{data.description}</p>}
          {data.rsvp.can_respond !== undefined && (
            <MyResponsePanel base={base} event={data} onChanged={changed} />
          )}
          {data.rsvp.can_view_list && <ResponsesPanel base={base} event={data} />}
          {data.can_edit && data.rsvp.enabled && (
            <p className="muted small">
              {t('Zu- und Absagen sind eingeschaltet')}
              {data.remind_days
                ? t(', Erinnerung {remind_days} Tage vorher', { remind_days: data.remind_days })
                : ''}
              .
            </p>
          )}
          <EventProjectPanel base={base} event={data} onChanged={changed} />
          {(data.attachments.length > 0 || data.can_edit) && (
            <div className="stack-sm">
              <strong>{t('Anhänge')}</strong>
              {data.attachments.length === 0 && (
                <p className="muted small">{t('Keine Anhänge.')}</p>
              )}
              <ul className="plain-list">
                {data.attachments.map((a) => (
                  <li key={a.id}>
                    <a href={a.url} target="_blank" rel="noreferrer">
                      {a.name}
                    </a>{' '}
                    <span className="muted small">{formatSize(a.size)}</span>
                    {data.can_edit && (
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy}
                        onClick={async () => {
                          if (
                            !(await confirmDialog({
                              title: t('Anhang „{name}“ entfernen?', { name: a.name }),
                              confirmLabel: t('Entfernen'),
                            }))
                          )
                            return
                          try {
                            await eventApi.removeAttachment(a.url)
                            changed(await eventApi.get(base, data.id))
                          } catch (err) {
                            setMessage({ kind: 'error', text: errorMessage(err) })
                          }
                        }}
                      >
                        entfernen
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              {data.can_edit && (
                <label className="field">
                  <span>{t('Anhang hinzufügen (PDF, JPEG oder PNG, höchstens 15 MB)')}</span>
                  <input
                    key={inputKey}
                    type="file"
                    accept="application/pdf,image/jpeg,image/png"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) void upload(file)
                    }}
                  />
                </label>
              )}
            </div>
          )}
          <p className="small">
            <a href={eventApi.icsUrl(base, data.id)} download>
              {data.repeat !== 'none' ? t('Serie') : t('Termin')}{' '}
              {t('in den eigenen Kalender (.ics)')}
            </a>
          </p>
          {data.can_edit && data.repeat !== 'none' && (
            <OccurrencePanel base={base} event={data} occurrence={occurrence} onChanged={changed} />
          )}
          {data.can_edit && (
            <div className="button-row">
              <button
                type="button"
                className="button button-primary"
                onClick={() => setEditing(true)}
              >
                {data.repeat !== 'none' ? t('Serie bearbeiten') : t('Bearbeiten')}
              </button>
              <button
                type="button"
                className="button button-danger"
                disabled={busy}
                onClick={async () => {
                  const what = data.repeat !== 'none' ? t('die ganze Serie') : t('den Termin')
                  if (
                    !(await confirmDialog({
                      title: t('Wirklich {what} „{title}“ löschen?', { what, title: data.title }),
                      confirmLabel: t('Löschen'),
                    }))
                  )
                    return
                  try {
                    await eventApi.remove(base, data.id)
                    onChanged()
                    onClose()
                  } catch (err) {
                    setMessage({ kind: 'error', text: errorMessage(err) })
                  }
                }}
              >
                {t('Löschen')}
              </button>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
