// Meldungen, wenn der Browser die Live-Kamera nicht herausgibt (Ralf 01.11.: Meldung war unklar).

const FALLBACK = ' Bis dahin geht „Foto der Scheibe“.'

// Verständliche Meldung je nach Grund, warum der Browser die Kamera nicht herausgibt.
export function cameraError(err: unknown, secure = window.isSecureContext): string {
  if (!secure) return 'Die Live-Kamera geht nur über eine sichere Verbindung (https).' + FALLBACK
  const name = err instanceof DOMException ? err.name : ''
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return (
        'Der Browser hat die Kamera nicht freigegeben. Bitte beim Schloss-Symbol neben der ' +
        'Adresse „Kamera: Zulassen“ wählen und die Live-Kamera erneut öffnen.' +
        FALLBACK
      )
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'Auf diesem Gerät wurde keine Kamera gefunden.' + FALLBACK
    case 'NotReadableError':
    case 'AbortError':
      return (
        'Die Kamera ist gerade belegt, zum Beispiel von einer anderen App oder einem anderen ' +
        'Browser-Tab. Bitte dort schließen und erneut versuchen.' +
        FALLBACK
      )
    default:
      return 'Dieser Browser kann die Kamera nicht öffnen.' + FALLBACK
  }
}
