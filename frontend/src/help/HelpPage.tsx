// Hilfe-Seite /hilfe: eine Suche über Anleitungen, Seitenhilfen und Glossar,
// Anleitungen nach Bereichen, einzelne Anleitung unter /hilfe/<name>.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Field } from '../components/ui.tsx'
import { t } from '../i18n/index.ts'
import { DECISIONS, TERMS, decisionAnchor, termAnchor, tr } from '../learning/content.ts'
import type { DecisionKey, TermKey } from '../learning/content.ts'
import { useLearning } from '../learning/LearningContext.tsx'
import { AREAS, matchesQuery } from './content.ts'
import type { HelpEntry } from './content.ts'
import { useBlocked } from './extras.ts'
import { useHelp } from './HelpContext.tsx'
import { BlockedGuide, ForYou, GuideNotes, HelpContacts, RightsHint } from './HelpExtras.tsx'
import { HelpMarkdown } from './HelpMarkdown.tsx'

const byTitle = (a: HelpEntry, b: HelpEntry) => a.title.localeCompare(b.title)

// oxlint-disable-next-line react/only-export-components
export function areaLabel(area: string): string {
  const labels: Record<string, string> = {
    start: t('Startseite'),
    konto: t('Mein Konto'),
    mitglieder: t('Mitglieder'),
    beitraege: t('Beiträge und Rechnungen'),
    finanzen: t('Finanzen'),
    termine: t('Termine'),
    rundschreiben: t('Rundschreiben'),
    meldungen: t('Meldungen'),
    wettbewerbe: t('Wettbewerbe'),
    webseite: t('Webseite'),
    einstellungen: t('Einstellungen'),
    'mein-bereich': t('Meine Daten'),
  }
  return labels[area] ?? area
}

/** Sichtbare Einträge laden (auch ohne geöffnete Leiste). */
function useEntries() {
  const help = useHelp()
  useEffect(() => {
    if (help && !help.entries && !help.failed) help.load()
  }, [help])
  return {
    entries: help?.entries?.filter(help.visible) ?? null,
    failed: !!help?.failed,
    retry: () => help?.load(),
  }
}

function LoadState({ failed, retry }: { failed: boolean; retry: () => void }) {
  return failed ? (
    <p role="alert">
      {t('Die Hilfe konnte nicht geladen werden.')}{' '}
      <button type="button" className="link-button" onClick={retry}>
        {t('Erneut versuchen')}
      </button>
    </p>
  ) : (
    <p className="muted" role="status">
      {t('Lädt …')}
    </p>
  )
}

