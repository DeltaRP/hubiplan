// Prüflisten vor folgenreichen Aktionen: was gute Praxis erwartet, zusätzlich zu
// den harten Fehlerprüfungen des Servers. Die Punkte blockieren nie.
// Eine Zeile erscheint nur, wenn sie für diesen Lauf überhaupt eine Rolle spielt.
import type { DecisionKey } from './content.ts'
import { t, tn } from '../i18n/index.ts'

export interface CheckItem {
  key: string
  ok: boolean
  text: string
  /** leiser Hinweis, wie man es behebt */
  fix?: string
  /** Link zur Stelle, an der man es behebt */
  to?: string
  why?: DecisionKey
  /** reiner Hinweis: zählt nicht als Punkt */
  info?: boolean
}

/** Zahlungsziel: unter 14 Tagen bleibt Mitgliedern kaum Zeit zu zahlen, bevor Mahnungen
 *  anstehen. Keine gesetzliche Mindestfrist; der Verzug ohne Mahnung tritt erst 30 Tage
 *  nach Fälligkeit ein (§ 286 Abs. 3 BGB). */
export const MIN_DUE_DAYS = 14

/** Vorabankündigung ohne andere Vereinbarung: 14 Kalendertage
 *  (SEPA Direct Debit Core Rulebook, EPC016-06, 2025 Version 1.0). */
export const DEFAULT_PRENOTIFICATION_DAYS = 14

/** Mandate verfallen nach 36 Monaten ohne Einzug (EPC016-06); ab drei Monaten
 *  vorher weist die Prüfliste darauf hin, damit Zeit für ein neues Mandat bleibt. */
export const MANDATE_EXPIRY_MONTHS = 36
export const MANDATE_WARN_MONTHS = 3

/** Prüfliste ab dieser Zahl Buchungen zeigen: ein Jahr ohne Buchungen braucht keine. */
export const MIN_BOOKINGS_FOR_RECEIPTS = 1

// --- vor dem Beitragslauf ---

export interface FeeRunInput {
  skipped: { reason: string }[]
  members: number
  dueDays: number
  /** Konto für Überweisungen mit IBAN */
  accountWithIban: boolean
  sepaEnabled: boolean
  checks?: { unreachable: number; with_mandate: number; open_change_requests: number }
}

export function feeRunChecks(input: FeeRunInput): CheckItem[] {
  const items: CheckItem[] = []
  const noType = input.skipped.filter((s) => !s.reason.startsWith('beitragsfrei')).length
  items.push({
    key: 'member_types',
    ok: noType === 0,
    text:
      noType === 0
        ? t('Alle Mitglieder haben eine Mitgliedsart.')
        : tn(
            '{n} Mitglied ohne Mitgliedsart, sie bekommen keine Rechnung.',
            '{n} Mitglieder ohne Mitgliedsart, sie bekommen keine Rechnung.',
            noType,
          ),
    fix: t('Mitgliedsart in der Mitgliedsakte nachtragen; die Namen stehen in der Vorschau.'),
  })
  items.push({
    key: 'account',
    ok: input.accountWithIban,
    text: input.accountWithIban
      ? t('Konto für Überweisungen mit IBAN hinterlegt.')
      : t('Auf der Rechnung steht noch kein Konto mit IBAN.'),
    fix: t('Konto unter Rechnung & Zahlung wählen.'),
    to: '/finanzen/einstellungen/rechnung',
  })
  items.push({
    key: 'due_days',
    ok: input.dueDays >= MIN_DUE_DAYS,
    text:
      input.dueDays >= MIN_DUE_DAYS
        ? t('Zahlungsziel {dueDays} Tage.', { dueDays: input.dueDays })
        : t('Zahlungsziel {dueDays} Tage (empfohlen mindestens {min}).', {
            dueDays: input.dueDays,
            min: MIN_DUE_DAYS,
          }),
    fix: t('Zahlungsziel unter Rechnung & Zahlung anpassen.'),
    to: '/finanzen/einstellungen/rechnung',
    why: 'due_days',
  })
  const c = input.checks
  if (c && input.members > 0) {
    items.push({
      key: 'unreachable',
      ok: c.unreachable === 0,
      text:
        c.unreachable === 0
          ? t('Alle Empfänger haben E-Mail oder vollständige Anschrift.')
          : tn(
              '{n} Mitglied ohne E-Mail und ohne vollständige Anschrift.',
              '{n} Mitglieder ohne E-Mail und ohne vollständige Anschrift.',
              c.unreachable,
            ),
      fix: t('Kontaktdaten in der Mitgliedsakte ergänzen, sonst kommt die Rechnung nicht an.'),
      to: '/mitglieder',
    })
    if (c.open_change_requests > 0)
      items.push({
        key: 'change_requests',
        ok: false,
        text: tn(
          '{n} offener Änderungsantrag von Mitgliedern.',
          '{n} offene Änderungsanträge von Mitgliedern.',
          c.open_change_requests,
        ),
        fix: t('Erst übernehmen oder ablehnen, damit Anschriften und Konten stimmen.'),
        to: '/mitglieder/anfragen/aenderungen',
      })
    if (input.sepaEnabled)
      items.push({
        key: 'mandates',
        ok: true,
        text: t('{with_mandate} von {members} Rechnungen lassen sich per Lastschrift einziehen.', {
          with_mandate: c.with_mandate,
          members: input.members,
        }),
        why: 'sepa_use',
        info: true,
      })
  }
  return items
}

