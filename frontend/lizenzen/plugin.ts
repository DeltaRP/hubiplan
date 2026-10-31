// Erzeugt beim Bauen die Lizenzhinweise der Bibliotheken, die tatsächlich im
// ausgelieferten Browser-Code stecken (lizenzen/drittanbieter.txt im Build).
// MIT, ISC und BSD verlangen, dass ihre Lizenztexte jede Kopie begleiten.
// Fehlt für ein Paket der Lizenztext, bricht der Build ab, statt still zu schweigen.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'

const HERE = dirname(fileURLToPath(import.meta.url))
const NODE_MODULES = join(HERE, '..', 'node_modules')
export const NOTICE_FILE = 'lizenzen/drittanbieter.txt'

// Hilfscode der Werkzeuge, den der Bundler selbst einfügt
const VIRTUAL: [string, string][] = [
  ['\0rolldown/', 'rolldown'],
  ['\0vite/', 'vite'],
]

/** Paketname zu einer Modul-ID aus node_modules, sonst null. */
export function packageOf(id: string): string | null {
  for (const [prefix, name] of VIRTUAL) if (id.startsWith(prefix)) return name
  const path = packagePathOf(id)
  if (!path) return null
  const parts = path.split('/node_modules/').pop()!.split('/')
  return parts[0].startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0]
}

/**
 * Pfad des Pakets innerhalb von node_modules, z. B. „markdown-it/node_modules/entities“.
 * Verschachtelte Pakete behalten ihren Pfad, damit die Lizenz der tatsächlich
 * gebündelten Version gelesen wird und nicht die eines gleichnamigen Pakets
 * auf oberster Ebene (Lizenzaudit 31.10.2026, L07: entities 4.5.0 und 8.1.0).
 */
export function packagePathOf(id: string): string | null {
  for (const [prefix, name] of VIRTUAL) if (id.startsWith(prefix)) return name
  const marker = '/node_modules/'
  const at = id.indexOf(marker)
  if (at < 0) return null
  const parts = id.slice(at + marker.length).split('/')
  const path: string[] = []
  let i = 0
  for (;;) {
    const take = parts[i].startsWith('@') ? 2 : 1
    path.push(...parts.slice(i, i + take))
    i += take
    if (parts[i] !== 'node_modules' || i + 1 >= parts.length) break
    path.push('node_modules')
    i += 1
  }
  return path.join('/')
}

function licenseText(dir: string, name: string): string {
  // auch LICENSE-MIT.txt (z. B. punycode.js)
  const file = readdirSync(dir).find((f) =>
    /^(licen[cs]e|copying)(-[a-z0-9.]+)?(\.(md|txt))?$/i.test(f),
  )
  if (!file) throw new Error(`Lizenztext fehlt für ${name} (${dir})`)
  let text = readFileSync(join(dir, file), 'utf8').trim()
  // Vite listet darunter die Lizenzen seiner eigenen Werkzeug-Abhängigkeiten;
  // im Browser landet nur Code von Vite selbst
  if (name === 'vite') text = text.split(/^# Licenses of bundled dependencies/m)[0].trim()
  return text
}

/** Text der Hinweisdatei für die angegebenen Modul-IDs. */
export function buildNotices(ids: Iterable<string>, root = NODE_MODULES): string {
  const paths = new Set<string>()
  for (const id of ids) {
    if (id.startsWith('\0') && !packageOf(id)) throw new Error(`Unbekanntes Hilfsmodul ${id}`)
    const path = packagePathOf(id)
    if (path) paths.add(path)
  }
  const entries = [...paths].map((path) => {
    const name = packageOf(`/node_modules/${path}/x`)!
    const dir = join(root, path)
    const pkg = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'))
    return { name, path, dir, pkg }
  })
  entries.sort((a, b) => a.name.localeCompare(b.name) || a.pkg.version.localeCompare(b.pkg.version))
  const blocks = entries.map(({ name, path, dir, pkg }) => {
    const rule = '='.repeat(78)
    // Bei verschachtelten Paketen den Pfad nennen, damit klar ist, welche Kopie gemeint ist
    const where = path.includes('/node_modules/') ? `\n(node_modules/${path})` : ''
    return `${rule}\n${name} ${pkg.version} (${pkg.license})${where}\n${rule}\n\n${licenseText(dir, name)}\n`
  })
  const extra = join(HERE, 'zusatz.txt')
  const head = readFileSync(join(HERE, 'kopf.txt'), 'utf8').trim()
  return [head, ...blocks, existsSync(extra) ? readFileSync(extra, 'utf8').trim() : '']
    .join('\n\n')
    .concat('\n')
}

export function thirdPartyNotices(): Plugin {
  return {
    name: 'hubiplan-lizenzen',
    apply: 'build',
    generateBundle(_options, bundle) {
      const ids = new Set<string>()
      for (const item of Object.values(bundle))
        if (item.type === 'chunk') for (const id of item.moduleIds) ids.add(id)
      try {
        this.emitFile({ type: 'asset', fileName: NOTICE_FILE, source: buildNotices(ids) })
      } catch (err) {
        this.error(err instanceof Error ? err.message : String(err))
      }
    },
  }
}
