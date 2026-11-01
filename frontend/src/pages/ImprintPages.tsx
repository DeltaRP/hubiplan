import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client.ts'
import { imprintApi, imprintPath, privacyPath } from '../api/imprint.ts'
import type { ImprintDetails, PublicImprint } from '../api/imprint.ts'
import { Logo } from '../components/Logo.tsx'
import { Alert } from '../components/ui.tsx'
import { usePublicImprint } from '../components/publicImprint.ts'
import { t } from '../i18n/index.ts'

function usePublicImprintData(key?: string) {
  const [result, setResult] = useState<{
    key?: string
    data: PublicImprint | null
    error: string | null
  }>({ data: null, error: null })
  useEffect(() => {
    let alive = true
    imprintApi
      .public(key)
      .then((data) => alive && setResult({ key, data, error: null }))
      .catch((err) => {
        if (!alive) return
        setResult({
          key,
          data: null,
          error:
            err instanceof ApiError && err.status === 404
              ? t('Diese Seite gibt es nicht.')
              : t('Die Seite kann gerade nicht geladen werden. Bitte später erneut versuchen.'),
        })
      })
    return () => {
      alive = false
    }
  }, [key])
  // Beim Wechsel der Seite gilt das alte Ergebnis nicht mehr
  return result.key === key ? result : { data: null, error: null }
}

/** Mehrzeiliger Freitext, Zeilenumbrüche bleiben erhalten. */
function Text({ value }: { value: string }) {
  return <p className="imprint-text">{value}</p>
}

