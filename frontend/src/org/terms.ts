// Eigene Bezeichnung für Abteilungen (z. B. „Zug“) mit Artikel und Fällen.
// Das Backend liefert die Formen fertig (organizations/terms.py); hier nur
// Platzhalter füllen und Vorgaben für „Abteilung“.
import { useOptionalOrg } from './OrgContext.tsx'
import { lang } from '../i18n/index.ts'

export type DeptTerms = Record<string, string>

type Gender = 'f' | 'm' | 'n'

const FORMS: Record<string, [string, string, string]> = {
  nom: ['die', 'der', 'das'],
  akk: ['die', 'den', 'das'],
  dat: ['der', 'dem', 'dem'],
  gen: ['der', 'des', 'des'],
  ein: ['eine', 'ein', 'ein'],
  einen: ['eine', 'einen', 'ein'],
  einem: ['einer', 'einem', 'einem'],
  eines: ['einer', 'eines', 'eines'],
  kein: ['keine', 'kein', 'kein'],
  diese: ['diese', 'dieser', 'dieses'],
  diesem: ['dieser', 'diesem', 'diesem'],
  dieses: ['dieser', 'dieses', 'dieses'],
  diesen: ['diese', 'diesen', 'dieses'],
  deinem: ['deiner', 'deinem', 'deinem'],
  deines: ['deiner', 'deines', 'deines'],
  ihrem: ['ihrer', 'ihrem', 'ihrem'],
  ihres: ['ihrer', 'ihres', 'ihres'],
  im: ['in der', 'im', 'im'],
  zum: ['zur', 'zum', 'zum'],
  vom: ['von der', 'vom', 'vom'],
  beim: ['bei der', 'beim', 'beim'],
  deinen: ['deine', 'deinen', 'dein'],
  ihren: ['ihre', 'ihren', 'ihr'],
  unser: ['unsere', 'unser', 'unser'],
  ein_anderer: ['eine andere', 'ein anderer', 'ein anderes'],
  einen_anderen: ['eine andere', 'einen anderen', 'ein anderes'],
  einem_anderen: ['einer anderen', 'einem anderen', 'einem anderen'],
  eines_anderen: ['einer anderen', 'eines anderen', 'eines anderen'],
  der_andere: ['die andere', 'der andere', 'das andere'],
  den_anderen: ['die andere', 'den anderen', 'das andere'],
  beim_anderen: ['bei der anderen', 'beim anderen', 'beim anderen'],
}
const GENITIVE_KEYS = new Set(['gen', 'eines', 'dieses', 'deines', 'ihres', 'eines_anderen'])
const GENDERS: Gender[] = ['f', 'm', 'n']
const ADJ = ['e', 'er', 'es']

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

export function genitiveOf(label: string, gender: string): string {
  if (gender === 'f' || !label) return label
  return /(s|ß|x|z)$/.test(label) ? `${label}es` : `${label}s`
}

/** Gleiche Formen wie organizations/terms.py (für Vorschau und Tests). */
export function buildTerms(
  label: string,
  plural: string,
  gender: string = 'f',
  genitive = '',
): DeptTerms {
  const g = (GENDERS.includes(gender as Gender) ? gender : 'f') as Gender
  const idx = GENDERS.indexOf(g)
  const sg = label || 'Abteilung'
  const pl = plural || 'Abteilungen'
  const gen = genitive || genitiveOf(sg, g)
  const tm: DeptTerms = {
    sg,
    pl,
    sg_gen: gen,
    pl_dat: /(n|s)$/.test(pl) ? pl : `${pl}n`,
  }
  for (const [key, forms] of Object.entries(FORMS)) {
    tm[key] = `${forms[idx]} ${GENITIVE_KEYS.has(key) ? gen : sg}`
  }
  for (const key of Object.keys(tm)) tm[cap(key)] = cap(tm[key])
  tm.gender = g
  tm.adj = ADJ[idx]
  return tm
}

// Englisch (Konzept englisch.md, 4.3): keine Fälle, ein Artikel; gleiche Platzhalter.
const FORMS_EN: Record<string, string> = {
  nom: 'the',
  akk: 'the',
  dat: 'the',
  gen: 'the',
  ein: 'a',
  einen: 'a',
  einem: 'a',
  eines: 'a',
  kein: 'no',
  diese: 'this',
  diesem: 'this',
  dieses: 'this',
  diesen: 'this',
  deinem: 'your',
  deines: 'your',
  deinen: 'your',
  ihrem: 'their',
  ihres: 'their',
  ihren: 'their',
  im: 'in the',
  zum: 'to the',
  vom: 'from the',
  beim: 'at the',
  unser: 'our',
  ein_anderer: 'another',
  einen_anderen: 'another',
  einem_anderen: 'another',
  eines_anderen: 'another',
  der_andere: 'the other',
  den_anderen: 'the other',
  beim_anderen: 'at the other',
}

/** Vorgaben auf Englisch; eigene Bezeichnungen ohne englische Form bleiben deutsch (F7). */
export const ENGLISH_DEFAULTS: Record<string, [string, string]> = {
  Abteilung: ['department', 'departments'],
  Verein: ['club', 'clubs'],
  Dachverband: ['umbrella association', 'umbrella associations'],
  Plattform: ['platform', 'platforms'],
  Einheit: ['unit', 'units'],
  Gruppe: ['group', 'groups'],
}

export function englishLabel(
  label: string,
  plural: string,
  labelEn = '',
  pluralEn = '',
): [string, string] {
  if (labelEn) return [labelEn, pluralEn || labelEn]
  return ENGLISH_DEFAULTS[label] ?? [label, plural || label]
}

