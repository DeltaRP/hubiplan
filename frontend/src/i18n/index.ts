// Übersetzung der Oberfläche (konzepte/englisch.md).
//
// Deutsch ist Standard und Quellsprache: Der deutsche Text ist der Schlüssel.
//   t('Speichern')                         → „Save“
//   t('Hallo {name}', { name })            → Platzhalter in geschweiften Klammern
//   tn('{n} Mitglied', '{n} Mitglieder', n) → Einzahl/Mehrzahl, {n} wird gesetzt
//   tc('social', 'Beitrag')               → mit Zusammenhang, wenn ein Wort zweideutig ist
// Der englische Katalog (en.json) wird nur geladen, wenn Englisch gewählt ist. Fehlt ein
// Eintrag, erscheint der deutsche Text. `npm run i18n:check` meldet fehlende Einträge.
//
// Die Sprache steht im Cookie `hp_lang`; der Server hält es passend zum Konto. Beim Wechsel
// lädt die Seite neu, damit alle Texte und Formate (auch außerhalb von React) stimmen.

export type Lang = 'de' | 'en'
export const LANGS: readonly Lang[] = ['de', 'en']
const COOKIE = 'hp_lang'

/** Einzahl/Mehrzahl im Katalog */
export interface PluralEntry {
  one: string
  other: string
}
export type Catalog = Record<string, string | PluralEntry>

// null/undefined erscheinen wie in JSX als leerer Text
type Params = Record<string, string | number | null | undefined>

function readCookie(): Lang {
  if (typeof document === 'undefined') return 'de'
  const raw = document.cookie
    .split('; ')
    .find((c) => c.startsWith(`${COOKIE}=`))
    ?.split('=')[1]
  return raw === 'en' ? 'en' : 'de'
}

let current: Lang = readCookie()
let catalog: Catalog = {}

/** Aktive Sprache der Oberfläche */
export function lang(): Lang {
  return current
}

/** Gebietsschema für Datum, Zahl und Betrag: Englisch mit britischen Formaten (Fachfrage F4) */
export function locale(): 'de-DE' | 'en-GB' {
  return current === 'en' ? 'en-GB' : 'de-DE'
}

/** Katalog der aktiven Sprache laden (einmal beim Start, vor dem ersten Zeichnen). */
export async function loadCatalog(): Promise<void> {
  if (typeof document !== 'undefined') document.documentElement.lang = current
  if (current === 'de') return
  try {
    catalog = (await import('./en.json')).default as Catalog
  } catch {
    // Ohne Katalog bleibt die Oberfläche deutsch statt leer
    catalog = {}
  }
}

/** Für Tests: Sprache und Katalog direkt setzen */
export function setCatalogForTest(language: Lang, entries: Catalog = {}): void {
  current = language
  catalog = language === 'de' ? {} : entries
}

/** Sprache merken und die Seite neu laden (nur wenn sie sich ändert). */
export function switchLanguage(language: Lang, reload = true): void {
  if (typeof document === 'undefined') return
  const secure = location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${COOKIE}=${language}; Path=/; Max-Age=${365 * 24 * 3600}; SameSite=Lax${secure}`
  if (language !== current && reload) location.reload()
}

function fill(text: string, params?: Params): string {
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (all, key: string) =>
    key in params ? String(params[key] ?? '') : all,
  )
}

function lookup(key: string): string | PluralEntry | undefined {
  if (current === 'de') return undefined
  const entry = catalog[key]
  // Leere Einträge (noch nicht übersetzt) gelten als fehlend
  if (entry === '' || (typeof entry === 'object' && (!entry.one || !entry.other))) return undefined
  return entry
}

/** Text übersetzen; der deutsche Text ist der Schlüssel. */
export function t(text: string, params?: Params): string {
  const entry = lookup(text)
  return fill(typeof entry === 'string' ? entry : text, params)
}

/** Text mit Zusammenhang (für zweideutige Wörter wie „Beitrag“) */
export function tc(context: string, text: string, params?: Params): string {
  const entry = lookup(`${context}|${text}`)
  return fill(typeof entry === 'string' ? entry : text, params)
}

/** Einzahl oder Mehrzahl je nach n; {n} wird durch die formatierte Zahl ersetzt. */
export function tn(one: string, other: string, n: number, params?: Params): string {
  const entry = lookup(one)
  const rule = new Intl.PluralRules(locale()).select(n) === 'one' ? 'one' : 'other'
  const text = entry && typeof entry === 'object' ? entry[rule] : rule === 'one' ? one : other
  return fill(text, { n: n.toLocaleString(locale()), ...params })
}
