// Verständliche Hinweise statt stiller Umleitung auf die Startseite.
import { Link } from 'react-router-dom'
import { displayName } from '../api/orgs.ts'
import { useOrg } from '../org/OrgContext.tsx'
import { usePageTitle } from '../components/pageTitle.ts'
import { t } from '../i18n/index.ts'

export function NoAccessPage({ reason }: { reason: 'right' | 'workspace' }) {
  usePageTitle(t('Kein Zugriff'))
  const { active, activeDept, activePortal } = useOrg()
  const current = active
    ? displayName(active)
    : activeDept
      ? displayName(activeDept)
      : activePortal
        ? t('Meine Daten ({x})', { x: activePortal.club_display_name || activePortal.club_name })
        : null
  return (
    <section className="card">
      <h1>{t('Kein Zugriff in diesem Arbeitsbereich')}</h1>
      <p>
        {reason === 'right'
          ? t('Für diese Seite fehlt dir im aktuellen Arbeitsbereich das nötige Recht.')
          : t('Diese Seite gehört zu einem anderen Arbeitsbereich.')}
        {current && t(' Aktuell gewählt: {current}.', { current })}
      </p>
      <p className="muted">
        {t(
          'Falls du mehrere Zugänge hast, wechsle oben rechts den Arbeitsbereich. Sonst hilft dir eine Person aus dem Vorstand weiter.',
        )}
      </p>
      <div className="button-row">
        <Link to="/" className="button button-primary">
          {t('Zur Startseite')}
        </Link>
      </div>
    </section>
  )
}

export function NotFoundPage() {
  usePageTitle(t('Seite nicht gefunden'))
  return (
    <section className="card">
      <h1>{t('Seite nicht gefunden')}</h1>
      <p>{t('Diese Adresse gibt es nicht (mehr). Vielleicht ist der Link veraltet.')}</p>
      <div className="button-row">
        <Link to="/" className="button button-primary">
          {t('Zur Startseite')}
        </Link>
      </div>
    </section>
  )
}

/**
 * Unbekannter oder nicht erlaubter Unterpfad eines Bereichs (alter Link, fehlendes Recht):
 * Hinweis und Weg zurück statt leerer Seite (UX-Audit 31.10. W07).
 */
export function SubpageUnavailable({ to, label }: { to: string; label: string }) {
  return (
    <div className="card">
      <p>
        {t(
          'Diese Ansicht gibt es nicht oder sie ist in deinem Arbeitsbereich nicht verfügbar, z. B. weil das Recht dafür fehlt oder der Link veraltet ist.',
        )}
      </p>
      <div className="button-row">
        <Link to={to} className="button button-primary">
          {label}
        </Link>
      </div>
    </div>
  )
}

// Ziel des QR-Codes „App verbinden“, wenn ihn die normale Kamera statt der App öffnet.
// Der Code steht im Fragment (#) und wird hier weder angezeigt noch gesendet.
export function AppPairNoticePage() {
  usePageTitle(t('App verbinden'))
  return (
    <section className="card">
      <h1>{t('App verbinden')}</h1>
      <p>
        {t(
          'Dieser QR-Code verbindet die HUBIplan-App mit deinem Konto. Bitte öffne die App auf deinem Telefon, tippe auf „Mit QR-Code verbinden“ und scanne den Code dort.',
        )}
      </p>
      <p className="muted">
        {t(
          'Der Code gilt nur kurz und nur einmal. Falls er abgelaufen ist, erzeugst du unter „Mein Konto“ einen neuen.',
        )}
      </p>
    </section>
  )
}
