// Meldungen Schritt 2: Interessenabfrage über einen Termin im Kalender. Wer zusagt, steht
// als Vorauswahl in der Meldung; gemeldet werden kann weiter jedes Mitglied (Ralf 2026-11-01).
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  entriesApi,
  type CallDetail,
  type Entry,
  type Interested,
  type Scope,
} from '../../api/entries.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, SelectField } from '../../components/ui.tsx'
import { eventHref, eventLabel } from '../competitions/CalendarLink.tsx'
import { t, tn } from '../../i18n/index.ts'

/** Unter „Ausschreibung“: Termin wählen, anlegen oder lösen. */
export function CallEventCard({
  org,
  call,
  onChanged,
}: {
  org: number
  call: CallDetail
  onChanged: (c: CallDetail) => void
}) {
  const [choosing, setChoosing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  if (!call.calendar?.on) return null
  const event = call.event

  async function run(data: { event: number | null } | { create: true }) {
    setBusy(true)
    try {
      onChanged(await entriesApi.setEvent(org, call.id, data))
      setMessage(null)
      setChoosing(false)
    } catch (err) {
      setMessage(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>{t('Interessenabfrage über den Kalender')}</h2>
      {event ? (
        <>
          <p>
            <Link to={eventHref(event)}>{eventLabel(event)}</Link>
          </p>
          {event.rsvp_enabled ? (
            <p className="muted">
              {event.yes_count} {event.yes_count === 1 ? t('Zusage') : t('Zusagen')}. Wer zusagt,
              steht unter „Meldung“ als Vorauswahl.
            </p>
          ) : (
            <Alert kind="info">
              {t(
                'Der Termin hat keine Zu- und Absagen. Schaltet sie im Kalender ein, damit Mitglieder sagen können, dass sie dabei sein möchten.',
              )}
            </Alert>
          )}
        </>
      ) : (
        <p className="muted">
          {t(
            'Verknüpft die Ausschreibung mit einem Termin, damit Mitglieder zusagen können, ob sie mitmachen möchten. Die Zusagen sind nur eine Vorauswahl.',
          )}
        </p>
      )}
      {choosing && <EventChooser org={org} call={call} disabled={busy} onPick={run} />}
      <div className="button-row">
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
        {!event && call.calendar.can_create && (
          <button
            type="button"
            className="button button-ghost"
            disabled={busy || !call.date}
            title={call.date ? undefined : t('Erst das Datum des Anlasses angeben')}
            onClick={() => void run({ create: true })}
          >
            {t('Termin mit Zusagen anlegen')}
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
                  'Die Ausschreibung vom Termin „{title}“ lösen? Der Termin und seine Zusagen bleiben im Kalender.',
                  { title: event.title },
                ),
                confirmLabel: t('Lösen'),
              })
              if (ok) await run({ event: null })
            }}
          >
            {t('Verknüpfung lösen')}
          </button>
        )}
      </div>
      {message && <Alert kind="error">{message}</Alert>}
    </div>
  )
}

function EventChooser({
  org,
  call,
  disabled,
  onPick,
}: {
  org: number
  call: CallDetail
  disabled: boolean
  onPick: (data: { event: number | null }) => void
}) {
  const data = useLoad(() => entriesApi.eventCandidates(org, call.id), [org, call.id])
  if (data.error) return <Alert kind="error">{data.error}</Alert>
  if (!data.data) return <p className="muted">{t('Termine werden geladen …')}</p>
  return (
    <SelectField
      label={t('Termin im Kalender')}
      value={call.event ? String(call.event.id) : ''}
      disabled={disabled}
      onChange={(e) => onPick({ event: e.target.value ? Number(e.target.value) : null })}
    >
      <option value="">{t('kein Termin')}</option>
      {data.data.events.map((e) => (
        <option key={e.id} value={e.id}>
          {eventLabel(e)}
          {e.call ? ` (auch bei „${e.call}“)` : ''}
        </option>
      ))}
    </SelectField>
  )
}

interface Target {
  key: string
  label: string
  block: number
  team: number | null
}

