// Einfache Auszeichnung der Rundschreiben (wie circulars/text.py im Backend):
// **fett**, *kursiv*, [Text](https://…), Zeilen mit „- “ bzw. „1. “ als Listen.
// Die Vorschau baut React-Elemente, nie rohes HTML.
import type { ReactNode } from 'react'

export type Block = { kind: 'p' | 'ul' | 'ol'; lines: string[] }

const BULLET = /^\s*[-•]\s+(.*)$/
const NUMBER = /^\s*\d+[.)]\s+(.*)$/
const TOKEN = /\[([^\]\n]+)\]\(((?:https?:\/\/|mailto:)[^)\s]+)\)|\*\*(.+?)\*\*|\*(?!\s)(.+?)\*/g

export function blocks(text: string): Block[] {
  const result: Block[] = []
  let current: Block | null = null
  for (const raw of text.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      current = null
      continue
    }
    const bullet = BULLET.exec(line)
    const number = NUMBER.exec(line)
    const kind = bullet ? 'ul' : number ? 'ol' : 'p'
    const content = (bullet ?? number)?.[1] ?? line
    if (!current || current.kind !== kind) {
      current = { kind, lines: [] }
      result.push(current)
    }
    current.lines.push(content)
  }
  return result
}

export function inline(text: string, keyBase = ''): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const key = `${keyBase}-${n++}`
    if (m[1] !== undefined)
      out.push(
        <a key={key} href={m[2]} target="_blank" rel="noreferrer">
          {m[1]}
        </a>,
      )
    else if (m[3] !== undefined) out.push(<strong key={key}>{inline(m[3], key)}</strong>)
    else out.push(<em key={key}>{inline(m[4] ?? '', key)}</em>)
    last = at + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function renderMarkup(text: string): ReactNode {
  return blocks(text).map((b, i) => {
    if (b.kind === 'p')
      return (
        <p key={i}>
          {b.lines.map((line, j) => (
            <span key={j}>
              {j > 0 && <br />}
              {inline(line, `${i}-${j}`)}
            </span>
          ))}
        </p>
      )
    const items = b.lines.map((line, j) => <li key={j}>{inline(line, `${i}-${j}`)}</li>)
    return b.kind === 'ul' ? <ul key={i}>{items}</ul> : <ol key={i}>{items}</ol>
  })
}
