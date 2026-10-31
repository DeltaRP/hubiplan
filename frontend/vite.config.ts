/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { thirdPartyNotices } from './lizenzen/plugin.ts'

// Im Entwicklungsmodus leitet Vite API-Aufrufe ans Django-Backend weiter.
// So laufen Frontend und Backend für den Browser unter derselben Adresse
// (wichtig für Session-Cookie und CSRF-Schutz).
const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'
const proxy = Object.fromEntries(
  ['/api', '/_allauth', '/admin', '/static', '/media'].map((path) => [path, { target: backend }]),
)

export default defineConfig({
  plugins: [react(), thirdPartyNotices()],
  server: {
    host: true,
    port: 5173,
    proxy,
  },
  test: {
    environment: 'jsdom',
    // jsdom nur einmal je Worker statt je Testdatei (jede Datei bleibt trotzdem für sich);
    // halbiert die Laufzeit. Folge: window.location lässt sich nicht ersetzen, Weiterleitungen
    // laufen deshalb über leaveTo.go (api/peering.ts).
    pool: 'vmThreads',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    // Das Vorladen aller Seiten (setup.ts) braucht bei voller Last mehr als die üblichen 10 s
    hookTimeout: 60_000,
    // Platz für die längeren Wartezeiten von findBy… (setup.ts) unter Last
    testTimeout: 30_000,
  },
})
