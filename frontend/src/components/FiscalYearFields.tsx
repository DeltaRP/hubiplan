// Beginn des Geschäftsjahres (Tag und Monat); es dauert immer zwölf Monate.
import { SelectField } from './ui.tsx'

// oxlint-disable-next-line react/only-export-components
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

const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

/** „1. Juli bis 30. Juni“ bzw. „Kalenderjahr“. */
// oxlint-disable-next-line react/only-export-components
export function fiscalDescription(month: number, day: number): string {
  if (month === 1 && day === 1) return 'Kalenderjahr (1. Januar bis 31. Dezember)'
  const endDay = day === 1 ? DAYS_IN_MONTH[(month + 10) % 12] : day - 1
  const endMonth = day === 1 ? (month + 10) % 12 : month - 1
  return `${day}. ${MONTHS[month - 1]} bis ${endDay}. ${MONTHS[endMonth]}`
}

export function FiscalYearFields({
  month,
  day,
  error,
  onChange,
}: {
  month: number
  day: number
  error?: string
  onChange: (month: number, day: number) => void
}) {
  const maxDay = DAYS_IN_MONTH[month - 1]
  return (
    <>
      <div className="grid-2">
        <SelectField
          label="Geschäftsjahr beginnt am Tag"
          value={day}
          error={error}
          onChange={(e) => onChange(month, Number(e.target.value))}
        >
          {Array.from({ length: maxDay }, (_, i) => i + 1).map((d) => (
            <option key={d} value={d}>
              {d}.
            </option>
          ))}
        </SelectField>
        <SelectField
          label="im Monat"
          value={month}
          onChange={(e) => {
            const m = Number(e.target.value)
            onChange(m, Math.min(day, DAYS_IN_MONTH[m - 1]))
          }}
        >
          {MONTHS.map((name, i) => (
            <option key={name} value={i + 1}>
              {name}
            </option>
          ))}
        </SelectField>
      </div>
      <p className="muted small">Geschäftsjahr: {fiscalDescription(month, day)}</p>
    </>
  )
}