// --- vor dem Lastschriftlauf ---

export interface DebitInput {
  creditorId: string
  creditorValid: boolean
  date: string
  earliest: string
  prenotificationDays: number
  invoices: { due_date?: string | null; has_email?: boolean }[]
  /** Mandate, die bald verfallen (letzter Einzug lange her) */
  expiringSoon?: number
}

/** Bankarbeitstage: Montag bis Freitag ohne die festen TARGET-Feiertage
 *  (Neujahr, Karfreitag, Ostermontag, 1. Mai, 25. und 26. Dezember; EPC016-06). */
export function isBankBusinessDay(iso: string): boolean {
  const date = new Date(`${iso}T12:00:00`)
  const day = date.getDay()
  if (day === 0 || day === 6) return false
  const md = iso.slice(5)
  if (['01-01', '05-01', '12-25', '12-26'].includes(md)) return false
  const easter = easterSunday(date.getFullYear())
  const diff = Math.round((date.getTime() - easter.getTime()) / 86400000)
  return diff !== -2 && diff !== 1
}

/** Ostersonntag nach der Gaußschen Osterformel (anonymer gregorianischer Algorithmus). */
export function easterSunday(year: number): Date {
  const a = year % 19
  const b = Math.floor(year / 100)
  const c = year % 100
  const d = Math.floor(b / 4)
  const e = b % 4
  const f = Math.floor((b + 8) / 25)
  const g = Math.floor((b - f + 1) / 3)
  const h = (19 * a + b - d - g + 15) % 30
  const i = Math.floor(c / 4)
  const k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7
  const m = Math.floor((a + 11 * h + 22 * l) / 451)
  const month = Math.floor((h + l - 7 * m + 114) / 31)
  const day = ((h + l - 7 * m + 114) % 31) + 1
  return new Date(year, month - 1, day, 12)
}