export function ImprintDetailsView({ d }: { d: ImprintDetails }) {
  const address = d.address
  return (
    <div className="imprint">
      <h2>{t('Angaben gemäß § 5 DDG')}</h2>
      <p>
        <strong>{d.name}</strong>
        {d.legal_form && (
          <>
            <br />
            {d.legal_form}
          </>
        )}
        {address.street && (
          <>
            <br />
            {address.street}
          </>
        )}
        {(address.postal_code || address.city) && (
          <>
            <br />
            {address.postal_code} {address.city}
          </>
        )}
        {address.country && address.country !== 'Deutschland' && (
          <>
            <br />
            {address.country}
          </>
        )}
      </p>
      {(d.representatives_text || d.representatives.length > 0) && (
        <>
          <h3>{t('Vertreten durch')}</h3>
          {d.representatives_text ? (
            <Text value={d.representatives_text} />
          ) : (
            <ul className="plain-list">
              {d.representatives.map((r) => (
                <li key={`${r.role}-${r.name}`}>
                  {r.name} ({r.role})
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {(d.email || d.phone || d.website) && (
        <>
          <h3>{t('Kontakt')}</h3>
          <p>
            {d.phone && (
              <>
                {t('Telefon:')} {d.phone}
              </>
            )}
            {d.phone && d.email && <br />}
            {d.email && (
              <>
                {t('E-Mail:')} <a href={`mailto:${d.email}`}>{d.email}</a>
              </>
            )}
            {d.website && (
              <>
                <br />
                {t('Website:')}{' '}
                <a href={d.website} rel="noopener noreferrer">
                  {d.website}
                </a>
              </>
            )}
          </p>
        </>
      )}
      {(d.register_court || d.register_number) && (
        <>
          <h3>{t('Registereintrag')}</h3>
          <p>
            {d.register_court && (
              <>
                {t('Registergericht:')} {d.register_court}
              </>
            )}
            {d.register_court && d.register_number && <br />}
            {d.register_number && (
              <>
                {t('Registernummer:')} {d.register_number}
              </>
            )}
          </p>
        </>
      )}
      {d.vat_id && (
        <>
          <h3>{t('Umsatzsteuer-ID')}</h3>
          <p>
            {t('Umsatzsteuer-Identifikationsnummer nach § 27a UStG:')} {d.vat_id}
          </p>
        </>
      )}
      {d.responsible && (
        <>
          <h3>{t('Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV')}</h3>
          <Text value={d.responsible} />
        </>
      )}
      {d.data_protection_officer && (
        <>
          <h3>{t('Datenschutzbeauftragte(r)')}</h3>
          <Text value={d.data_protection_officer} />
        </>
      )}
      {d.extra_text && <Text value={d.extra_text} />}
    </div>
  )
}

function PublicCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="login-page">
      <div className="card public-photo public-imprint">
        <div className="login-logo">
          <Logo />
        </div>
        <h1>{title}</h1>
        {children}
      </div>
    </main>
  )
}

/** Lädt die Einheit (falls ein Schlüssel da ist) und immer die Plattform. */
function useCombinedImprint(key?: string) {
  const unit = usePublicImprintData(key)
  const platform = usePublicImprintData(undefined)
  usePublicImprint(key && unit.data ? key : null, unit.data?.unit)
  // Ein Schlüssel, der direkt zur Plattform gehört, zeigt die Plattform nicht doppelt
  const own = key && !(unit.data?.is_platform && !unit.data.inherited)
  return { unit: own ? unit : null, platform }
}

/** Abschnitt mit Überschrift, Ladehinweis und Fehlermeldung. */
function Section({
  title,
  state,
  children,
}: {
  title: string
  state: { data: PublicImprint | null; error: string | null }
  children: (data: PublicImprint) => ReactNode
}) {
  return (
    <section className="imprint-section">
      <h2>{title}</h2>
      {state.error && <Alert kind="error">{state.error}</Alert>}
      {!state.data && !state.error && <p className="muted">{t('Lädt …')}</p>}
      {state.data && children(state.data)}
    </section>
  )
}

function ImprintBody({ data }: { data: PublicImprint }) {
  if (data.inherited && data.is_platform)
    return (
      <p className="muted">
        {t(
          'Für {unit} ist noch kein eigenes Impressum hinterlegt. Es gelten die Angaben des Betreibers dieser Plattform (unten).',
          { unit: data.unit },
        )}
      </p>
    )
  return (
    <>
      {data.inherited && (
        <p className="muted">
          {t('Für {unit} gilt das Impressum von {owner}.', { unit: data.unit, owner: data.owner })}
        </p>
      )}
      {data.mode === 'link' ? (
        <p>
          {t('Das Impressum von {owner} steht auf der eigenen Website:', { owner: data.owner })}{' '}
          <a href={data.external_url} rel="noopener noreferrer">
            {data.external_url}
          </a>
        </p>
      ) : data.details ? (
        <ImprintDetailsView d={data.details} />
      ) : null}
    </>
  )
}

function PrivacyBody({ data }: { data: PublicImprint }) {
  if (data.privacy.mode === 'link' && data.privacy.url)
    return (
      <p>
        {t('Die Datenschutzhinweise stehen auf der eigenen Website:')}{' '}
        <a href={data.privacy.url} rel="noopener noreferrer">
          {data.privacy.url}
        </a>
      </p>
    )
  return data.privacy.text.trim() ? (
    <Text value={data.privacy.text} />
  ) : (
    <p>{t('Es sind noch keine Datenschutzhinweise hinterlegt.')}</p>
  )
}

const PLATFORM_TITLE = t('Betreiber der Plattform HUBIplan')

/**
 * /impressum und /impressum/:key: eine Seite für alles. Mit Schlüssel steht zuerst die
 * Einheit (Verein), darunter der Betreiber der Plattform.
 */
export function ImprintPage() {
  const key = useParams().key
  const { unit, platform } = useCombinedImprint(key)
  return (
    <PublicCard title={t('Impressum')}>
      {unit && (
        <Section title={unit.data?.owner ?? t('Verein')} state={unit}>
          {(data) => <ImprintBody data={data} />}
        </Section>
      )}
      <Section title={PLATFORM_TITLE} state={platform}>
        {(data) => (
          <>
            <ImprintBody data={data} />
            <p className="muted small">
              {t(
                'Über diese Plattform verwalten Vereine und andere Einheiten ihre Mitglieder. Für ihre Inhalte (Rundschreiben, Termine, Dokumente) ist die jeweilige Einheit verantwortlich.',
              )}
            </p>
          </>
        )}
      </Section>
      <p className="small">
        <Link to={privacyPath(key)}>{t('Datenschutz')}</Link>
      </p>
    </PublicCard>
  )
}

/**
 * /datenschutz und /datenschutz/:key: zuerst die Datenschutzhinweise der Einheit (sie ist für
 * die Mitgliederdaten verantwortlich), darunter die Datenschutzerklärung der Plattform.
 */
export function PrivacyPage() {
  const key = useParams().key
  const { unit, platform } = useCombinedImprint(key)
  return (
    <PublicCard title={t('Datenschutz')}>
      {unit && (
        <Section
          title={t('Datenschutzhinweise {x}', { x: unit.data?.owner ?? 'des Vereins' })}
          state={unit}
        >
          {(data) => <PrivacyBody data={data} />}
        </Section>
      )}
      <Section
        title={t('Datenschutzerklärung: {PLATFORM_TITLE}', { PLATFORM_TITLE })}
        state={platform}
      >
        {(data) => <PrivacyBody data={data} />}
      </Section>
      <p className="small">
        <Link to={imprintPath(key)}>{t('Impressum')}</Link>
      </p>
    </PublicCard>
  )
}

/** Statische Dateien, die der Webserver neben der App ausliefert (deploy/web.Dockerfile). */
const LICENSE_FILES = {
  license: '/lizenzen/LICENSE.txt',
  thirdParty: '/lizenzen/drittanbieter.txt',
}

/** Öffentliches Repository mit dem Quellcode (AGPL § 13). Wer HUBIplan verändert betreibt, trägt hier sein eigenes ein. */
const SOURCE_REPO = 'https://github.com/hubiplan/hubiplan'

/** Commit der laufenden Fassung; deploy/server-setup.sh legt ihn beim Ausrollen ab. */
const VERSION_FILE = '/lizenzen/fassung.txt'

/** Liest den Commit der laufenden Fassung; ohne Datei (z. B. Entwicklung) null. */
function useRunningCommit(): string | null {
  const [commit, setCommit] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    fetch(VERSION_FILE)
      .then((resp) => (resp.ok ? resp.text() : ''))
      .then((text) => {
        const sha = (text ?? '').trim()
        if (active && /^[0-9a-f]{40}$/.test(sha)) setCommit(sha)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])
  return commit
}

/** /lizenz: Lizenz von HUBIplan, Quellcode und Lizenzen der enthaltenen Bibliotheken. */
export function LicensePage() {
  const commit = useRunningCommit()
  return (
    <PublicCard title={t('Lizenzen')}>
      <p>
        {t(
          'HUBIplan ist freie Software unter der GNU Affero General Public License, Version 3 oder später (AGPL-3.0-or-later). Ihr dürft HUBIplan nutzen, verändern und weitergeben. Wer eine veränderte Fassung weitergibt oder als Online-Dienst betreibt, muss den Quellcode dieser Fassung unter derselben Lizenz zugänglich machen.',
        )}
      </p>
      <p>
        {t(
          'HUBIplan wird ohne Gewährleistung bereitgestellt, soweit das Gesetz es zulässt. Einzelheiten stehen in den Abschnitten 15 und 16 der Lizenz.',
        )}
      </p>
      <p>
        {t('Den Quellcode bekommt ihr kostenlos auf GitHub:')}{' '}
        {commit ? (
          <a href={`${SOURCE_REPO}/tree/${commit}`}>
            {t('Quellcode dieser Fassung ({x})', { x: commit.slice(0, 7) })}
          </a>
        ) : (
          <a href={SOURCE_REPO}>{t('Quellcode von HUBIplan')}</a>
        )}
        .
      </p>
      <ul>
        <li>
          <a href={LICENSE_FILES.license}>{t('Lizenztext (englisch)')}</a>
        </li>
        <li>
          <a href={LICENSE_FILES.thirdParty}>{t('Lizenzen der enthaltenen Bibliotheken')}</a>
        </li>
      </ul>
    </PublicCard>
  )
}

/**
 * Freiwillige Erklärung zur Barrierefreiheit (Barrierefreiheit X-02). Vereine sind keine
 * öffentlichen Stellen; die Seite nennt trotzdem Stand, bekannte Grenzen und Kontakt.
 */
export function AccessibilityPage() {
  return (
    <PublicCard title={t('Barrierefreiheit')}>
      <p>
        {t(
          'HUBIplan soll für alle Mitglieder und Vorstände bedienbar sein, auch mit Tastatur, Screenreader, Vergrößerung oder großer Schrift. Maßstab sind die Richtlinien WCAG 2.2, Stufe AA.',
        )}
      </p>
      <h2>{t('Stand')}</h2>
      <p>
        {t(
          'Weitgehend erfüllt (Prüfung im Oktober 2026). Dazu gehören Tastaturbedienung, sichtbarer Fokus, beschriftete Felder, Fehlermeldungen am Feld, ausreichende Kontraste auch bei hellen Vereinsfarben sowie Diagramme mit Wertetabelle.',
        )}
      </p>
      <h2>{t('Bekannte Einschränkungen')}</h2>
      <ul>
        <li>
          {t(
            'PDF-Dokumente (Rechnungen, Bestätigungen, Ausweise) sind noch nicht für Screenreader aufbereitet. Die wichtigen Angaben stehen auch als Text in der E-Mail oder im Mitgliederbereich.',
          )}
        </li>
        <li>
          {t(
            'Die Unterschrift auf Quittungen wird gezeichnet. Wer nicht unterschreiben kann, wird mit Grund „ohne Unterschrift“ vermerkt.',
          )}
        </li>
        <li>
          {t('Beschreibungen von Bildern (Alternativtexte) pflegt der jeweilige Verein selbst.')}
        </li>
      </ul>
      <h2>{t('Barriere melden')}</h2>
      <p>
        {t(
          'Wenn Ihnen etwas den Zugang erschwert, schreiben Sie bitte dem Vorstand Ihres Vereins oder dem Betreiber dieser Instanz. Die Kontaktdaten stehen im',
        )}{' '}
        <Link to="/impressum">{t('Impressum')}</Link>.
      </p>
    </PublicCard>
  )
}
