// Tabellenrollen ausdrücklich setzen (UI-Audit Barrierefreiheit H-05).
// Auf dem Handy werden Tabellen per CSS zu Blöcken (index.css, „.table tr { display: block }“).
// Safari/VoiceOver und teils Chrome geben dabei die Tabellenrollen auf; dann hört man nur
// Werte ohne Spaltenbezug. Mit ausdrücklichen ARIA-Rollen bleibt die Struktur erhalten.

const SELECTOR = 'table.table, table.aid-example'

/**
 * Spaltennamen an die Zellen schreiben, wo die Seite keine eigenen gesetzt hat: auf dem
 * Handy steht der Name vor jedem Wert (index.css), sonst fehlt dort jede Spaltenbedeutung
 * (UX-Audit 31.10. C03). Eigene data-label (auch leere) bleiben unverändert.
 */
function addColumnLabels(table: HTMLTableElement) {
  const head = table.tHead?.rows[0]
  if (!head) return
  // Mit zusammengefassten Zeilen stimmt die Spaltenzählung nicht: dann nichts raten
  if (table.querySelector('td[rowspan]:not([rowspan="1"]), th[rowspan]:not([rowspan="1"])')) return
  const names: string[] = []
  for (const th of Array.from(head.cells)) {
    const text = (th.getAttribute('aria-label') ?? th.textContent ?? '').trim()
    for (let i = 0; i < (th.colSpan || 1); i++) names.push(text)
  }
  for (const body of Array.from(table.tBodies)) {
    for (const row of Array.from(body.rows)) {
      let col = 0
      for (const cell of Array.from(row.cells)) {
        const name = names[col] ?? ''
        col += cell.colSpan || 1
        if (cell.tagName !== 'TD') continue
        const auto = cell.hasAttribute('data-label-auto')
        if (cell.hasAttribute('data-label') && !auto) continue
        if (cell.getAttribute('data-label') !== name) cell.setAttribute('data-label', name)
        if (!auto) cell.setAttribute('data-label-auto', '')
      }
    }
  }
}

export function addTableRoles(table: HTMLTableElement) {
  if (table.classList.contains('table') && !table.classList.contains('table-keep'))
    addColumnLabels(table)
  const set = (el: Element, role: string) => {
    if (el.getAttribute('role') !== role) el.setAttribute('role', role)
  }
  set(table, 'table')
  for (const group of Array.from(
    table.querySelectorAll(':scope > thead, :scope > tbody, :scope > tfoot'),
  ))
    set(group, 'rowgroup')
  for (const row of Array.from(table.rows)) {
    set(row, 'row')
    for (const cell of Array.from(row.cells)) {
      if (cell.tagName === 'TH') {
        const inHead = cell.parentElement?.parentElement?.tagName === 'THEAD'
        set(cell, inHead || cell.getAttribute('scope') === 'col' ? 'columnheader' : 'rowheader')
      } else {
        set(cell, 'cell')
      }
    }
  }
}

/** Beobachtet die Seite und versieht neue oder geänderte Tabellen mit Rollen. */
export function watchTableSemantics(root: HTMLElement = document.body) {
  let pending = false
  const run = () => {
    pending = false
    root.querySelectorAll<HTMLTableElement>(SELECTOR).forEach(addTableRoles)
  }
  const observer = new MutationObserver(() => {
    if (pending) return
    pending = true
    requestAnimationFrame(run)
  })
  observer.observe(root, { childList: true, subtree: true })
  run()
  return () => observer.disconnect()
}
