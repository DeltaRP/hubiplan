// Zu- und Absagen: eigene Rückmeldung, Teilnehmerliste des Vorstands, Kalender-Abo.
import { useMemo, useState } from 'react'
import { eventApi } from '../../api/events.ts'
import type {
  CalendarBase,
  EventDetail,
  Occurrence,
  ResponseRow,
  ResponseStatus,
} from '../../api/events.ts'
import { errorMessage, useLoad } from '../forms.ts'
import { Alert, Field } from '../ui.tsx'
import { berlin, formatDay } from './time.ts'
import { confirmDialog } from '../dialog.ts'
import { useTerms } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

const STATUS_LABEL: Record<ResponseStatus, string> = { yes: t('Zusage'), no: t('Absage') }

function deadlineText(iso: string): string {
  const d = berlin(iso)
  return t('{x}, {time} Uhr', { x: formatDay(d.date), time: d.time })
}

/** Kennzeichen in Listen: eigene Rückmeldung oder „Rückmeldung offen“. */
export function RsvpBadge({ o }: { o: Occurrence }) {
  if (!o.rsvp_enabled || o.is_cancelled) return null
  if (o.my_response === 'yes') return <span className="badge badge-yes">zugesagt</span>
  if (o.my_response === 'no') return <span className="badge">abgesagt</span>
  if (o.my_response === null)
    return <span className="badge badge-open">{t('Rückmeldung offen')}</span>
  return null
}

/** Mitgliederbereich: zu- oder absagen. */
export function MyResponsePanel({
  base,
  event,
  onChanged,
}: {
  base: CalendarBase
  event: EventDetail
  onChanged: (event: EventDetail) => void
}) {
  const info = event.rsvp
  const mine = info.mine ?? null
  const [guests, setGuests] = useState(String(mine?.guests ?? 0))
  const [note, setNote] = useState(mine?.note ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<EventDetail>) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await action())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const send = (status: ResponseStatus) =>
    run(() =>
      eventApi.respond(base, event.id, {
        status,
        guests: status === 'yes' && info.guests_allowed ? Number(guests) || 0 : 0,
        note,
      }),
    )

  return (
    <div className="subcard stack-sm rsvp-panel">
      <strong>{t('Ihre Rückmeldung')}</strong>
      {mine ? (
        <p>
          <span className={mine.status === 'yes' ? 'badge badge-yes' : 'badge'}>
            {STATUS_LABEL[mine.status]}
          </span>
          {mine.guests > 0 &&
            t(' mit {guests} Begleitperson{x}', {
              guests: mine.guests,
              x: mine.guests > 1 ? 'en' : '',
            })}
          {mine.source === 'board' && (
            <span className="muted small"> (vom Vorstand eingetragen)</span>
          )}
        </p>
      ) : (
        <p className="muted">{t('Sie haben sich noch nicht zurückgemeldet.')}</p>
      )}
      {info.deadline && (
        <p className="muted small">
          {t('Anmeldeschluss:')} {deadlineText(info.deadline)}
        </p>
      )}
      {info.free !== undefined && (
        <p className="muted small">
          {info.free > 0
            ? t('Noch {free} Plätze frei.', { free: info.free })
            : t('Alle Plätze sind vergeben.')}
        </p>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {info.can_respond ? (
        <>
          <div className="grid-2">
            {info.guests_allowed && (
              <Field
                label={t('Begleitpersonen')}
                type="number"
                min={0}
                max={info.max_guests}
                value={guests}
                onChange={(e) => setGuests(e.target.value)}
              />
            )}
            <Field
              label={t('Bemerkung (optional)')}
              value={note}
              maxLength={200}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void send('yes')}
            >
              {t('Zusagen')}
            </button>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => void send('no')}
            >
              {t('Absagen')}
            </button>
            {mine && (
              <button
                type="button"
                className="link-button"
                disabled={busy}
                onClick={() => void run(() => eventApi.withdraw(base, event.id))}
              >
                {t('Rückmeldung zurücknehmen')}
              </button>
            )}
          </div>
        </>
      ) : (
        info.reason && <p className="muted small">{info.reason}</p>
      )}
    </div>
  )
}

