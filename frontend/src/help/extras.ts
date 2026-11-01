// Hilfe: Hilfsfunktionen zu HelpExtras.tsx (erste Schritte, ausgegraute Anleitungen,
// „Zeig es mir“).
import type { HelpEntry } from './content.ts'
import { useHelp } from './HelpContext.tsx'

/** Erste Schritte in dieser Reihenfolge; jede Person sieht nur, was sie nutzen darf. */
export const FIRST_STEPS = [
  'guide.password',
  'guide.two_factor',
  'guide.language',
  'guide.app_pair',
  'guide.portal_change',
  'guide.member_admit',
  'guide.member_import',
  'guide.member_export',
  'guide.fee_rates',
  'guide.fee_run',
  'guide.bank_statement',
  'guide.booking',
  'guide.event_create',
  'guide.circular_send',
  'guide.role_create',
  'guide.role_preview',
] as const

/** Einträge, die die Person sehen könnte, wenn sie das Recht hätte (nur bei passender Suche). */
export function useBlocked(filter: (e: HelpEntry) => boolean): HelpEntry[] {
  const help = useHelp()
  if (!help?.entries) return []
  return help.entries.filter((e) => e.kind === 'guide' && help.missing(e).length > 0 && filter(e))
}

/** Beschriftungen, die eine Anleitung fett nennt (Knöpfe, Reiter, Felder). */
export function labelsIn(body: string): string[] {
  return [...new Set([...body.matchAll(/\*\*([^*]+)\*\*/g)].map((m) => m[1].trim()))]
}

const TARGETS = 'button, a, [role="tab"], label, legend, summary, h1, h2, h3, th'

/** „Zeig es mir“: erstes Bedienelement mit einer der Beschriftungen auf der Seite hervorheben. */
export function highlight(labels: string[], root: ParentNode = document): boolean {
  const main = root.querySelector('#inhalt') ?? root
  const norm = (s: string | null) => (s ?? '').replace(/\s+/g, ' ').trim().toLocaleLowerCase()
  const wanted = labels.map(norm)
  for (const want of wanted) {
    for (const el of main.querySelectorAll<HTMLElement>(TARGETS)) {
      if (norm(el.textContent) !== want && norm(el.getAttribute('aria-label')) !== want) continue
      if (el.closest('.help-panel')) continue
      el.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
      el.classList.add('help-highlight')
      window.setTimeout(() => el.classList.remove('help-highlight'), 4000)
      return true
    }
  }
  return false
}
