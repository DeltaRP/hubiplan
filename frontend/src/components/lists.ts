// Zerlegen von Listen-Eingaben wie "10, 25, 40".

/** Ganze positive Zahlen, getrennt durch Komma, Semikolon oder Leerzeichen. */
export function parseNumberList(text: string): number[] {
  return text
    .split(/[\s,;]+/)
    .map((x) => Number(x))
    .filter((x) => Number.isInteger(x) && x > 0)
}

/** Texte, getrennt durch Komma oder Semikolon (Leerzeichen gehören zum Wert). */
export function parseTextList(text: string): string[] {
  return text
    .split(/[,;]/)
    .map((x) => x.trim())
    .filter(Boolean)
}