function targets(call: CallDetail, entry: Entry): Target[] {
  const out: Target[] = []
  for (const b of call.blocks) {
    if (b.kind === 'mannschaften')
      for (const tm of entry.teams.filter((x) => x.block === b.id))
        out.push({ key: `t${tm.id}`, label: tm.name, block: b.id, team: tm.id })
    else if (b.kind === 'personen')
      out.push({ key: `b${b.id}`, label: b.label, block: b.id, team: null })
  }
  return out
}

/** Unter „Meldung“: die Zusagen als Vorauswahl, je Person mit Ziel (Mannschaft/Liste). */
export function InterestCard({
  org,
  call,
  entry,
  locked,
  run,
}: {
  org: Scope
  call: CallDetail
  entry: Entry
  locked: boolean
  run: (action: () => Promise<Entry | unknown>) => Promise<boolean>
}) {
  const data = useLoad(
    () => entriesApi.responses(org, call.id),
    // nach jeder Änderung der Meldung neu laden („schon gemeldet“)
    [org, call.id, entry.persons.length, entry.persons.map((p) => p.membership).join(',')],
  )
  const event = call.event
  if (!event || !entry.can_pick_members) return null
  const list = targets(call, entry)
  const yes = data.data?.yes ?? []
  const open = yes.filter((r) => !r.taken)
  return (
    <div className="card card-wide">
      <h2>{t('Zusagen zum Termin')}</h2>
      <p className="muted">
        {yes.length === 0
          ? t('Zu „{title}“ ({x}) hat noch niemand zugesagt.', {
              title: event.title,
              x: formatDate(event.date),
            })
          : tn(
              '{n} Zusage, davon {x2} schon in der Meldung.',
              '{n} Zusagen, davon {x2} schon in der Meldung.',
              yes.length,
              { x2: yes.length - open.length },
            )}
        {data.data && data.data.no_count > 0
          ? tn(' {n} Absage.', ' {n} Absagen.', data.data.no_count)
          : ''}{' '}
        {t('Melden lässt sich weiter jedes Mitglied.')}
      </p>
      {data.error && <Alert kind="error">{data.error}</Alert>}
      {yes.length > 0 && (
        <ul className="plain-list">
          {yes.map((r) => (
            <InterestRow
              key={r.membership}
              person={r}
              targets={list}
              disabled={locked}
              onAdd={(tm) =>
                run(() =>
                  entriesApi.addPerson(org, call.id, {
                    block: tm.block,
                    team: tm.team,
                    membership: r.membership,
                  }),
                )
              }
            />
          ))}
        </ul>
      )}
      {!locked && list.length === 0 && yes.length > 0 && (
        <p className="muted small">
          {t('Legt zuerst eine Mannschaft an, dann lassen sich die Zusagen zuordnen.')}
        </p>
      )}
    </div>
  )
}

function InterestRow({
  person: r,
  targets: list,
  disabled,
  onAdd,
}: {
  person: Interested
  targets: Target[]
  disabled: boolean
  onAdd: (tm: Target) => Promise<boolean>
}) {
  const [target, setTarget] = useState('')
  const chosen = list.find((tm) => tm.key === target) ?? list[0]
  const details = [
    r.unit_name,
    r.birth_year ? t('geb. {birth_year}', { birth_year: r.birth_year }) : '',
    r.note,
  ]
    .filter(Boolean)
    .join(' · ')
  return (
    <li className="button-row">
      <span>
        <strong>{r.name}</strong>
        {details && <span className="muted small"> · {details}</span>}
      </span>
      {r.taken ? (
        <span className="muted small">{t('schon gemeldet')}</span>
      ) : (
        !disabled &&
        chosen && (
          <>
            {list.length > 1 && (
              <select
                aria-label={t('Ziel für {name}', { name: r.name })}
                value={chosen.key}
                onChange={(e) => setTarget(e.target.value)}
              >
                {list.map((tm) => (
                  <option key={tm.key} value={tm.key}>
                    {tm.label}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="button button-ghost"
              onClick={() => void onAdd(chosen)}
            >
              {list.length > 1 ? t('hinzufügen') : t('zu {label}', { label: chosen.label })}
            </button>
          </>
        )
      )}
    </li>
  )
}
