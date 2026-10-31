// Testdaten für den Terminkalender.
import { addDays, monthStart, today } from '../components/calendar/time.ts'

const day = (offset: number) => addDays(monthStart(today()), offset)

export function occurrence(over: Record<string, unknown> = {}) {
  return {
    key: '1-x',
    event_id: 1,
    title: 'Jahreshauptversammlung',
    starts_at: `${day(9)}T19:00:00+01:00`,
    ends_at: `${day(9)}T22:00:00+01:00`,
    original_start: `${day(9)}T19:00:00+01:00`,
    all_day: false,
    location: 'Vereinsheim',
    address: '',
    category: { id: 3, name: 'Versammlung', color: '#2f5f8f' },
    visibility: 'members',
    is_cancelled: false,
    note: '',
    is_moved: false,
    is_series: false,
    changed_at: null,
    owner: 'Hubertusverein',
    level: 'club',
    department_id: null,
    own: true,
    can_edit: true,
    rsvp_enabled: false,
    ...over,
  }
}
