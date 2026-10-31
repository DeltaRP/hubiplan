// Startseiten-Kachel „Nächste Termine“.
import { Link } from 'react-router-dom'
import { eventApi } from '../../api/events.ts'
import type { CalendarBase } from '../../api/events.ts'
import { useLoad } from '../forms.ts'
import { RsvpBadge } from './Rsvp.tsx'
import { addDays, berlin, formatDay, today } from './time.ts'

export function UpcomingTile({ base }: { base: CalendarBase }) {
  const from = today()
  const { data, error } = useLoad(
    () => eventApi.upcoming(base, from, addDays(from, 90)),
    [base, from],
  )
  const items = (data?.items ?? []).slice(0, 5)
  return (
    <div className="card tile">
      <h2>Nächste Termine</h2>
      {error && <p className="muted small">Termine konnten nicht geladen werden.</p>}
      {data && items.length === 0 && <p className="muted">In den nächsten Wochen keine Termine.</p>}
      {items.length > 0 && (
        <ul className="plain-list upcoming-list">
          {items.map((o) => {
            const s = berlin(o.starts_at)
            return (
              <li key={o.key} className={o.is_cancelled ? 'event-cancelled' : undefined}>
                <span className="muted small">
                  {formatDay(s.date)}
                  {!o.all_day && `, ${s.time} Uhr`}
                </span>
                <div>
                  <span className="event-title">{o.title}</span>
                  {o.is_cancelled && <span className="badge badge-cancelled"> abgesagt</span>}{' '}
                  <RsvpBadge o={o} />
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <Link className="small" to="/termine">
        Zum Kalender
      </Link>
    </div>
  )
}
