import { describe, expect, it } from 'vitest'
import {
  isAllowedHref,
  normalizeHref,
  parseMarkdown,
  toMarkdown,
} from '../components/texteditor/markdown.ts'

function roundtrip(text: string): string | null {
  const doc = parseMarkdown(text)
  return doc ? toMarkdown(doc) : null
}

describe('Markdown des Editors', () => {
  it('übersetzt alle Knöpfe verlustfrei hin und zurück', () => {
    const text = [
      '## Überschrift',
      '',
      '### Zwischenüberschrift',
      '',
      'Ein **fetter** und *kursiver* Text mit [Link](https://example.org) und ~~alt~~.',
      '',
      '- eins',
      '- zwei',
      '',
      '1. erstens',
      '2. zweitens',
      '',
      '![Festzug 2026](bild:abcd1234)',
      '',
      '[Termine](seite:termine) und [Mail](mailto:vorstand@example.org)',
    ].join('\n')
    expect(roundtrip(text)).toBe(text)
  })

  it('schreibt Aufzählungen mit Bindestrich und macht # zur Überschrift unter dem Titel', () => {
    expect(roundtrip('* a\n* b')).toBe('- a\n- b')
    expect(roundtrip('# Titel im Text')).toBe('## Titel im Text')
  })

  it('leerer Text bleibt leer', () => {
    expect(roundtrip('')).toBe('')
  })

  it('lehnt Texte mit Tabellen ab (Bearbeitung als Markdown)', () => {
    expect(parseMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')).toBeNull()
  })

  it('behält Absätze und Zeilenumbrüche', () => {
    expect(roundtrip('Zeile eins\\\nZeile zwei\n\nNeuer Absatz')).toBe(
      'Zeile eins\\\nZeile zwei\n\nNeuer Absatz',
    )
    // weiche Zeilenumbrüche zeigt die Webseite als Leerzeichen
    expect(parseMarkdown('a\nb')).not.toBeNull()
  })

  it('maskiert Zeichen, die sonst Auszeichnung wären', () => {
    const doc = parseMarkdown('Preis 5 \\* 3')
    expect(doc).not.toBeNull()
    expect(toMarkdown(doc!)).toBe('Preis 5 \\* 3')
  })

  it('erlaubt nur sichere Linkziele', () => {
    expect(isAllowedHref('https://x.example')).toBe(true)
    expect(isAllowedHref('mailto:a@b.de')).toBe(true)
    expect(isAllowedHref('seite:kontakt')).toBe(true)
    expect(isAllowedHref('javascript:alert(1)')).toBe(false)
    expect(normalizeHref('www.schuetzen.de')).toBe('https://www.schuetzen.de')
    expect(normalizeHref('vorstand@schuetzen.de')).toBe('mailto:vorstand@schuetzen.de')
    expect(normalizeHref('javascript:alert(1)')).toBeNull()
    expect(normalizeHref('kein link')).toBeNull()
  })
})
