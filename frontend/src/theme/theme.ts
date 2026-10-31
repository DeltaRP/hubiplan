// Laufzeit-Theme der aktiven Organisation. Das Backend liefert das bereits
// vererbte Erscheinungsbild (Abteilung ← Verein ← Dachverband ← Plattform) und
// die lesbare Schriftfarbe auf Primär- und Akzentfarbe.

export interface ThemeColors {
  primary: string
  on_primary: string
  accent: string
  on_accent: string
}

import { contrastRatio, readableOn } from './contrast.ts'

const VARS = [
  '--color-primary',
  '--color-primary-hover',
  '--color-link',
  '--color-focus',
  '--color-on-primary',
  '--color-accent',
  '--color-on-accent',
  '--sidebar-bg',
  '--sidebar-focus',
] as const

/** Seitenhintergrund (--color-bg in theme.css): Links stehen auf Weiß und auf ihm. */
export const PAGE_BG = '#f5f6f4'

/** Farbe mit Schwarz mischen (0 = unverändert, 1 = schwarz). */
export function darken(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16)
  const ch = (shift: number) => Math.round(((n >> shift) & 255) * (1 - amount))
  return `#${[16, 8, 0].map((s) => ch(s).toString(16).padStart(2, '0')).join('')}`
}

/** Farbe mit Weiß mischen (0 = unverändert, 1 = weiß). */
export function lighten(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16)
  const ch = (shift: number) => {
    const c = (n >> shift) & 255
    return Math.round(c + (255 - c) * amount)
  }
  return `#${[16, 8, 0].map((s) => ch(s).toString(16).padStart(2, '0')).join('')}`
}

/**
 * Linkfarbe aus der Primärfarbe: so wenig wie nötig abgedunkelt, bis normaler
 * Text auf Weiß und auf dem Seitenhintergrund 4,5 : 1 erreicht (WCAG 1.4.3,
 * UI-Audit NUI-04). Die Markenfarbe selbst bleibt.
 */
export function linkColor(primary: string): string {
  for (let step = 0; step <= 20; step++) {
    const c = darken(primary, step * 0.05)
    if (Math.min(contrastRatio(c, '#ffffff'), contrastRatio(c, PAGE_BG)) >= 4.5) return c
  }
  return '#000000'
}

/** Seitenleiste aus der Primärfarbe (stark abgedunkelt). */
export function sidebarColor(primary: string): string {
  return darken(primary, 0.55)
}

/**
 * Hoverfarbe für gefüllte Schaltflächen: in die Richtung, in der die Schrift
 * besser lesbar bleibt (helle Schrift → dunkler, dunkle Schrift → heller).
 */
export function hoverColor(primary: string, onPrimary: string): string {
  const darker = darken(primary, 0.15)
  const lighter = lighten(primary, 0.15)
  return contrastRatio(darker, onPrimary) >= contrastRatio(lighter, onPrimary) ? darker : lighter
}

export function applyTheme(
  theme: ThemeColors | null,
  root: HTMLElement = document.documentElement,
) {
  if (!theme) {
    for (const v of VARS) root.style.removeProperty(v)
    return
  }
  root.style.setProperty('--color-primary', theme.primary)
  root.style.setProperty('--color-primary-hover', hoverColor(theme.primary, theme.on_primary))
  root.style.setProperty('--color-link', linkColor(theme.primary))
  // Fokusrahmen, Feldfokus und Häkchen: dieselbe abgedunkelte Farbe, damit sie auch bei
  // hellen Vereinsfarben (Gold, Gelb, Hellblau) deutlich zu sehen sind (WCAG 1.4.11)
  root.style.setProperty('--color-focus', linkColor(theme.primary))
  root.style.setProperty('--color-on-primary', theme.on_primary)
  root.style.setProperty('--color-accent', theme.accent)
  root.style.setProperty('--color-on-accent', theme.on_accent)
  const sidebar = sidebarColor(theme.primary)
  root.style.setProperty('--sidebar-bg', sidebar)
  // Fokusrahmen in der Seitenleiste: Weiß oder Schwarz, je nachdem was dort absticht
  root.style.setProperty('--sidebar-focus', readableOn(sidebar))
}
