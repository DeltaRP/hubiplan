// Kalender in Monats- und Listenansicht, für Vorstand, Abteilung und Mitglieder.
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { eventApi } from '../../api/events.ts'
import type { CalendarBase, Occurrence } from '../../api/events.ts'
import { useLoad } from '../forms.ts'
import { LoadError } from '../ui.tsx'
import { EventDialog, NewEventDialog, VisibilityBadge } from './EventDialog.tsx'
import { RsvpBadge } from './Rsvp.tsx'
import {
  MONTHS,
  WEEKDAYS,
  addDays,
  addMonths,
  berlin,
  formatDay,
  monthGrid,
  monthStart,
  today,
  daysOf,
} from './time.ts'
import { t } from '../../i18n/index.ts'

type View = 'month' | 'list'

const VIEW_KEY = 'hubiplan.kalenderansicht'

// Zuletzt gewählte Ansicht; auf schmalen Bildschirmen sonst die Liste, weil die
// Monatsansicht dort nur Punkte zeigt.
function initialView(): View {
  try {
    const saved = localStorage.getItem(VIEW_KEY)
    if (saved === 'month' || saved === 'list') return saved
  } catch {
    // ohne Speicher: Standard
  }
  return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 700px)').matches
    ? 'list'
    : 'month'
}

function itemClass(o: Occurrence): string {
  return `event-item${o.is_cancelled ? ' event-cancelled' : ''}${o.all_day ? ' event-allday' : ''}`
}

function EventLabel({ o }: { o: Occurrence }) {
  const time = o.all_day ? '' : `${berlin(o.starts_at).time} `
  return (
    <>
      <span className="event-dot" style={{ background: o.category?.color ?? '#7a847f' }} />
      <span className="event-time">{time}</span>
      <span className="event-title">{o.title}</span>
    </>
  )
}

