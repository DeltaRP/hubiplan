// Datum und Uhrzeit in deutscher Zeit, unabhängig von der Zeitzone des Geräts.
import type { Occurrence } from '../../api/events.ts'

const TZ = 'Europe/Berlin'

const partsFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** „2026-06-13T14:00:00+02:00“ → { date: '2026-06-13', time: '14:00' } */
export function berlin(iso: string): { date: string; time: string } {
  const parts = Object.fromEntries(
    partsFormat.formatToParts(new Date(iso)).map((p) => [p.type, p.value]),
  )
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  }
}

/** Datum + Uhrzeit für die API (wird dort als deutsche Zeit gelesen). */
export function toApi(date: string, time = '00:00'): string {
  return `${date}T${time}:00`
}

export const WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
export const MONTHS = [
  'Januar',
  'Februar',
  'März',
  'April',
  'Mai',
  'Juni',
  'Juli',
  'August',
  'September',
  'Oktober',
  'November',
  'Dezember',
]

function utc(date: string): Date {
  const [y, m, d] = date.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}

export function iso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export function addDays(date: string, days: number): string {
  const d = utc(date)
  d.setUTCDate(d.getUTCDate() + days)
  return iso(d)
}

/** Wochentag 0 = Montag … 6 = Sonntag */
export function weekday(date: string): number {
  return (utc(date).getUTCDay() + 6) % 7
}

export function today(): string {
  return berlin(new Date().toISOString()).date
}

export function monthStart(date: string): string {
  return `${date.slice(0, 7)}-01`
}

export function addMonths(date: string, months: number): string {
  const d = utc(monthStart(date))
  d.setUTCMonth(d.getUTCMonth() + months)
  return iso(d)
}

/** Alle Tage der Monatsansicht: volle Wochen von Montag bis Sonntag. */
export function monthGrid(month: string): string[] {
  const first = monthStart(month)
  const start = addDays(first, -weekday(first))
  const last = addDays(addMonths(first, 1), -1)
  const end = addDays(last, 6 - weekday(last))
  const days: string[] = []
  for (let d = start; d <= end; d = addDays(d, 1)) days.push(d)
  return days
}

export function formatDay(date: string, withWeekday = true): string {
  const [y, m, d] = date.split('-')
  return `${withWeekday ? `${WEEKDAYS[weekday(date)]} ` : ''}${d}.${m}.${y}`
}

/** Lesbarer Zeitraum eines Termins, z. B. „Sa 13.06.2026, 14:00 – 18:00 Uhr“. */
export function formatRange(startIso: string, endIso: string, allDay: boolean): string {
  const s = berlin(startIso)
  const e = berlin(endIso)
  if (allDay) {
    return s.date === e.date
      ? `${formatDay(s.date)}, ganztägig`
      : `${formatDay(s.date)} – ${formatDay(e.date)}`
  }
  if (s.date === e.date) {
    return `${formatDay(s.date)}, ${s.time}${e.time !== s.time ? ` – ${e.time}` : ''} Uhr`
  }
  return `${formatDay(s.date)}, ${s.time} Uhr – ${formatDay(e.date)}, ${e.time} Uhr`
}

/** Tage zwischen `from` und `to`, an denen ein Termin erscheint (mehrtägig: jeder Tag).
 *
 * Nur der sichtbare Ausschnitt wird aufgezählt: Ein Termin über Monate erscheint
 * so auch in späteren Monaten, ohne alle Tage ab Beginn durchzugehen. */
export function daysOf(
  o: Pick<Occurrence, 'starts_at' | 'ends_at' | 'all_day'>,
  from: string,
  to: string,
): string[] {
  const start = berlin(o.starts_at).date
  let end = berlin(o.ends_at).date
  // Termin bis genau Mitternacht: endet am Vortag
  if (!o.all_day && end > start && berlin(o.ends_at).time === '00:00') end = addDays(end, -1)
  if (end < start) end = start
  const first = start > from ? start : from
  const last = end < to ? end : to
  const days: string[] = []
  for (let d = first; d <= last; d = addDays(d, 1)) days.push(d)
  return days
}