/** Englische Formen (wie organizations/terms.py ``build_terms_en``). */
export function buildTermsEn(
  label: string,
  plural: string,
  gender: string = 'f',
  labelEn = '',
  pluralEn = '',
): DeptTerms {
  const [sg, pl] = englishLabel(label || 'Abteilung', plural || 'Abteilungen', labelEn, pluralEn)
  const tm: DeptTerms = { sg, pl, sg_gen: sg, pl_dat: pl }
  const an = /^(?!uni|use|eu|one)[aeiou]/i.test(sg) ? 'an' : 'a'
  for (const [key, article] of Object.entries(FORMS_EN)) {
    tm[key] = `${article === 'a' ? an : article} ${sg}`
  }
  for (const key of Object.keys(tm)) tm[cap(key)] = cap(tm[key])
  tm.gender = GENDERS.includes(gender as Gender) ? gender : 'f'
  tm.adj = ''
  return tm
}

/** Formen in der Sprache der Oberfläche. */
export function termsFor(
  label: string,
  plural: string,
  gender: string = 'f',
  genitive = '',
  labelEn = '',
  pluralEn = '',
): DeptTerms {
  return lang() === 'en'
    ? buildTermsEn(label, plural, gender, labelEn, pluralEn)
    : buildTerms(label, plural, gender, genitive)
}

/**
 * Name des Dachverbands in Texten eines Vereins (Platzhalter mit ``dv_``,
 * z. B. {dv_im} „im BSV“, {dv_akk} „den BSV“). Ohne Namen: „Dachverband“.
 * ``dv_has`` ist '1', wenn der Verein zu einem Dachverband gehört.
 */
export function buildFederationTerms(name = '', gender = 'm', genitive = ''): DeptTerms {
  const base = name
    ? termsFor(name, name, gender || 'm', genitive || name, name)
    : termsFor('Dachverband', 'Dachverbände', 'm', 'Dachverbands')
  const tm: DeptTerms = {}
  for (const [key, value] of Object.entries(base)) {
    if (!/^pl/i.test(key)) tm[`dv_${key}`] = value
  }
  tm.dv_has = name ? '1' : ''
  return tm
}

export const DEFAULT_FED_TERMS: DeptTerms = buildFederationTerms()

/**
 * Eigene Bezeichnung einer Einheit (z. B. „Verein“, „Zug“) mit Vorsilbe ``e_``:
 * {e_sg} „Verein“, {e_im} „im Verein“, {e_gen} „des Vereins“, {e_pl} „Vereine“,
 * {e_eines_anderen} „eines anderen Vereins“. Ohne Bezeichnung: „Einheit“.
 */
export function buildOwnTerms(
  label = '',
  plural = '',
  gender = 'f',
  genitive = '',
  labelEn = '',
  pluralEn = '',
): DeptTerms {
  const base = label
    ? termsFor(label, plural || label, gender, genitive, labelEn, pluralEn)
    : termsFor('Einheit', 'Einheiten', 'f')
  const tm: DeptTerms = {}
  for (const [key, value] of Object.entries(base)) tm[`e_${key}`] = value
  return tm
}

export const DEFAULT_OWN_TERMS: DeptTerms = buildOwnTerms()

export const DEFAULT_TERMS: DeptTerms = {
  ...termsFor('Abteilung', 'Abteilungen', 'f'),
  ...DEFAULT_FED_TERMS,
  ...DEFAULT_OWN_TERMS,
}

/** Platzhalter wie {gen} oder {Pl} füllen; unbekannte bleiben stehen. */
export function fillTerms(text: string, terms: DeptTerms = DEFAULT_TERMS): string {
  return text.replace(
    /\{(\w+)\}/g,
    (all, key: string) => terms[key] ?? DEFAULT_FED_TERMS[key] ?? DEFAULT_OWN_TERMS[key] ?? all,
  )
}

/** Eigene Formen aus Bezeichnung oder Typ, falls der Server keine liefert. */
function ownFallback(
  org?: {
    label?: string
    label_plural?: string
    label_gender?: string
    label_genitive?: string
    label_en?: string
    label_plural_en?: string
    type?: string
  } | null,
): DeptTerms {
  if (org?.label)
    return buildOwnTerms(
      org.label,
      org.label_plural,
      org.label_gender,
      org.label_genitive,
      org.label_en,
      org.label_plural_en,
    )
  if (org?.type === 'federation')
    return buildOwnTerms('Dachverband', 'Dachverbände', 'm', 'Dachverbands')
  if (org?.type === 'club') return buildOwnTerms('Verein', 'Vereine', 'm', 'Vereins')
  return DEFAULT_OWN_TERMS
}

/** Formen für den aktiven Bereich (Verein, Abteilungsbereich, Mitgliederbereich). */
export function useTerms(): DeptTerms {
  const ctx = useOptionalOrg()
  const active = ctx?.active
  if (active) {
    const terms = active.department_terms
    const children =
      terms ??
      (active.type === 'federation' ? termsFor('Verein', 'Vereine', 'm', 'Vereins') : DEFAULT_TERMS)
    return terms?.e_sg ? terms : { ...DEFAULT_FED_TERMS, ...children, ...ownFallback(active) }
  }
  return ctx?.activeDept?.terms ?? ctx?.activePortal?.terms ?? DEFAULT_TERMS
}

/** Formen aus einer Organisation (Zusammenfassung oder Detail), sonst die Vorgaben. */
export function orgTerms(org?: { department_terms?: DeptTerms } | null): DeptTerms {
  return { ...DEFAULT_FED_TERMS, ...DEFAULT_OWN_TERMS, ...(org?.department_terms ?? DEFAULT_TERMS) }
}
