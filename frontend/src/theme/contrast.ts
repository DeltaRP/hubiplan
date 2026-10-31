// Kontrastberechnung nach WCAG 2.x – gleiche Formel wie im Backend.

function channel(v: number) {
  const c = v / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

export function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16)
  return (
    0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
  )
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

export const LIGHT_TEXT = '#ffffff'
export const DARK_TEXT = '#1d2421'

export function readableOn(background: string): string {
  if (!/^#[0-9a-f]{6}$/i.test(background)) return DARK_TEXT
  return contrastRatio(background, LIGHT_TEXT) >= contrastRatio(background, DARK_TEXT)
    ? LIGHT_TEXT
    : DARK_TEXT
}
