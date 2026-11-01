// Hilfe: Anleitungen und Seitenhilfen (konzepte/hilfe-funktion.md, docs/hilfe.md).
//
// Jeder Eintrag ist eine Markdown-Datei je Sprache unter ./de und ./en mit gleichem
// Dateinamen. Oben steht ein Kopf zwischen zwei Zeilen „---“:
//
//   key: guide.password          eindeutiger Schlüssel (guide.… oder page.…)
//   titel: Passwort ändern
//   bereich: konto               Gruppe auf der Hilfe-Seite (AREAS)
//   modul: members               nur, wenn das Modul freigeschaltet ist (leer: immer)
//   rechte: [members.edit]       eines davon nötig (leer: alle Angemeldeten)
//   routen: [/mein-konto/anmeldung]
//   stichworte: [Kennwort, Login]
//
// Seitenhilfen (Ordner seiten/) gehören zu ihren Routen; Anleitungen (anleitungen/)
// erscheinen auf diesen Routen als „Häufige Aufgaben“. Bilder: ![Text](bild:name),
// erzeugt von scripts/hilfe-bilder.sh nach src/help/bilder.json.
import type { Lang } from '../i18n/index.ts'

export type HelpKind = 'guide' | 'page'

export interface HelpEntry {
  key: string
  kind: HelpKind
  file: string
  /** Adresse unter /hilfe/, z. B. „passwort-aendern“ oder „seite/mein-konto“ */
  slug: string
  title: string
  area: string
  module?: string
  rights: string[]
  routes: string[]
  keywords: string[]
  body: string
}

/** Bereiche der Hilfe-Seite in dieser Reihenfolge; die Namen stehen in HelpPage (areaLabel). */
export const AREAS = [
  'start',
  'konto',
  'mitglieder',
  'beitraege',
  'finanzen',
  'termine',
  'rundschreiben',
  'meldungen',
  'wettbewerbe',
  'webseite',
  'einstellungen',
  'mein-bereich',
] as const
export type Area = (typeof AREAS)[number]

const LIST_FIELDS = new Set(['rechte', 'routen', 'stichworte'])

/** Kopf und Text einer Hilfedatei lesen. Wirft bei Formfehlern (Test prüft alle Dateien). */
export function parseHelpFile(file: string, raw: string): HelpEntry {
  const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(raw.replace(/\r\n/g, '\n'))
  if (!m) throw new Error(`${file}: Kopf fehlt`)
  const meta: Record<string, string | string[]> = {}
  for (const line of m[1].split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue
    const kv = /^([a-z]+):\s*(.*)$/.exec(line)
    if (!kv) throw new Error(`${file}: Zeile „${line}“ unverständlich`)
    const [, name, value] = kv
    if (LIST_FIELDS.has(name)) {
      const list = /^\[(.*)\]$/.exec(value.trim())
      if (!list) throw new Error(`${file}: ${name} braucht [a, b]`)
      meta[name] = list[1]
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    } else meta[name] = value.trim()
  }
  const str = (k: string) => (typeof meta[k] === 'string' ? (meta[k] as string) : '')
  const list = (k: string) => (Array.isArray(meta[k]) ? (meta[k] as string[]) : [])
  const key = str('key')
  const kind: HelpKind = key.startsWith('page.') ? 'page' : 'guide'
  if (!/^(guide|page)\.[a-z0-9_]+$/.test(key)) throw new Error(`${file}: key „${key}“ ungültig`)
  if (!str('titel')) throw new Error(`${file}: titel fehlt`)
  return {
    key,
    kind,
    file,
    slug: file
      .replace(/^anleitungen\//, '')
      .replace(/^seiten\//, 'seite/')
      .replace(/\.md$/, ''),
    title: str('titel'),
    area: str('bereich'),
    module: str('modul') || undefined,
    rights: list('rechte'),
    routes: list('routen'),
    keywords: list('stichworte'),
    body: m[2].trim(),
  }
}

type Loader = () => Promise<string>
// Nur die gewählte Sprache wird geladen, und erst, wenn jemand die Hilfe öffnet
const FILES: Record<Lang, Record<string, Loader>> = {
  de: import.meta.glob('./de/**/*.md', { query: '?raw', import: 'default' }) as Record<
    string,
    Loader
  >,
  en: import.meta.glob('./en/**/*.md', { query: '?raw', import: 'default' }) as Record<
    string,
    Loader
  >,
}

/** Dateiname ohne Sprachordner, z. B. „anleitungen/passwort.md“ */
export const relName = (path: string) => path.replace(/^\.\/(de|en)\//, '')

const cache = new Map<Lang, Promise<HelpEntry[]>>()

/** Alle Einträge einer Sprache (fehlt eine englische Datei, gilt die deutsche). */
export function loadHelp(language: Lang): Promise<HelpEntry[]> {
  let p = cache.get(language)
  if (!p) {
    p = (async () => {
      const de = FILES.de
      const own = FILES[language]
      const byName = new Map(Object.entries(own).map(([path, load]) => [relName(path), load]))
      return Promise.all(
        Object.entries(de).map(async ([path, load]) => {
          const name = relName(path)
          const raw = await (byName.get(name) ?? load)()
          return parseHelpFile(name, raw)
        }),
      )
    })()
    cache.set(language, p)
    // Fehler nicht zwischenspeichern, beim nächsten Öffnen erneut versuchen
    p.catch(() => cache.delete(language))
  }
  return p
}

/** Darf diese Person den Eintrag sehen? Modul freigeschaltet und eines der Rechte. */
export function visibleFor(
  entry: Pick<HelpEntry, 'module' | 'rights'>,
  hasModule: (m: string) => boolean,
  hasRight: (r: string) => boolean,
): boolean {
  if (entry.module && !hasModule(entry.module)) return false
  return entry.rights.length === 0 || entry.rights.some(hasRight)
}

/** Passt die Route zur Adresse? Gleich oder darunter (/mitglieder passt zu /mitglieder/5). */
export function routeMatches(route: string, pathname: string): boolean {
  return pathname === route || pathname.startsWith(`${route.replace(/\/$/, '')}/`)
}

/** Seitenhilfe zur Adresse: die Route mit dem längsten Treffer gewinnt. */
export function pageHelpFor(entries: HelpEntry[], pathname: string): HelpEntry | null {
  let best: HelpEntry | null = null
  let len = -1
  for (const e of entries) {
    if (e.kind !== 'page') continue
    for (const r of e.routes)
      if (routeMatches(r, pathname) && r.length > len) {
        best = e
        len = r.length
      }
  }
  return best
}

/** Anleitungen für die Seite (genau diese Route oder eine darüber). */
export function guidesFor(entries: HelpEntry[], pathname: string): HelpEntry[] {
  return entries.filter(
    (e) => e.kind === 'guide' && e.routes.some((r) => routeMatches(r, pathname)),
  )
}

/** Alle Wörter der Suche müssen vorkommen (Groß-/Kleinschreibung egal). */
export function matchesQuery(query: string, ...texts: (string | undefined)[]): boolean {
  const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const hay = texts.filter(Boolean).join(' ').toLocaleLowerCase()
  return words.every((w) => hay.includes(w))
}

/** Bilder im Text: bild:name → Datei der Sprache. */
export const IMAGE_PREFIX = 'bild:'
export const imageUrl = (name: string, language: Lang) => `/hilfe-bilder/${language}/${name}.png`

/** Namen aller Bilder in einem Text */
export function imagesIn(body: string): string[] {
  return [...body.matchAll(/!\[[^\]]*\]\(bild:([a-z0-9-]+)\)/g)].map((m) => m[1])
}