export function debitChecks(input: DebitInput): CheckItem[] {
  const items: CheckItem[] = []
  items.push({
    key: 'creditor',
    ok: input.creditorValid,
    text: input.creditorValid
      ? t('Gläubiger-ID hinterlegt.')
      : t('Gläubiger-ID fehlt oder ist ungültig.'),
    fix: t('Unter Rechnung & Zahlung → SEPA-Lastschrift eintragen.'),
    to: '/finanzen/einstellungen/rechnung',
  })
  if (input.date) {
    const business = isBankBusinessDay(input.date)
    items.push({
      key: 'business_day',
      ok: business,
      text: business
        ? t('Einzugsdatum ist ein Bankarbeitstag.')
        : t('Einzugsdatum fällt auf ein Wochenende oder einen Bankfeiertag.'),
      fix: t('Einen Werktag wählen; sonst bucht die Bank erst am nächsten Bankarbeitstag.'),
      why: 'collection_date',
    })
    const early = input.invoices.filter((i) => i.due_date && i.due_date > input.date).length
    if (input.invoices.some((i) => i.due_date))
      items.push({
        key: 'before_due',
        ok: early === 0,
        text:
          early === 0
            ? t('Keine Rechnung wird vor ihrer Fälligkeit eingezogen.')
            : tn(
                '{n} Rechnung wird vor der Fälligkeit eingezogen.',
                '{n} Rechnungen werden vor der Fälligkeit eingezogen.',
                early,
              ),
        fix: t('Späteres Einzugsdatum wählen oder diese Rechnungen abwählen.'),
        why: 'collection_date',
      })
  }
  const noMail = input.invoices.filter((i) => i.has_email === false).length
  if (input.invoices.some((i) => i.has_email !== undefined))
    items.push({
      key: 'prenotification_print',
      ok: noMail === 0,
      text:
        noMail === 0
          ? t('Alle Zahler bekommen die Vorabankündigung per E-Mail.')
          : tn(
              '{n} Vorabankündigung muss gedruckt werden (keine E-Mail).',
              '{n} Vorabankündigungen müssen gedruckt werden (keine E-Mail).',
              noMail,
            ),
      fix: t('Nach dem Erstellen ausdrucken und rechtzeitig verschicken.'),
      why: 'prenotification',
    })
  if (input.prenotificationDays < DEFAULT_PRENOTIFICATION_DAYS)
    items.push({
      key: 'prenotification_days',
      ok: false,
      text: t(
        'Vorabankündigung {prenotificationDays} Tage statt der üblichen {DEFAULT_PRENOTIFICATION_DAYS}.',
        { prenotificationDays: input.prenotificationDays, DEFAULT_PRENOTIFICATION_DAYS },
      ),
      fix: t(
        'Nur zulässig, wenn die kürzere Frist im Mandat oder in den Beitragsbedingungen steht.',
      ),
      to: '/finanzen/einstellungen/rechnung',
      why: 'prenotification',
    })
  if (input.expiringSoon)
    items.push({
      key: 'expiring',
      ok: false,
      text: tn(
        '{n} Mandat verfällt bald, weil lange nichts eingezogen wurde.',
        '{n} Mandate verfallen bald, weil lange nichts eingezogen wurde.',
        input.expiringSoon,
      ),
      fix: t('Mit diesem Lauf einziehen oder rechtzeitig ein neues Mandat einholen.'),
      to: '/finanzen/lastschrift/mandate',
    })
  items.push({
    key: 'submit',
    ok: true,
    text: t(
      'Datei rechtzeitig einreichen: Banken verlangen sie meist ein bis zwei Bankarbeitstage vor dem Einzug.',
    ),
    info: true,
  })
  return items
}

// --- vor dem Jahresabschluss ---

export interface ClosingInput {
  bookings: number
  without_receipt: number
  tax_areas_enabled: boolean
  categories_without_area: number
  open_invoices?: number
  unbooked_debit_runs?: number
}

