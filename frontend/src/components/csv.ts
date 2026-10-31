// CSV-Dateien im Browser erzeugen.

/** Lädt eine CSV-Datei (Semikolon, mit BOM für Excel) im Browser herunter. */
export function downloadCsv(fileName: string, rows: (string | number)[][]) {
  const text = rows
    .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(';'))
    .join('\r\n')
  const blob = new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
