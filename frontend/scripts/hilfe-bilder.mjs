// Bildschirmfotos der Hilfe (src/help/bilder.json) mit Playwright, je Sprache einmal.
// Aufruf nur über scripts/hilfe-bilder.sh (startet Backend und Oberfläche mit Demodaten).
//
//   BASE_URL=http://web:5173 DEMO_PASSWORD=… OUT=/out node scripts/hilfe-bilder.mjs [name …]
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright'

const base = process.env.BASE_URL ?? 'http://localhost:5173'
const password = process.env.DEMO_PASSWORD
const out = process.env.OUT ?? new URL('../public/hilfe-bilder', import.meta.url).pathname
if (!password) throw new Error('DEMO_PASSWORD fehlt')
const spec = JSON.parse(readFileSync(new URL('../src/help/bilder.json', import.meta.url), 'utf8'))
const only = new Set(process.argv.slice(2))
const images = spec.bilder.filter((b) => !only.size || only.has(b.name))

const browser = await chromium.launch()
let failed = 0
for (const language of ['de', 'en']) {
  mkdirSync(join(out, language), { recursive: true })
  const byUser = Map.groupBy(images, (b) => b.zugang)
  for (const [user, list] of byUser) {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 860 },
      deviceScaleFactor: 1,
      colorScheme: 'light',
      reducedMotion: 'reduce',
      locale: language === 'en' ? 'en-GB' : 'de-DE',
    })
    const page = await context.newPage()
    await page.goto(`${base}/anmelden`)
    await page.locator('input[autocomplete="username"]').fill(user)
    await page.locator('input[autocomplete="current-password"]').fill(password)
    await page.locator('button[type="submit"]').first().click()
    await page.waitForURL((u) => !u.pathname.startsWith('/anmelden'))
    // Sprache am Konto setzen; der Server stellt das Cookie passend ein
    const status = await page.evaluate(async (code) => {
      const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? ''
      const r = await fetch('/api/me/language/', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ language: code }),
      })
      return r.status
    }, language)
    if (status !== 200) throw new Error(`Sprache ${language} nicht wählbar (HTTP ${status})`)
    for (const b of list) {
      const file = join(out, language, `${b.name}.png`)
      try {
        await page.goto(`${base}${b.seite}`)
        await page.waitForLoadState('networkidle')
        await page
          .locator('main [role="status"]', { hasText: /Lädt|Loading/ })
          .waitFor({ state: 'detached' })
          .catch(() => {})
        const target = page.locator(b.ausschnitt ? `main ${b.ausschnitt}` : 'main').first()
        await target.waitFor({ state: 'visible', timeout: 15000 })
        await target.screenshot({ path: file, animations: 'disabled', caret: 'hide' })
        console.log(`${language}/${b.name}.png`)
      } catch (err) {
        failed++
        console.error(`FEHLER ${language}/${b.name}: ${err.message.split('\n')[0]}`)
      }
    }
    // Sprache zurück auf Deutsch, damit der Demozugang so bleibt wie vorher
    await page.evaluate(async () => {
      const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? ''
      await fetch('/api/me/language/', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ language: 'de' }),
      })
    })
    await context.close()
  }
}
await browser.close()
if (failed) {
  console.error(`${failed} Bild(er) fehlgeschlagen`)
  process.exit(1)
}