export function closingChecks(c: ClosingInput): CheckItem[] {
  const items: CheckItem[] = []
  if (c.bookings >= MIN_BOOKINGS_FOR_RECEIPTS)
    items.push({
      key: 'receipts',
      ok: c.without_receipt === 0,
      text:
        c.without_receipt === 0
          ? t('Jede Buchung hat einen Beleg.')
          : tn('{n} Buchung ohne Beleg.', '{n} Buchungen ohne Beleg.', c.without_receipt),
      fix: t('Belege im Kassenbuch nachtragen, bevor die Kassenprüfer kommen.'),
      to: '/finanzen/kassenbuch',
      why: 'receipts',
    })
  if (c.tax_areas_enabled)
    items.push({
      key: 'tax_areas',
      ok: c.categories_without_area === 0,
      text:
        c.categories_without_area === 0
          ? t('Alle benutzten Kategorien haben einen steuerlichen Bereich.')
          : tn(
              '{n} benutzte Kategorie ohne steuerlichen Bereich.',
              '{n} benutzte Kategorien ohne steuerlichen Bereich.',
              c.categories_without_area,
            ),
      fix: t('Bereich unter Finanzen → Einrichtung → Kategorien zuordnen.'),
      to: '/finanzen/einstellungen/kategorien',
      why: 'tax_areas',
    })
  if (c.unbooked_debit_runs !== undefined && c.unbooked_debit_runs > 0)
    items.push({
      key: 'debit_runs',
      ok: false,
      text: tn(
        '{n} Lastschriftlauf ist noch nicht gebucht.',
        '{n} Lastschriftläufe sind noch nicht gebucht.',
        c.unbooked_debit_runs,
      ),
      fix: t('Nach dem Geldeingang den Lauf buchen.'),
      to: '/finanzen/lastschrift',
    })
  if (c.open_invoices !== undefined && c.open_invoices > 0)
    items.push({
      key: 'open_invoices',
      ok: false,
      text: tn(
        '{n} Rechnung des Jahres noch offen.',
        '{n} Rechnungen des Jahres noch offen.',
        c.open_invoices,
      ),
      fix: t('Zahlungen erfassen oder offene Beträge im Kassenbericht erläutern.'),
      to: '/finanzen/rechnungen',
    })
  items.push({
    key: 'audit',
    ok: true,
    text: t('Nach dem Abschluss ist das Jahr gesperrt; vorher die Kassenprüfung abschließen.'),
    why: 'cash_audit',
    info: true,
  })
  return items
}

// --- vor den Jahresbestätigungen (Zuwendungen) ---

export interface DonationInput {
  /** fehlende oder abgelaufene Angaben zum Bescheid (vom Server) */
  problems: string[]
  open: number
  without_address: number
  goods_without_documents: number
  goods_open: number
  fees_skipped: number
}

export function donationChecks(c: DonationInput): CheckItem[] {
  const items: CheckItem[] = [
    {
      key: 'notice',
      ok: c.problems.length === 0,
      text:
        c.problems.length === 0
          ? t('Angaben zum Bescheid vollständig und noch gültig.')
          : c.problems.join(' '),
      fix: t('Unter „Einstellungen“ den aktuellen Bescheid eintragen.'),
      to: '/finanzen/zuwendungen/einstellungen',
      why: 'donation_notice',
    },
  ]
  if (c.open > 0)
    items.push({
      key: 'address',
      ok: c.without_address === 0,
      text:
        c.without_address === 0
          ? t('Alle offenen Zuwendungen haben eine Anschrift.')
          : tn(
              '{n} offene Zuwendung ohne Anschrift.',
              '{n} offene Zuwendungen ohne Anschrift.',
              c.without_address,
            ),
      fix: t('Die Bestätigung nennt Name und Anschrift des Zuwendenden: Anschrift nachtragen.'),
      why: 'donation_liability',
    })
  if (c.goods_open > 0)
    items.push({
      key: 'goods',
      ok: c.goods_without_documents === 0,
      text:
        c.goods_without_documents === 0
          ? t('Zu allen Sachzuwendungen liegen Unterlagen zum Wert vor.')
          : tn(
              '{n} Sachzuwendung ohne Unterlagen zum Wert.',
              '{n} Sachzuwendungen ohne Unterlagen zum Wert.',
              c.goods_without_documents,
            ),
      fix: t('Kaufbeleg oder Gutachten besorgen und das Häkchen setzen.'),
      why: 'donation_goods',
    })
  if (c.goods_open > 0)
    items.push({
      key: 'goods_single',
      ok: true,
      text: tn(
        '{n} Sachzuwendung wird nicht gesammelt, sondern einzeln bestätigt.',
        '{n} Sachzuwendungen werden nicht gesammelt, sondern einzeln bestätigt.',
        c.goods_open,
      ),
      info: true,
    })
  if (c.fees_skipped > 0)
    items.push({
      key: 'fees',
      ok: true,
      text: tn(
        '{n} Mitgliedsbeitrag wird nach den Einstellungen nicht bestätigt.',
        '{n} Mitgliedsbeiträge werden nach den Einstellungen nicht bestätigt.',
        c.fees_skipped,
      ),
      why: 'donation_fees',
      info: true,
    })
  return items
}

