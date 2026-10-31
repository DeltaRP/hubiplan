import { describe, expect, it } from 'vitest'
import { formatMemberDate, jubileeWhen } from '../components/forms.ts'

describe('Genauigkeit für Mitgliedschaften', () => {
  it('zeigt Daten tages-, monats- oder jahresgenau', () => {
    expect(formatMemberDate('2001-03-15', 'day')).toBe('15.3.2001')
    expect(formatMemberDate('2001-03-15', 'month')).toBe('03/2001')
    expect(formatMemberDate('2001-03-15', 'year')).toBe('2001')
    expect(formatMemberDate(null, 'year')).toBe('–')
    expect(formatMemberDate('2001-03-15', undefined)).toBe('15.3.2001')
  })

  it('beschreibt den Jubiläumszeitpunkt', () => {
    expect(jubileeWhen('2026-01-01', 'year')).toBe('im Jahr 2026')
    expect(jubileeWhen('2026-03-01', 'month')).toBe('im März 2026')
    expect(jubileeWhen('2026-03-15', 'day')).toBe('am 15.3.2026')
  })
})
