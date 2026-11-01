import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { t } from '../i18n/index.ts'

/** Fängt Fehler beim Laden oder Anzeigen einer Seite ab (z. B. nach einem Update fehlt ein
 * altes Seitenmodul), statt die ganze Oberfläche leer zu lassen (Gesamtaudit 30.10.).
 * ``resetKey`` (Pfad) setzt den Fehler beim Seitenwechsel zurück. */
export class PageErrorBoundary extends Component<
  { resetKey: string; children: ReactNode },
  { failed: boolean; key: string }
> {
  state = { failed: false, key: this.props.resetKey }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  static getDerivedStateFromProps(
    props: { resetKey: string },
    state: { failed: boolean; key: string },
  ) {
    return props.resetKey !== state.key ? { failed: false, key: props.resetKey } : null
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Seite ließ sich nicht anzeigen', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="alert alert-error" role="alert">
        <p>
          {t(
            'Diese Seite ließ sich nicht laden. Vielleicht gibt es eine neue Version von HUBIplan oder die Verbindung war kurz weg.',
          )}
        </p>
        <button type="button" className="button" onClick={() => window.location.reload()}>
          {t('Neu laden')}
        </button>
      </div>
    )
  }
}