export function HelpPage() {
  const { entries, failed, retry } = useEntries()
  const learning = useLearning()
  const hasFeature = learning?.hasFeature
  const has = useCallback(
    (f: Parameters<NonNullable<typeof hasFeature>>[0]) => (hasFeature ? hasFeature(f) : true),
    [hasFeature],
  )
  const [query, setQuery] = useState('')
  const searching = query.trim().length > 0

  const found = useMemo(
    () =>
      (entries ?? [])
        .filter((e) => matchesQuery(query, e.title, e.body, e.keywords.join(' ')))
        .sort(byTitle),
    [entries, query],
  )
  const terms = useMemo(
    () =>
      searching
        ? (Object.keys(TERMS) as TermKey[]).filter(
            (k) =>
              has(TERMS[k].feature) && matchesQuery(query, tr(TERMS[k].name), tr(TERMS[k].meaning)),
          )
        : [],
    [query, searching, has],
  )
  const decisions = useMemo(
    () =>
      searching
        ? (Object.keys(DECISIONS) as DecisionKey[]).filter(
            (k) =>
              has(DECISIONS[k].feature) &&
              matchesQuery(query, tr(DECISIONS[k].title), tr(DECISIONS[k].text)),
          )
        : [],
    [query, searching, has],
  )

  // Anleitungen, für die ein Recht fehlt: nur bei passender Suche, ausgegraut (F1)
  const blocked = useBlocked(
    (e) => searching && matchesQuery(query, e.title, e.body, e.keywords.join(' ')),
  ).sort(byTitle)
  const guides = (entries ?? []).filter((e) => e.kind === 'guide' && e.key !== 'guide.whats_new')
  const news = (entries ?? []).find((e) => e.key === 'guide.whats_new')
  const areas = AREAS.map((a) => ({
    area: a,
    items: guides.filter((g) => g.area === a).sort(byTitle),
  })).filter((a) => a.items.length > 0)

  return (
    <section className="help-page">
      <h1>{t('Hilfe')}</h1>
      <p className="muted">
        {t(
          'Anleitungen Schritt für Schritt, Erklärungen zu jeder Seite und das Glossar. Auf jeder Seite öffnet „Hilfe zu dieser Seite“ oben (oder die Taste ?) die passende Hilfe.',
        )}
      </p>
      <div className="help-search">
        <Field
          label={t('Hilfe durchsuchen')}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {!entries && <LoadState failed={failed} retry={retry} />}
      {entries && searching && (
        <div className="help-results">
          {found.length + terms.length + decisions.length + blocked.length === 0 && (
            <p role="status">{t('Nichts gefunden.')}</p>
          )}
          {found.length > 0 && (
            <section>
              <h2>{t('Anleitungen und Seiten')}</h2>
              <ul className="help-list">
                {found.map((e) => (
                  <li key={e.key}>
                    <Link to={`/hilfe/${e.slug}`}>{e.title}</Link>{' '}
                    <span className="muted small">
                      ({e.kind === 'page' ? t('Seite') : areaLabel(e.area)})
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {blocked.length > 0 && (
            <section>
              <h2>{t('Dafür fehlt dir ein Recht')}</h2>
              <ul className="help-list">
                {blocked.map((e) => (
                  <BlockedGuide key={e.key} entry={e} />
                ))}
              </ul>
            </section>
          )}
          {terms.length + decisions.length > 0 && (
            <section>
              <h2>{t('Im Glossar')}</h2>
              <ul className="help-list">
                {terms.map((k) => (
                  <li key={k}>
                    <Link to={`/glossar#${termAnchor(k)}`}>{tr(TERMS[k].name)}</Link>
                  </li>
                ))}
                {decisions.map((k) => (
                  <li key={k}>
                    <Link to={`/glossar#${decisionAnchor(k)}`}>{tr(DECISIONS[k].title)}</Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
      {entries && !searching && (
        <>
          {news && (
            <p>
              <Link to={`/hilfe/${news.slug}`}>{news.title}</Link>
            </p>
          )}
          <ForYou
            areaLabel={areaLabel}
            linkTo={(e) => <Link to={`/hilfe/${e.slug}`}>{e.title}</Link>}
          />
          <HelpContacts />
          {areas.map((a) => (
            <section key={a.area} className="help-area">
              <h2>{areaLabel(a.area)}</h2>
              <ul className="help-list">
                {a.items.map((g) => (
                  <li key={g.key}>
                    <Link to={`/hilfe/${g.slug}`}>{g.title}</Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          <section className="help-area">
            <h2>{t('Glossar')}</h2>
            <p>
              {t(
                'Fachbegriffe und Entscheidungen der Vereinsverwaltung, kurz erklärt und mit Quellen.',
              )}{' '}
              <Link to="/glossar">{t('Zum Glossar')}</Link>
            </p>
          </section>
        </>
      )}
    </section>
  )
}

/** Eine Anleitung oder Seitenhilfe unter /hilfe/<name> */
export function HelpEntryPage() {
  const { '*': slug = '' } = useParams()
  const { entries, failed, retry } = useEntries()
  const help = useHelp()
  const navigate = useNavigate()
  const entry = entries?.find((e) => e.slug === slug)
  // Nicht sichtbar, weil ein Recht fehlt? Dann sagen, welches (F1)
  const hidden = !entry ? help?.entries?.find((e) => e.slug === slug) : undefined
  const missing = hidden ? (help?.missing(hidden) ?? []) : []
  const target = entry?.routes.find((r) => !r.includes(':') && r !== '/hilfe')
  const related =
    entry?.kind === 'page'
      ? (entries ?? []).filter(
          (e) => e.kind === 'guide' && e.routes.some((r) => entry.routes.includes(r)),
        )
      : []
  return (
    <section className="help-page">
      <p>
        <Link to="/hilfe">← {t('Alle Hilfe')}</Link>
      </p>
      {!entries && <LoadState failed={failed} retry={retry} />}
      {entries && !entry && hidden && missing.length > 0 && (
        <>
          <h1>{hidden.title}</h1>
          <p role="status">
            <RightsHint rights={missing} />
          </p>
        </>
      )}
      {entries && !entry && !(hidden && missing.length > 0) && (
        <>
          <h1>{t('Hilfe')}</h1>
          <p role="status">
            {t('Diese Hilfe gibt es nicht, oder sie gehört zu einer Funktion, die du nicht nutzt.')}
          </p>
        </>
      )}
      {entry && (
        <article>
          <h1>{entry.title}</h1>
          <HelpMarkdown body={entry.body} />
          <GuideNotes entry={entry} editable />
          {target && (
            <p className="help-actions">
              <Link to={target}>{t('Zur Seite in HUBIplan')}</Link>
              {entry.kind === 'guide' && help && (
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => {
                    navigate(target)
                    help.openGuide({ key: entry.key, path: target })
                  }}
                >
                  {t('Zeig es mir')}
                </button>
              )}
            </p>
          )}
          {related.length > 0 && (
            <section>
              <h2>{t('Häufige Aufgaben')}</h2>
              <ul className="help-list">
                {related.map((g) => (
                  <li key={g.key}>
                    <Link to={`/hilfe/${g.slug}`}>{g.title}</Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>
      )}
    </section>
  )
}
