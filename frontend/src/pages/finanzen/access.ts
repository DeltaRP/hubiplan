// Finanzen: Kasse (finance) und Beiträge/Rechnungen (billing) unter einem
// Menüpunkt. Welche Unterpunkte erscheinen, hängt von Modulen und Rechten ab.
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'
import { DEFAULT_TERMS } from '../../org/terms.ts'

export interface FinanceAccess {
  /** Kasse: Kassenbuch, Konten, Kategorien, Abschluss */
  finance: boolean
  financeEdit: boolean
  /** Beiträge und Rechnungen, Mahnungen, Lastschriften */
  billing: boolean
  billingEdit: boolean
  /** Beitragsläufe und Beitragssätze (nicht im Arbeitsbereich einer Untereinheit) */
  feeRuns: boolean
  /** SEPA-Lastschrift eingeschaltet: Lastschriftläufe und Mandate */
  sepa: boolean
  /** Rechnungen des Dachverbands an den Verein */
  received: boolean
  /** Name des Dachverbands mit Präposition, z. B. „Vom BSV“ */
  receivedLabel: string
  /** Zuwendungsbestätigungen: nur eingetragene Vereine mit Kasse */
  donations: boolean
  /** Zählprotokoll und Kassenbericht für Feste (zuschaltbar) */
  cashCounts: boolean
  /** Rücklagen nach § 62 AO (zuschaltbar) */
  reserves: boolean
}

export function financeAccess(org: OrgSummary | null): FinanceAccess {
  const none = {
    finance: false,
    financeEdit: false,
    billing: false,
    billingEdit: false,
    feeRuns: false,
    sepa: false,
    received: false,
    receivedLabel: '',
    donations: false,
    cashCounts: false,
    reserves: false,
  }
  if (!org || org.type === 'platform') return none
  const has = (p: string) => org.permissions.includes(p)
  const finance = org.modules.includes('finance') && has(PERM.financeView)
  const billing = org.modules.includes('billing') && has(PERM.billingView)
  return {
    finance,
    financeEdit: finance && has(PERM.financeEdit),
    billing,
    billingEdit: billing && has(PERM.billingEdit),
    feeRuns: billing && org.type !== 'unit',
    sepa: billing && org.type !== 'unit' && !!org.sepa_enabled,
    received: org.type === 'club' && !!org.parent_name && (finance || billing),
    receivedLabel:
      (org.department_terms ?? DEFAULT_TERMS).dv_Vom ?? 'Von der übergeordneten Einheit',
    // für jede Einheit mit Kasse; ausgestellt wird erst mit Schalter und gültigem Bescheid
    donations: finance,
    cashCounts: finance && !!org.cash_counts_enabled,
    reserves: finance && !!org.reserves_enabled,
  }
}

export interface NavItem {
  to: string
  label: string
}

/** Unterpunkte von Finanzen (Seitenleiste). */
export function financeSections(a: FinanceAccess): NavItem[] {
  if (!a.finance && !a.billing) return []
  return [
    { to: '/finanzen', label: 'Übersicht' },
    ...(a.finance ? [{ to: '/finanzen/entwicklung', label: 'Entwicklung' }] : []),
    ...(a.billing || a.received ? [{ to: '/finanzen/rechnungen', label: 'Rechnungen' }] : []),
    ...(a.sepa ? [{ to: '/finanzen/lastschrift', label: 'Lastschriften' }] : []),
    ...(a.finance ? [{ to: '/finanzen/kassenbuch', label: 'Kassenbuch' }] : []),
    ...(a.finance ? [{ to: '/finanzen/kontoauszuege', label: 'Kontoauszüge' }] : []),
    ...(a.finance ? [{ to: '/finanzen/quittungen', label: 'Quittungen' }] : []),
    ...(a.cashCounts ? [{ to: '/finanzen/kassenzaehlung', label: 'Kassenzählung' }] : []),
    ...(a.reserves ? [{ to: '/finanzen/ruecklagen', label: 'Rücklagen' }] : []),
    ...(a.donations ? [{ to: '/finanzen/zuwendungen', label: 'Zuwendungsbestätigungen' }] : []),
    ...(a.finance ? [{ to: '/finanzen/veranstaltungen', label: 'Veranstaltungen' }] : []),
    ...(a.finance ? [{ to: '/finanzen/abschluss', label: 'Abschluss & Berichte' }] : []),
    { to: '/finanzen/einstellungen', label: 'Einrichtung' },
  ]
}

export function invoiceTabs(a: FinanceAccess): NavItem[] {
  return [
    ...(a.billing
      ? [
          { to: '/finanzen/rechnungen', label: 'Rechnungen' },
          ...(a.feeRuns
            ? [{ to: '/finanzen/rechnungen/beitragslaeufe', label: 'Beitragsläufe' }]
            : []),
          { to: '/finanzen/rechnungen/mahnungen', label: 'Mahnungen' },
        ]
      : []),
    ...(a.received ? [{ to: '/finanzen/rechnungen/dachverband', label: a.receivedLabel }] : []),
  ]
}

export function settingsTabs(a: FinanceAccess): NavItem[] {
  return [
    ...(a.billing
      ? [
          ...(a.feeRuns
            ? [{ to: '/finanzen/einstellungen/beitraege', label: 'Beitragssätze' }]
            : []),
          { to: '/finanzen/einstellungen/mahnstufen', label: 'Mahnstufen' },
          { to: '/finanzen/einstellungen/rechnung', label: 'Rechnung & Zahlung' },
        ]
      : []),
    ...(a.finance
      ? [
          { to: '/finanzen/einstellungen/konten', label: 'Konten' },
          { to: '/finanzen/einstellungen/kategorien', label: 'Kategorien' },
        ]
      : []),
  ]
}
