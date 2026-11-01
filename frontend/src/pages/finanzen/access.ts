// Finanzen: Kasse (finance) und Beiträge/Rechnungen (billing) unter einem
// Menüpunkt. Welche Unterpunkte erscheinen, hängt von Modulen und Rechten ab.
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'
import { DEFAULT_TERMS } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

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
      (org.department_terms ?? DEFAULT_TERMS).dv_Vom ?? t('Von der übergeordneten Einheit'),
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
    { to: '/finanzen', label: t('Übersicht') },
    ...(a.finance ? [{ to: '/finanzen/entwicklung', label: t('Entwicklung') }] : []),
    ...(a.billing || a.received ? [{ to: '/finanzen/rechnungen', label: t('Rechnungen') }] : []),
    ...(a.sepa ? [{ to: '/finanzen/lastschrift', label: t('Lastschriften') }] : []),
    ...(a.finance ? [{ to: '/finanzen/kassenbuch', label: t('Kassenbuch') }] : []),
    ...(a.finance ? [{ to: '/finanzen/kontoauszuege', label: t('Kontoauszüge') }] : []),
    ...(a.finance ? [{ to: '/finanzen/quittungen', label: t('Quittungen') }] : []),
    ...(a.cashCounts ? [{ to: '/finanzen/kassenzaehlung', label: t('Kassenzählung') }] : []),
    ...(a.reserves ? [{ to: '/finanzen/ruecklagen', label: t('Rücklagen') }] : []),
    ...(a.donations ? [{ to: '/finanzen/zuwendungen', label: t('Zuwendungsbestätigungen') }] : []),
    ...(a.finance ? [{ to: '/finanzen/veranstaltungen', label: t('Veranstaltungen') }] : []),
    ...(a.finance ? [{ to: '/finanzen/abschluss', label: t('Abschluss & Berichte') }] : []),
    { to: '/finanzen/einstellungen', label: t('Einrichtung') },
  ]
}

export function invoiceTabs(a: FinanceAccess): NavItem[] {
  return [
    ...(a.billing
      ? [
          { to: '/finanzen/rechnungen', label: t('Rechnungen') },
          ...(a.feeRuns
            ? [{ to: '/finanzen/rechnungen/beitragslaeufe', label: t('Beitragsläufe') }]
            : []),
          { to: '/finanzen/rechnungen/mahnungen', label: t('Mahnungen') },
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
            ? [{ to: '/finanzen/einstellungen/beitraege', label: t('Beitragssätze') }]
            : []),
          { to: '/finanzen/einstellungen/mahnstufen', label: t('Mahnstufen') },
          { to: '/finanzen/einstellungen/rechnung', label: t('Rechnung & Zahlung') },
        ]
      : []),
    ...(a.finance
      ? [
          { to: '/finanzen/einstellungen/konten', label: t('Konten') },
          { to: '/finanzen/einstellungen/kategorien', label: t('Kategorien') },
        ]
      : []),
  ]
}
