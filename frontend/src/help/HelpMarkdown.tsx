// Text einer Hilfedatei anzeigen. Nur eigene Texte aus dem Repo, trotzdem ohne rohes HTML.
// Interne Links (/mitglieder) wechseln die Seite ohne Neuladen; Bilder kommen aus
// /hilfe-bilder/<sprache>/ (scripts/hilfe-bilder.sh).
import { useMemo } from 'react'
import type { MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { fillTerms, useTerms } from '../org/terms.ts'
import { renderHelp } from './markdown.ts'

export function HelpMarkdown({ body, onNavigate }: { body: string; onNavigate?: () => void }) {
  const terms = useTerms()
  const navigate = useNavigate()
  const html = useMemo(() => renderHelp(fillTerms(body, terms)), [body, terms])
  const click = (e: MouseEvent<HTMLDivElement>) => {
    const a = (e.target as HTMLElement).closest('a')
    const href = a?.getAttribute('href')
    if (!a || !href?.startsWith('/') || e.metaKey || e.ctrlKey || e.shiftKey) return
    e.preventDefault()
    navigate(href)
    onNavigate?.()
  }
  return (
    // Klicks auf Links im Text; die Links selbst sind per Tastatur erreichbar
    // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div className="help-text" onClick={click} dangerouslySetInnerHTML={{ __html: html }} />
  )
}
