// Wettbewerb und Termin im Kalender (Ralf 2026-11-01): beim Anlegen einen Termin wählen
// (Angaben übernehmen) oder einen neuen anlegen; unter „Einrichten“ die Verknüpfung ändern
// und die Zusagen als Starter übernehmen.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  competitionsApi,
  type CompetitionDetail,
  type CompetitionEvent,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, SelectField } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'

export function eventLabel(e: CompetitionEvent): string {
  const when = `${formatDate(e.date)}${e.time ? t(', {time} Uhr', { time: e.time }) : ''}`
  const unit = e.unit_name ? ` (${e.unit_name})` : ''
  const cancelled = e.is_cancelled ? t(' – abgesagt') : ''
  return t('{when} · {title}{unit}{cancelled}', { when, title: e.title, unit, cancelled })
}

export function eventHref(e: CompetitionEvent): string {
  return `/termine?termin=${e.id}&datum=${e.date}`
}

/** Auswahl beim Anlegen: kein Termin, neuer Termin oder ein bestehender. */
export function EventPicker({
  org,
  value,
  onChange,
}: {
  org: number
  /** '' kein Termin, 'neu' neuer Termin, sonst die Nummer des Termins */
  value: string
  onChange: (value: string, event: CompetitionEvent | null) => void
}) {
  const data = useLoad(() => competitionsApi.eventCandidates(org), [org])
  if (!data.data?.on) return null
  const events = data.data.events
  return (
    <SelectField
      label={t('Termin im Kalender')}
      value={value}
      hint={t('Ein bestehender Termin bringt Titel, Datum, Ort und Beschreibung mit.')}
      onChange={(e) => {
        const v = e.target.value
        onChange(v, events.find((x) => String(x.id) === v) ?? null)
      }}
    >
      <option value="">{t('kein Termin')}</option>
      {data.data.can_create && <option value="neu">{t('neuen Termin im Kalender anlegen')}</option>}
      {events.map((e) => (
        <option key={e.id} value={e.id} disabled={!!e.competition}>
          {eventLabel(e)}
          {e.competition ? ` (schon bei „${e.competition}“)` : ''}
        </option>
      ))}
    </SelectField>
  )
}

/** Unter „Einrichten“: zugeordneter Termin, ändern, lösen, anlegen, Zusagen übernehmen. */
export function EventCard({
  org,
  comp,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  onChanged: (res: { location: string; description: string }) => void
}) {
  const [choosing, setChoosing] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  if (!comp.calendar?.on) return null
  const event = comp.event_info ?? null
  const canManage = comp.can_manage
  const closed = comp.status === 'endgueltig'

  async function run(action: () => Promise<{ location: string; description: string }>) {
    setBusy(true)
    try {
      const res = await action()
      setMessage(null)
      setChoosing(false)
      onChanged(res)
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function takeStarters() {
    setBusy(true)
    try {
      const res = await competitionsApi.startersFromEvent(org, comp.id)
      const text =
        res.added === 0
          ? t('Alle Zusagen stehen schon in der Starterliste.')
          : t('{added} Starter aus den Zusagen übernommen.', { added: res.added })
      setMessage({ kind: 'success', text })
      onChanged({ location: comp.location, description: comp.description })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>{t('Termin im Kalender')}</h2>
      {event ? (
        <>
          <p>
            <Link to={eventHref(event)}>{eventLabel(event)}</Link>
            {event.location && <span className="muted"> · {event.location}</span>}
          </p>
          {event.date !== comp.date && (
            <Alert kind="info">
              {t('Der Termin ist am {x}, der Wettbewerb am {x2}.', {
                x: formatDate(event.date),
                x2: formatDate(comp.date),
              })}
            </Alert>
          )}
          {event.rsvp_enabled && (
            <p className="muted">
              {event.yes_count} {event.yes_count === 1 ? t('Zusage') : t('Zusagen')}{' '}
              {t('zum Termin.')}
            </p>
          )}
        </>
      ) : (
        <p className="muted">{t('Der Wettbewerb ist mit keinem Termin verknüpft.')}</p>
      )}
      {canManage && !closed && (
        <>
          {choosing && (
            <EventPicker
              org={org}
              value={event ? String(event.id) : ''}
              onChange={(v) => {
                if (v === 'neu')
                  void run(() => competitionsApi.setEvent(org, comp.id, { create: true }))
                else
                  void run(() =>
                    competitionsApi.setEvent(org, comp.id, { event: v ? Number(v) : null }),
                  )
              }}
            />
          )}
          <div className="button-row">
            {event?.rsvp_enabled && event.yes_count > 0 && (
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void takeStarters()}
              >
                {t('Zusagen als Starter übernehmen')}
              </button>
            )}
            {!choosing && (
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={() => setChoosing(true)}
              >
                {event ? t('Anderen Termin wählen') : t('Termin wählen')}
              </button>
            )}
            {!event && comp.calendar.can_create && (
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={() =>
                  void run(() => competitionsApi.setEvent(org, comp.id, { create: true }))
                }
              >
                {t('Termin anlegen')}
              </button>
            )}
            {event && (
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={async () => {
                  const ok = await confirmDialog({
                    title: t('Verknüpfung lösen'),
                    message: t(
                      'Den Wettbewerb vom Termin „{title}“ lösen? Der Termin bleibt im Kalender.',
                      { title: event.title },
                    ),
                    confirmLabel: t('Lösen'),
                  })
                  if (ok) await run(() => competitionsApi.setEvent(org, comp.id, { event: null }))
                }}
              >
                {t('Verknüpfung lösen')}
              </button>
            )}
          </div>
        </>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </div>
  )
}