export function CalendarView({
  base,
  emptyHint,
}: {
  base: CalendarBase
  /** Hinweis, wenn noch keine Termine eingetragen sind */
  emptyHint?: string
}) {
  const [view, setViewState] = useState<View>(initialView)
  function setView(v: View) {
    setViewState(v)
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      // egal
    }
  }
  // Direktlink ?termin=<id>&datum=<JJJJ-MM-TT> öffnet den Termin (z. B. aus „Offene Aufgaben“)
  const [params, setParams] = useSearchParams()
  const linked = Number(params.get('termin')) || null
  const linkedDate = params.get('datum')
  const [month, setMonth] = useState(
    monthStart(linkedDate && /^\d{4}-\d{2}-\d{2}$/.test(linkedDate) ? linkedDate : today()),
  )
  const [picked, setPicked] = useState<Occurrence | null>(null)
  function setSelected(o: Occurrence | null) {
    setPicked(o)
    if (!o && linked) {
      const next = new URLSearchParams(params)
      next.delete('termin')
      next.delete('datum')
      setParams(next, { replace: true })
    }
  }
  const [creating, setCreating] = useState<string | null>(null)
  const grid = monthGrid(month)
  const from = view === 'month' ? grid[0] : month
  const to = view === 'month' ? grid[grid.length - 1] : addDays(addMonths(month, 12), -1)
  // Daten gehören zu genau einem Zeitraum: beim Blättern nie die Termine des vorigen
  // Monats unter der neuen Überschrift zeigen (UX-Audit 31.10. W02)
  const rangeKey = `${from}|${to}`
  const loaded = useLoad(
    () => eventApi.list(base, from, to).then((d) => ({ ...d, rangeKey })),
    [base, from, to],
  )
  const data = loaded.data?.rangeKey === rangeKey ? loaded.data : null
  const { error, reload } = loaded
  const selected =
    picked ?? (linked ? (data?.items.find((o) => o.event_id === linked) ?? null) : null)
  const year = Number(month.slice(0, 4))

  const byDay = new Map<string, Occurrence[]>()
  if (view === 'month') {
    for (const o of data?.items ?? []) {
      for (const d of daysOf(o, from, to)) {
        const list = byDay.get(d)
        if (list) list.push(o)
        else byDay.set(d, [o])
      }
    }
  }
  const todayIso = today()

  return (
    <div className="calendar stack">
      <div className="calendar-toolbar">
        <div className="button-row">
          <button
            type="button"
            className="button button-ghost"
            aria-label={view === 'month' ? t('Vorheriger Monat') : t('Früher')}
            onClick={() => setMonth(addMonths(month, -1))}
          >
            ‹
          </button>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setMonth(monthStart(todayIso))}
          >
            {t('Heute')}
          </button>
          <button
            type="button"
            className="button button-ghost"
            aria-label={view === 'month' ? t('Nächster Monat') : t('Später')}
            onClick={() => setMonth(addMonths(month, 1))}
          >
            ›
          </button>
          <strong className="calendar-title" aria-live="polite">
            {view === 'month'
              ? t('{x} {year}', { x: MONTHS[Number(month.slice(5, 7)) - 1], year })
              : t('ab {x} {year}', { x: MONTHS[Number(month.slice(5, 7)) - 1], year })}
          </strong>
        </div>
        <div className="button-row">
          <div className="segmented" role="group" aria-label={t('Ansicht')}>
            <button
              type="button"
              className={`button button-ghost${view === 'month' ? ' is-active' : ''}`}
              aria-pressed={view === 'month'}
              onClick={() => setView('month')}
            >
              {t('Monat')}
            </button>
            <button
              type="button"
              className={`button button-ghost${view === 'list' ? ' is-active' : ''}`}
              aria-pressed={view === 'list'}
              onClick={() => setView('list')}
            >
              {t('Liste')}
            </button>
          </div>
          <a
            className="button button-ghost"
            href={eventApi.programUrl(base, year)}
            target="_blank"
            rel="noreferrer"
          >
            {t('Jahresprogramm {year} (PDF)', { year })}
          </a>
          {data?.can_manage && (
            <button
              type="button"
              className="button button-primary"
              onClick={() => setCreating(month === monthStart(todayIso) ? todayIso : month)}
            >
              {t('Neuer Termin')}
            </button>
          )}
        </div>
      </div>

      {error && (
        <LoadError
          message={t('Die Termine konnten nicht geladen werden ({error}).', { error })}
          onRetry={() => void reload()}
        />
      )}
      {!data && !error && (
        <p className="muted" role="status">
          {t('Termine')} {view === 'month' ? t('für') : 'ab'}{' '}
          {MONTHS[Number(month.slice(5, 7)) - 1]} {year} {t('werden geladen …')}
        </p>
      )}

      {data && view === 'month' && (
        <div className="calendar-grid" role="group" aria-label={t('Monatsansicht')}>
          {WEEKDAYS.map((w) => (
            <div key={w} className="calendar-weekday" aria-hidden="true">
              {w}
            </div>
          ))}
          {grid.map((day) => {
            const items = byDay.get(day) ?? []
            const outside = day.slice(0, 7) !== month.slice(0, 7)
            return (
              <div
                key={day}
                role="group"
                className={`calendar-day${outside ? ' is-outside' : ''}${
                  day === todayIso ? ' is-today' : ''
                }`}
                aria-label={formatDay(day)}
              >
                <div className="calendar-day-head">
                  <span>{Number(day.slice(8, 10))}</span>
                  {data.can_manage && (
                    <button
                      type="button"
                      className="calendar-add"
                      aria-label={t('Neuer Termin am {x}', { x: formatDay(day) })}
                      onClick={() => setCreating(day)}
                    >
                      +
                    </button>
                  )}
                </div>
                {items.map((o) => (
                  <button
                    type="button"
                    key={`${o.key}-${day}`}
                    className={itemClass(o)}
                    title={o.title}
                    aria-label={`${o.all_day ? '' : `${berlin(o.starts_at).time} `}${o.title}${
                      o.is_cancelled ? ' (abgesagt)' : ''
                    }`}
                    onClick={() => setSelected(o)}
                  >
                    <EventLabel o={o} />
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      )}

      {data && view === 'list' && (
        <div className="calendar-list">
          {data.items.length === 0 && (
            <p className="muted">{emptyHint ?? t('Keine Termine in diesem Zeitraum.')}</p>
          )}
          <ul className="plain-list">
            {data.items.map((o) => {
              const s = berlin(o.starts_at)
              const e = berlin(o.ends_at)
              const range =
                s.date === e.date
                  ? formatDay(s.date)
                  : t('{x} – {x2}', { x: formatDay(s.date), x2: formatDay(e.date) })
              return (
                <li key={o.key}>
                  <button type="button" className={itemClass(o)} onClick={() => setSelected(o)}>
                    <span className="calendar-list-date">
                      {range}
                      {!o.all_day && (
                        <span className="muted"> {t('· {time} Uhr', { time: s.time })}</span>
                      )}
                    </span>
                    <span className="calendar-list-main">
                      <span
                        className="event-dot"
                        style={{ background: o.category?.color ?? '#7a847f' }}
                      />{' '}
                      <strong className="event-title">{o.title}</strong>{' '}
                      <VisibilityBadge visibility={o.visibility} />
                      {o.is_cancelled && <span className="badge badge-cancelled">abgesagt</span>}
                      {o.changed_at && !o.is_cancelled && (
                        <span className="badge">{t('geändert')}</span>
                      )}
                      <RsvpBadge o={o} />
                      <span className="muted small">
                        {' '}
                        {[o.location, o.own ? '' : o.owner].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {data && data.items.length === 0 && view === 'month' && emptyHint && (
        <p className="muted small">{emptyHint}</p>
      )}

      {selected && data && (
        <EventDialog
          base={base}
          occurrence={selected}
          categories={data.categories}
          rsvpAllowed={data.rsvp_allowed}
          onClose={() => setSelected(null)}
          onChanged={() => void reload()}
        />
      )}
      {creating && data && (
        <NewEventDialog
          base={base}
          date={creating}
          categories={data.categories}
          rsvpAllowed={data.rsvp_allowed}
          onClose={() => setCreating(null)}
          onSaved={() => {
            setCreating(null)
            void reload()
          }}
        />
      )}
    </div>
  )
}
