// Glossar der Begriffe und Entscheidungen. Für alle angemeldeten Bearbeitenden;
// Einträge zu nicht freigeschalteten Funktionen fehlen.
import { useEffect, useMemo, useState } from 'react'
import {
  DECISIONS,
  PHASES,
  SECTIONS,
  SOURCES,
  TERMS,
  decisionAnchor,
  termAnchor,
  tr,
  type DecisionKey,
  type PhaseKey,
  type SectionKey,
  type SourceKey,
  type TermKey,
} from './content.ts'
import { Field } from '../components/ui.tsx'
import { useLearning } from './LearningContext.tsx'
import { t } from '../i18n/index.ts'

const byName = (a: string, b: string) => a.localeCompare(b, 'de', { sensitivity: 'base' })

/** Alle Wörter der Suche müssen vorkommen (Groß-/Kleinschreibung egal). */
function matches(query: string, ...texts: (string | undefined)[]): boolean {
  const words = query.toLocaleLowerCase('de').split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const hay = texts.filter(Boolean).join(' ').toLocaleLowerCase('de')
  return words.every((w) => hay.includes(w))
}

const ALL = () => true

export function GlossaryPage() {
  const learning = useLearning()
  const [query, setQuery] = useState('')
  const has = learning?.hasFeature ?? ALL

  const terms = useMemo(
    () =>
      (Object.keys(TERMS) as TermKey[])
        .filter((k) => has(TERMS[k].feature))
        .filter((k) => {
          const tm = TERMS[k]
          return matches(
            query,
            'symbol' in tm ? tm.symbol : undefined,
            tr(tm.name),
            tr(tm.meaning),
            tr(tm.example),
          )
        }),
    [query, has],
  )
  const decisions = useMemo(
    () =>
      (Object.keys(DECISIONS) as DecisionKey[])
        .filter((k) => has(DECISIONS[k].feature))
        .filter((k) => {
          const e = DECISIONS[k]
          return matches(query, tr(e.title), tr(e.text), tr(e.place))
        }),
    [query, has],
  )

  // Sprung zum Anker, sobald die Seite steht (Link „im Glossar ↗“)
  useEffect(() => {
    const id = window.location.hash.slice(1)
    if (id) document.getElementById(id)?.scrollIntoView?.()
  }, [])

  const usedSources = new Set<SourceKey>()
  for (const k of Object.keys(TERMS) as TermKey[])
    if (has(TERMS[k].feature)) TERMS[k].sources.forEach((s) => usedSources.add(s))
  for (const k of Object.keys(DECISIONS) as DecisionKey[])
    if (has(DECISIONS[k].feature)) DECISIONS[k].sources.forEach((s) => usedSources.add(s))

  const sections = (Object.keys(SECTIONS) as SectionKey[])
    .map((s) => ({
      key: s,
      items: terms
        .filter((k) => TERMS[k].section === s)
        .sort((a, b) => byName(tr(TERMS[a].name), tr(TERMS[b].name))),
    }))
    .filter((s) => s.items.length > 0)
  const phases = (Object.keys(PHASES) as PhaseKey[])
    .map((p) => ({
      key: p,
      items: decisions
        .filter((k) => DECISIONS[k].phase === p)
        .sort((a, b) => byName(tr(DECISIONS[a].title), tr(DECISIONS[b].title))),
    }))
    .filter((p) => p.items.length > 0)
  const nothing = sections.length === 0 && phases.length === 0

  return (
    <section className="glossary">
      <h1>{t('Glossar')}</h1>
      <p className="muted">
        {t('Begriffe und Entscheidungen der Vereinsverwaltung, kurz erklärt und mit Quellen.')}
      </p>
      <div className="glossary-search">
        <Field
          label={t('Glossar durchsuchen')}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {nothing && <p role="status">{t('Nichts gefunden.')}</p>}
      {sections.map((s) => (
        <section key={s.key} className="glossary-section">
          <h2>{tr(SECTIONS[s.key])}</h2>
          <dl className="glossary-list">
            {s.items.map((k) => {
              const tm = TERMS[k]
              return (
                <div key={k} id={termAnchor(k)} className="glossary-entry">
                  <dt>
                    {'symbol' in tm && tm.symbol ? (
                      <>
                        <strong>{tm.symbol}</strong> · {tr(tm.name)}
                      </>
                    ) : (
                      <strong>{tr(tm.name)}</strong>
                    )}
                  </dt>
                  <dd>
                    {tr(tm.meaning)}
                    <span className="glossary-example muted">{tr(tm.example)}</span>
                  </dd>
                </div>
              )
            })}
          </dl>
        </section>
      ))}
      {phases.length > 0 && (
        <section className="glossary-section">
          <h2>{t('Entscheidungen')}</h2>
          {phases.map((p) => (
            <section key={p.key} className="glossary-phase">
              <h3>{tr(PHASES[p.key])}</h3>
              <dl className="glossary-list">
                {p.items.map((k) => {
                  const e = DECISIONS[k]
                  return (
                    <div key={k} id={decisionAnchor(k)} className="glossary-entry">
                      <dt>
                        <strong>{tr(e.title)}</strong>{' '}
                        <span className="muted small">({tr(e.place)})</span>
                      </dt>
                      <dd>{tr(e.text)}</dd>
                    </div>
                  )
                })}
              </dl>
            </section>
          ))}
        </section>
      )}
      <section className="glossary-section">
        <h2>{t('Quellen')}</h2>
        <ul className="glossary-sources">
          {(Object.keys(SOURCES) as SourceKey[])
            .filter((s) => usedSources.has(s))
            .sort((a, b) => byName(SOURCES[a].full, SOURCES[b].full))
            .map((s) => (
              <li key={s}>
                {SOURCES[s].full}{' '}
                <a href={SOURCES[s].url} target="_blank" rel="noreferrer noopener">
                  {SOURCES[s].url}
                </a>
              </li>
            ))}
        </ul>
      </section>
    </section>
  )
}