// --- vor dem endgültigen Abschluss eines Wettbewerbs ---

export interface CompetitionFinishInput {
  /** Schützen ohne Ergebnis (Einzelwertungen) */
  missing: number
  openShootoffs: number
  bird: boolean
  /** Vogelschießen: Pfänder, die noch hängen */
  hangingPrizes: number
  website: 'aus' | 'live' | 'abschluss'
}

export function competitionFinishChecks(input: CompetitionFinishInput): CheckItem[] {
  const items: CheckItem[] = []
  if (input.bird) {
    items.push({
      key: 'prizes',
      ok: input.hangingPrizes === 0,
      text:
        input.hangingPrizes === 0
          ? t('Alle Pfänder sind gefallen.')
          : tn('{n} Pfand hängt noch.', '{n} Pfänder hängen noch.', input.hangingPrizes),
      fix: t('Nachtragen unter „Einrichten“, falls auf Papier gezählt wurde.'),
    })
  } else {
    items.push({
      key: 'results',
      ok: input.missing === 0,
      text:
        input.missing === 0
          ? t('Alle Schützen haben ein Ergebnis.')
          : tn('{n} Schütze ohne Ergebnis.', '{n} Schützen ohne Ergebnis.', input.missing),
      fix: t('Nachtragen oder bewusst ohne Ergebnis lassen; die Namen stehen unter „Auswertung“.'),
      why: 'comp_provisional',
    })
  }
  if (!input.bird) {
    items.push({
      key: 'shootoffs',
      ok: input.openShootoffs === 0,
      text:
        input.openShootoffs === 0
          ? t('Keine offenen Gleichstände auf Preisplätzen.')
          : tn(
              '{n} Gleichstand auf Preisplätzen ohne Stechen; der Abschluss ist erst danach möglich.',
              '{n} Gleichstände auf Preisplätzen ohne Stechen; der Abschluss ist erst danach möglich.',
              input.openShootoffs,
            ),
      fix: t('Stechen unter „Auswertung“ oder im Standmodus anlegen.'),
      why: 'comp_final',
    })
  }
  items.push({
    key: 'tablets',
    ok: true,
    info: true,
    text: t(
      'Auf jedem Tablet im Standmodus sollte „Alles gespeichert“ stehen, sonst fehlen Eingaben ohne Empfang.',
    ),
  })
  items.push({
    key: 'guests',
    ok: true,
    info: true,
    text: t('Gäste und Schützen außer Konkurrenz richtig markiert? Sie bekommen sonst Plätze.'),
  })
  items.push({
    key: 'website',
    ok: true,
    info: true,
    text:
      input.website === 'aus'
        ? t('Die Ergebnisse erscheinen nicht auf der Webseite.')
        : input.website === 'live'
          ? t('Die Ergebnisse stehen schon während des Schießens auf der Webseite.')
          : t('Nach dem Abschluss erscheinen die Ergebnisse auf der Webseite.'),
    why: 'comp_website',
  })
  return items
}
