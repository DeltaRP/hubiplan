// Lizenzaudit 29.10.2026 Teil d (F01/F04/F05): Lizenzhinweise aus dem Bundle.
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildNotices, packageOf, packagePathOf } from './plugin.ts'

describe('Lizenzhinweise', () => {
  it('ordnet Module ihren Paketen zu', () => {
    expect(packageOf('/app/node_modules/react/index.js')).toBe('react')
    expect(packageOf('/app/node_modules/@scope/pkg/lib/a.js')).toBe('@scope/pkg')
    expect(packageOf('/app/node_modules/a/node_modules/b/x.js')).toBe('b')
    expect(packageOf('\0rolldown/runtime.js')).toBe('rolldown')
    expect(packageOf('\0vite/preload-helper.js')).toBe('vite')
    expect(packageOf('/app/src/main.tsx')).toBeNull()
  })

  it('enthält Paketlizenzen und übernommenen Fremdcode', () => {
    const text = buildNotices([
      '/app/node_modules/react/index.js',
      '/app/node_modules/qrcode.react/lib/esm/index.js',
      '/app/node_modules/normalize-wheel/index.js',
      '\0vite/preload-helper.js',
      '/app/src/main.tsx',
    ])
    expect(text).toMatch(/^react \d+\.\d+\.\d+ \(MIT\)$/m)
    expect(text).toMatch(/^qrcode\.react \S+ \(ISC\)$/m)
    expect(text).toContain('Copyright (c) Project Nayuki.')
    expect(text).toContain('Modernizr')
    expect(text).toContain('/lizenzen/LICENSE.txt')
    // Fachfrage 2: Symbole neu gezeichnet, keine Feather-Vorlage mehr
    expect(text).not.toContain('Feather')
    // Von Vite nur die eigene Lizenz, nicht die Liste seiner Werkzeuge
    expect(text).toContain('VoidZero Inc. and Vite contributors')
    expect(text).not.toContain('Licenses of bundled dependencies')
    expect(text).not.toMatch(/^main\.tsx/m)
  })

  // Lizenzaudit 31.10.2026, L07: verschachtelte Pakete mit eigener Version
  it('liest verschachtelte Pakete aus ihrem eigenen Ordner', () => {
    expect(packagePathOf('/app/node_modules/a/node_modules/b/x.js')).toBe('a/node_modules/b')
    expect(packagePathOf('/app/node_modules/@s/a/node_modules/@t/b/x.js')).toBe(
      '@s/a/node_modules/@t/b',
    )
    expect(packagePathOf('/app/node_modules/react/index.js')).toBe('react')

    const root = mkdtempSync(join(tmpdir(), 'lizenzen-'))
    const pkg = (dir: string, version: string, text: string) => {
      mkdirSync(join(root, dir), { recursive: true })
      writeFileSync(
        join(root, dir, 'package.json'),
        JSON.stringify({ version, license: 'BSD-2-Clause' }),
      )
      writeFileSync(join(root, dir, 'LICENSE'), text)
    }
    pkg('entities', '8.1.0', 'Text der Version 8')
    pkg('markdown-it', '14.3.3', 'Text von markdown-it')
    pkg('markdown-it/node_modules/entities', '4.5.0', 'Text der Version 4')
    const text = buildNotices(
      [
        '/app/node_modules/markdown-it/index.mjs',
        '/app/node_modules/markdown-it/node_modules/entities/lib/esm/decode.js',
      ],
      root,
    )
    expect(text).toMatch(/^entities 4\.5\.0 \(BSD-2-Clause\)$/m)
    expect(text).toContain('(node_modules/markdown-it/node_modules/entities)')
    expect(text).toContain('Text der Version 4')
    expect(text).not.toContain('8.1.0')
    expect(text).not.toContain('Text der Version 8')
  })

  it('bricht ab, wenn ein Lizenztext fehlt', () => {
    const root = mkdtempSync(join(tmpdir(), 'lizenzen-'))
    mkdirSync(join(root, 'ohne'))
    writeFileSync(join(root, 'ohne', 'package.json'), '{"version":"1.0.0","license":"MIT"}')
    expect(() => buildNotices(['/x/node_modules/ohne/index.js'], root)).toThrow(/Lizenztext fehlt/)
    expect(() => buildNotices(['\0unbekannt'], root)).toThrow(/Unbekanntes Hilfsmodul/)
  })
})