/** Vorstand: Teilnehmerliste mit Eintragen von Hand und Export. */
export function ResponsesPanel({ base, event }: { base: CalendarBase; event: EventDetail }) {
  const tm = useTerms()
  const { data, error, reload } = useLoad(
    () => eventApi.responses(base, event.id),
    [base, event.id],
  )
  const [filter, setFilter] = useState('')
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const canEnter = !!event.rsvp.can_enter

  async function enter(membershipId: number, status: ResponseStatus, guests = 0, note = '') {
    setMessage(null)
    try {
      await eventApi.enterResponse(base, event.id, {
        membership_id: membershipId,
        status,
        guests,
        note,
      })
      await reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function remove(row: ResponseRow) {
    if (
      !(await confirmDialog({
        title: t('Rückmeldung von {name} entfernen?', { name: row.name }),
        confirmLabel: t('Entfernen'),
      }))
    )
      return
    try {
      await eventApi.removeResponse(base, event.id, row.membership_id)
      await reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const open = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const rows = data?.open ?? []
    return q ? rows.filter((r) => r.name.toLowerCase().includes(q)) : rows
  }, [data, filter])

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const s = data.summary
  return (
    <div className="stack-sm responses">
      <div className="responses-head">
        <strong>
          {t('Rückmeldungen')}
          {data.scope === 'department' ? t(' deiner Zugmitglieder') : ''}
        </strong>
        <span className="button-row">
          <a
            className="button button-ghost"
            href={eventApi.exportUrl(base, event.id, 'xlsx')}
            download
          >
            {t('Excel')}
          </a>
          <a
            className="button button-ghost"
            href={eventApi.exportUrl(base, event.id, 'pdf')}
            target="_blank"
            rel="noreferrer"
          >
            PDF
          </a>
        </span>
      </div>
      <p className="small">
        {s.yes} {t('Zusagen')}
        {s.guests > 0 &&
          t(' + {guests} Begleitpersonen = {persons} Personen', {
            guests: s.guests,
            persons: s.persons,
          })}
        {data.capacity ? ` (höchstens ${data.capacity})` : ''}{' '}
        {t('· {no} Absagen · {open} noch offen', { no: s.no, open: s.open })}
      </p>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{t('Name')}</th>
                <th>{tm.sg}</th>
                <th>{t('Rückmeldung')}</th>
                <th>{t('Bemerkung')}</th>
                {canEnter && <th />}
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.membership_id}>
                  <td>{r.name}</td>
                  <td>{r.departments}</td>
                  <td>
                    {r.status && STATUS_LABEL[r.status]}
                    {r.guests > 0 && t(' + {guests}', { guests: r.guests })}
                    {r.source === 'board' && <span className="muted small"> (Vorstand)</span>}
                  </td>
                  <td>{r.note}</td>
                  {canEnter && (
                    <td>
                      <button type="button" className="link-button" onClick={() => remove(r)}>
                        entfernen
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.open.length > 0 && (
        <details className="responses-open">
          <summary>
            {t('Noch keine Rückmeldung ({n})', { n: data.open.length })}
            {canEnter && t(' – hier für Mitglieder ohne Zugang eintragen')}
          </summary>
          <Field
            label={t('Mitglied suchen')}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <ul className="plain-list">
            {open.slice(0, 200).map((r) => (
              <li key={r.membership_id} className="responses-open-row">
                <span>
                  {r.name}
                  {r.departments && <span className="muted small"> · {r.departments}</span>}
                </span>
                {canEnter && (
                  <span className="button-row">
                    <button
                      type="button"
                      className="link-button"
                      aria-label={t('Zusage für {name} eintragen', { name: r.name })}
                      onClick={() => void enter(r.membership_id, 'yes')}
                    >
                      {t('Zusage')}
                    </button>
                    <button
                      type="button"
                      className="link-button"
                      aria-label={t('Absage für {name} eintragen', { name: r.name })}
                      onClick={() => void enter(r.membership_id, 'no')}
                    >
                      {t('Absage')}
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
          {open.length > 200 && (
            <p className="muted small">
              {t('Weitere')} {open.length - 200} {t('– bitte die Suche nutzen.')}
            </p>
          )}
        </details>
      )}
    </div>
  )
}

/** Mitgliederbereich: persönliches Kalender-Abo. */
export function FeedPanel({ base }: { base: CalendarBase }) {
  const { data, error, setData } = useLoad(() => eventApi.feed(base), [base])
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<{ ics_url: string | null }>, text: string) {
    setBusy(true)
    setMessage(null)
    try {
      setData(await action())
      setMessage({ kind: 'success', text })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setMessage({ kind: 'success', text: t('Link kopiert.') })
    } catch {
      setMessage({ kind: 'error', text: t('Kopieren ging nicht. Bitte den Link markieren.') })
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <div className="card card-wide stack">
      <p className="muted small">
        {t(
          'Mit diesem persönlichen Link erscheinen Ihre Termine im Kalender von Handy oder Outlook („Kalender abonnieren“ bzw. „Kalender aus dem Internet hinzufügen“). Der Link ist nur für Sie. Geben Sie ihn nicht weiter. Sie können ihn jederzeit erneuern, dann gilt der alte nicht mehr.',
        )}
      </p>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {data.ics_url ? (
        <>
          <div className="statute-link">
            <code>{data.ics_url}</code>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => copy(data.ics_url!)}
            >
              {t('Link kopieren')}
            </button>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={async () => {
                if (
                  await confirmDialog({
                    title: t('Neuen Link erstellen?'),
                    message: t('Der alte Link gilt dann nicht mehr.'),
                    confirmLabel: t('Neuen Link erstellen'),
                    danger: false,
                  })
                ) {
                  void run(() => eventApi.renewFeed(base), t('Neuer Link erstellt.'))
                }
              }}
            >
              {t('Neuen Link erstellen')}
            </button>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() =>
                void run(() => eventApi.removeFeed(base), t('Das Abo ist abgeschaltet.'))
              }
            >
              {t('Abo abschalten')}
            </button>
          </div>
        </>
      ) : (
        <button
          type="button"
          className="button button-primary"
          disabled={busy}
          onClick={() => void run(() => eventApi.renewFeed(base), t('Ihr Link ist bereit.'))}
        >
          {t('Persönlichen Link erstellen')}
        </button>
      )}
    </div>
  )
}
