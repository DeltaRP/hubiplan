// Prüft den englischen Katalog (src/i18n/en.json) gegen die Texte im Code.
//
//   node scripts/i18n-check.mjs           Bericht; Exit 0 (bis zur Abnahme nur Warnung)
//   node scripts/i18n-check.mjs --strict  Exit 1, wenn Übersetzungen fehlen
//   node scripts/i18n-check.mjs --add     fehlende Schlüssel mit leerem Wert eintragen
//   node scripts/i18n-check.mjs --list    alle fehlenden Schlüssel ausgeben
//
// Gefunden werden t('…'), tc('Zusammenhang', '…') und tn('Einzahl', 'Mehrzahl', n)
// mit festem Text. Leere Werte im Katalog gelten als fehlend.
import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('..', import.meta.url).pathname
const src = join(root, 'src')
const catalogPath = join(src, 'i18n', 'en.json')
const self = join(src, 'i18n', 'index.ts') // Beispiele in den Kommentaren
const args = new Set(process.argv.slice(2))

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'test' ? [] : files(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) && path !== self ? [path] : []
  })
}

// Einen String-Literal ab Position i lesen; liefert [Text, Ende] oder null
function literal(code, i) {
  const quote = code[i]
  if (quote !== "'" && quote !== '"' && quote !== '`') return null
  let out = ''
  for (let j = i + 1; j < code.length; j++) {
    const c = code[j]
    if (c === '\\') {
      const next = code[j + 1]
      out += next === 'n' ? '\n' : next === 't' ? '\t' : next
      j++
    } else if (quote === '`' && c === '$' && code[j + 1] === '{') {
      return null
    } else if (c === quote) {
      return [out, j + 1]
    } else {
      out += c
    }
  }
  return null
}

function skipSpace(code, i) {
  while (/\s/.test(code[i] ?? '')) i++
  return i
}

const used = new Map() // Schlüssel → erste Fundstelle
const dynamic = []
const call = /(?<![\w.$])(t|tc|tn)\(/g
for (const file of files(src)) {
  const code = readFileSync(file, 'utf8')
  for (const m of code.matchAll(call)) {
    const where = `${relative(root, file)}:${code.slice(0, m.index).split('\n').length}`
    let i = skipSpace(code, m.index + m[0].length)
    const first = literal(code, i)
    if (!first) {
      dynamic.push(where)
      continue
    }
    let key = first[0]
    if (m[1] === 'tc') {
      i = skipSpace(code, first[1])
      const second = code[i] === ',' ? literal(code, skipSpace(code, i + 1)) : null
      if (!second) {
        dynamic.push(where)
        continue
      }
      key = `${first[0]}|${second[0]}`
    }
    if (!used.has(key)) used.set(key, where)
  }
}

const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'))
const filled = (v) => (typeof v === 'string' ? v !== '' : !!v && v.one !== '' && v.other !== '')
const missing = [...used.keys()].filter((k) => !filled(catalog[k]))
const unused = Object.keys(catalog).filter((k) => !used.has(k))

console.log(
  `Übersetzung: ${used.size} Texte, ${used.size - missing.length} englisch, ` +
    `${missing.length} fehlen, ${unused.length} ungenutzt, ${dynamic.length} ohne festen Text`,
)
if (args.has('--list')) {
  for (const k of missing) console.log(`  fehlt: ${JSON.stringify(k)}  (${used.get(k)})`)
  for (const k of unused) console.log(`  ungenutzt: ${JSON.stringify(k)}`)
  for (const w of dynamic) console.log(`  ohne festen Text: ${w}`)
}
if (args.has('--add') && missing.length) {
  for (const k of missing) if (!(k in catalog)) catalog[k] = ''
  const sorted = Object.fromEntries(Object.entries(catalog).sort(([a], [b]) => a.localeCompare(b)))
  writeFileSync(catalogPath, `${JSON.stringify(sorted, null, 2)}\n`)
  console.log(`${missing.length} Schlüssel in en.json eingetragen.`)
}
if (args.has('--strict') && missing.length) process.exit(1)
