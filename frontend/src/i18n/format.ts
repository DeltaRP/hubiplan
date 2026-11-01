// Datum, Zeit, Zahl und Betrag in der Sprache der Oberfläche (Englisch: britische Formate).
// Eingaben nehmen in beiden Sprachen die deutsche Schreibweise an; hier geht es nur um Anzeige.
import { locale } from './index.ts'

export function formatDay(value: Date | string, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleDateString(locale(), options)
}

export function formatTime(value: Date | string, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleTimeString(locale(), options)
}

export function formatDayTime(value: Date | string, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleString(locale(), options)
}

export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  return n.toLocaleString(locale(), options)
}

export function formatEuro(n: number): string {
  return new Intl.NumberFormat(locale(), { style: 'currency', currency: 'EUR' }).format(n)
}
