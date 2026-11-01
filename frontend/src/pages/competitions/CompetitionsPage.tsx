// Wettbewerbe: Liste, Einrichten (Grunddaten, Wertungen), Erfassen und Auswertung.
import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import {
  competitionsApi,
  orgStandApi,
  STATUS_LABELS,
  WEBSITE_DEPTH_LABELS,
  WEBSITE_LABELS,
  type Competition,
  type CompetitionDetail,
  type CompetitionStatus,
  type Detail,
  type Scoring,
  type WebsiteDepth,
  type WebsiteMode,
} from '../../api/competitions.ts'
import { PERM } from '../../api/orgs.ts'
import { DataTable } from '../../components/DataTable.tsx'
import { choiceDialog, confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import {
  Alert,
  Checkbox,
  Field,
  LoadError,
  SaveStatus,
  SelectField,
  Tabs,
} from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { BirdStand } from './BirdStand.tsx'
import { EventCard, EventPicker } from './CalendarLink.tsx'
import { ManualPrizes, PrizesCard, StandAccessCard } from './BirdSetup.tsx'
import { ForeignPanel } from './ForeignPanel.tsx'
import { ResultsPanel } from './ResultsPanel.tsx'
import {
  AwardsCard,
  GrantsCard,
  SeriesListPage,
  SeriesPage,
  SeriesSelect,
  TitlesPage,
  TrophiesPage,
} from './History.tsx'
import { StandPanel } from './StandPanel.tsx'
import { TargetSettings } from './TargetSettings.tsx'
import { Term, Why } from '../../learning/Aids.tsx'
import { Checklist } from '../../learning/Checklist.tsx'
import { competitionFinishChecks } from '../../learning/checks.ts'
import { locale, t } from '../../i18n/index.ts'

export function CompetitionsPage() {
  return (
    <Routes>
      <Route index element={<CompetitionList />} />
      <Route path="reihen" element={<SeriesListPage />} />
      <Route path="reihen/:id" element={<SeriesPage />} />
      <Route path="pokale" element={<TrophiesPage />} />
      <Route path="titel" element={<TitlesPage />} />
      <Route path=":id/*" element={<CompetitionArea />} />
    </Routes>
  )
}

function CompetitionList() {
  const org = useActiveOrg()
  const navigate = useNavigate()
  const canManage = org.permissions.includes(PERM.competitionsManage)
  const { data, error, reload } = useLoad(() => competitionsApi.list(org.id), [org.id])
  const [creating, setCreating] = useState(false)

  return (
    <section>
      <h1>Wettbewerbe</h1>
      <p className="muted">
        Eigene Schießen mit Einzel- und Zugwertung und Stechen, Vogelschießen mit Pfändern, und
        fremde Wettbewerbe, bei denen ihr eure Plätze eintragt.
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {canManage && !creating && (
        <div className="button-row">
          <button type="button" className="button" onClick={() => setCreating(true)}>
            Neuer Wettbewerb
          </button>
        </div>
      )}
      {creating && (
        <NewCompetition
          org={org.id}
          onClose={() => setCreating(false)}
          onCreated={(id) => navigate(`/wettbewerbe/${id}`)}
        />
      )}
      {data && (
        <DataTable<Competition>
          label="Wettbewerbe"
          rows={data}
          rowKey={(c) => c.id}
          initialSort={{ key: 'date', dir: 'desc' }}
          emptyText="Noch keine Wettbewerbe."
          columns={[
            {
              key: 'date',
              label: 'Datum',
              value: (c) => c.date,
              render: (c) => new Date(c.date).toLocaleDateString(locale()),
            },
            {
              key: 'title',
              label: 'Wettbewerb',
              value: (c) => c.title,
              render: (c) => <Link to={`/wettbewerbe/${c.id}`}>{c.title}</Link>,
            },
            { key: 'occasion', label: 'Anlass', value: (c) => c.occasion, optional: true },
            {
              key: 'starters',
              label: 'Starter',
              value: (c) => c.starter_count,
              numeric: true,
            },
            {
              key: 'status',
              label: 'Zustand',
              value: (c) => c.status_label,
              filter: true,
            },
          ]}
        />
      )}
    </section>
  )
}

/** Heutiges Datum (Ortszeit) als JJJJ-MM-TT */
function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function NewCompetition({
  org,
  onClose,
  onCreated,
}: {
  org: number
  onClose: () => void
  onCreated: (id: number) => void
}) {
  const form = useForm({
    title: '',
    date: todayIso(),
    template: 'schiessen',
    organizer: '',
    event: '',
  })
  const { values: v, set, errors } = form

  async function save(e: FormEvent) {
    e.preventDefault()
    const { event, ...rest } = v
    const created = await form.submit(() =>
      competitionsApi.create(org, {
        ...rest,
        form: v.template === 'vogel' ? 'vogel' : 'rangliste',
        own: v.template !== 'fremd',
        ...(event === 'neu' ? { create_event: true } : event ? { event: Number(event) } : {}),
      }),
    )
    if (created) onCreated((created as Competition).id)
  }

  return (
    <div className="card card-wide">
      <form onSubmit={save}>
        <div className="card-head">
          <h2>Neuer Wettbewerb</h2>
          <button type="button" className="button button-ghost push-right" onClick={onClose}>
            Abbrechen
          </button>
        </div>
        <div className="grid-3">
          <Field
            label="Titel"
            required
            placeholder="z. B. Preisschießen 2027"
            value={v.title}
            error={errors.title}
            onChange={(e) => set('title', e.target.value)}
          />
          <Field
            label="Datum"
            type="date"
            required
            value={v.date}
            error={errors.date}
            onChange={(e) => set('date', e.target.value)}
          />
          <SelectField
            label="Vorlage"
            value={v.template}
            onChange={(e) => set('template', e.target.value)}
          >
            <option value="schiessen">Schießen mit Einzel- und Zugwertung</option>
            <option value="einfach">nur Einzelwertung</option>
            <option value="vogel">Vogelschießen mit Pfändern</option>
            <option value="fremd">Fremder Wettbewerb (eigene Plätze eintragen)</option>
            <option value="">leer (Wertungen selbst anlegen)</option>
          </SelectField>
          <EventPicker
            org={org}
            value={v.event}
            onChange={(value, event) => {
              set('event', value)
              if (event) {
                set('title', event.title)
                set('date', event.date)
              }
            }}
          />
          {v.template === 'fremd' && (
            <Field
              label="Ausrichter"
              placeholder="z. B. Bürger-Schützenverein"
              value={v.organizer}
              error={errors.organizer}
              onChange={(e) => set('organizer', e.target.value)}
            />
          )}
        </div>
        <Why k="comp_own" />
        {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
        <div className="button-row">
          <button type="submit" className="button" disabled={form.busy}>
            Anlegen
          </button>
        </div>
      </form>
    </div>
  )
}

function CompetitionArea() {
  const org = useActiveOrg()
  const id = Number(useParams().id)
  const { data, error, reload, setData } = useLoad(
    () => competitionsApi.get(org.id, id),
    [org.id, id],
  )
  const standApi = useMemo(() => orgStandApi(org.id, id), [org.id, id])
  const [showAccess, setShowAccess] = useState(false)
  if (error) return <LoadError message={error} onRetry={reload} />
  if (!data) return <p className="muted">Wird geladen …</p>
  const base = `/wettbewerbe/${id}`
  return (
    <section>
      <p>
        <Link to="/wettbewerbe">← Alle Wettbewerbe</Link>
      </p>
      <h1>{data.title}</h1>
      <p className="muted">
        {new Date(data.date).toLocaleDateString(locale())}
        {data.occasion ? ` · ${data.occasion}` : ''}
        {data.discipline ? ` · ${data.discipline}` : ''}
        {!data.own && data.organizer ? (
          <>
            {' '}
            · <Term k="comp_organizer">Ausrichter</Term>: {data.organizer}
          </>
        ) : null}{' '}
        · {STATUS_LABELS[data.status]}
      </p>
      <Tabs
        items={[
          { to: base, label: 'Erfassen' },
          { to: `${base}/auswertung`, label: 'Auswertung' },
          { to: `${base}/einrichten`, label: 'Einrichten' },
        ]}
      />
      <Routes>
        <Route
          index
          element={
            <>
              <div className="button-row">
                {data.own && (
                  <a className="button button-ghost" href={`/stand/${org.id}/${id}`}>
                    Standmodus (Vollbild, Handy, offline)
                  </a>
                )}
                {data.own && data.can_manage && data.status !== 'endgueltig' && (
                  <button
                    type="button"
                    className="button button-ghost"
                    aria-expanded={showAccess}
                    onClick={() => setShowAccess((v) => !v)}
                  >
                    Anderes Gerät per QR-Code
                  </button>
                )}
                <PrintMenu org={org.id} comp={data} />
              </div>
              {showAccess && data.own && data.can_manage && (
                <StandAccessCard org={org.id} comp={data} />
              )}
              {!data.own ? (
                <ForeignPanel org={org.id} comp={data} />
              ) : data.form === 'vogel' ? (
                <>
                  <BirdStand
                    api={standApi}
                    comp={data}
                    onDrawAll={async () => {
                      await competitionsApi.drawAll(org.id, id)
                    }}
                  />
                  <ManualPrizes org={org.id} comp={data} />
                </>
              ) : (
                <StandPanel api={standApi} comp={data} />
              )}
            </>
          }
        />
        <Route
          path="auswertung"
          element={
            <>
              <ResultsPanel org={org.id} comp={data} onChanged={reload} />
              <GrantsCard org={org.id} comp={data} onChanged={reload} />
            </>
          }
        />
        <Route
          path="einrichten"
          element={<Setup org={org.id} comp={data} onChanged={setData} reload={reload} />}
        />
        <Route path="*" element={<Navigate to={base} replace />} />
      </Routes>
    </section>
  )
}

export function PrintMenu({ org, comp }: { org: number; comp: CompetitionDetail }) {
  async function print() {
    const choices = !comp.own
      ? [{ value: 'pdf', label: 'Ergebnisliste' }]
      : comp.form === 'vogel'
        ? [
            { value: 'losliste', label: 'Losliste (zum Zählen auf Papier)' },
            { value: 'pfaenderliste', label: 'Leere Pfänderliste' },
            { value: 'pdf', label: 'Pfänderliste mit Ergebnissen' },
          ]
        : [
            {
              value: 'schiessliste&sortierung=name',
              label: 'Schießliste nach Name',
              hint: 'Zum Eintragen am Stand, erfasste Werte sind eingedruckt',
            },
            {
              value: 'schiessliste&sortierung=einheit',
              label: 'Schießliste nach Zug',
              hint: 'Je Zug eine Tabelle mit Feldern für die Zugwertung',
            },
            {
              value: 'schiessliste&leer=1',
              label: 'Leere Schießliste',
              hint: 'Ohne Namen, für Nachmeldungen',
            },
          ]
    // Nach dem Schießen zuerst die Ergebnisliste (Ralf 2026-11-01)
    if (comp.own && comp.form !== 'vogel') {
      const result = { value: 'pdf', label: 'Ergebnisliste', hint: 'Plätze und Punkte' }
      if (comp.status === 'vorlaeufig' || comp.status === 'endgueltig') choices.unshift(result)
      else choices.push(result)
    }
    const choice = await choiceDialog({
      title: 'Drucken',
      message: 'Welche Vorlage? (PDF zum Ausdrucken)',
      choices,
      cancelValue: '',
    })
    if (choice) window.open(competitionsApi.exportUrl(org, comp.id, `als=${choice}`), '_blank')
  }
  return (
    <button type="button" className="button button-ghost" onClick={() => void print()}>
      Drucken …
    </button>
  )
}

function Setup({
  org,
  comp,
  onChanged,
  reload,
}: {
  org: number
  comp: CompetitionDetail
  onChanged: (c: CompetitionDetail) => void
  reload: () => void
}) {
  const navigate = useNavigate()
  const canManage = comp.can_manage
  const form = useForm({
    title: comp.title,
    occasion: comp.occasion,
    discipline: comp.discipline,
    location: comp.location,
    date: comp.date,
    description: comp.description,
    details: comp.details,
    website: comp.website,
    website_depth: comp.website_depth,
    share_ranking: comp.share_ranking,
    series: comp.series,
    organizer: comp.organizer,
    drop_out: comp.drop_out,
    fixed_order: comp.fixed_order,
    total_shots: comp.total_shots,
    lots: comp.lots,
  })
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) => competitionsApi.update(org, comp.id, changes), {
    enabled: canManage,
    onSaved: (saved) => onChanged({ ...comp, ...(saved as Competition) }),
  })

  function setDetail(i: number, d: Partial<Detail>) {
    set(
      'details',
      v.details.map((x, j) => (j === i ? { ...x, ...d } : x)),
    )
  }

  async function changeStatus(status: CompetitionStatus) {
    try {
      await competitionsApi.setStatus(org, comp.id, status)
      reload()
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function reset() {
    const choice = await choiceDialog({
      title: 'Wettbewerb zurücksetzen',
      message: `Bei „${comp.title}“ alle erfassten Ergebnisse löschen (Werte, Stechen, Schüsse, gefallene Pfänder)? Regeln, Pfänder, Standzugang und Termin bleiben, der Zustand geht auf „Vorbereitung“. Das lässt sich nicht rückgängig machen.`,
      choices: [
        { value: 'ergebnisse', label: 'Nur Ergebnisse löschen' },
        { value: 'alles', label: 'Ergebnisse und Schützen löschen' },
      ],
      cancelValue: '',
    })
    if (!choice) return
    try {
      await competitionsApi.reset(org, comp.id, choice === 'ergebnisse')
      reload()
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function copy() {
    try {
      const res = await competitionsApi.copy(org, comp.id)
      navigate(`/wettbewerbe/${res.id}/einrichten`)
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: 'Wettbewerb löschen',
      message: `„${comp.title}“ mit allen Startern, Ergebnissen und Stechen löschen?`,
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    try {
      await competitionsApi.remove(org, comp.id)
      navigate('/wettbewerbe')
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <>
      <div className="card card-wide">
        <div className="card-head">
          <h2>Grunddaten</h2>
          {canManage && <SaveStatus auto={auto} />}
        </div>
        <fieldset disabled={!canManage}>
          <div className="grid-3">
            <Field
              label="Titel"
              required
              value={v.title}
              error={errors.title}
              onChange={(e) => set('title', e.target.value)}
            />
            <Field
              label="Datum"
              type="date"
              required
              value={v.date}
              error={errors.date}
              onChange={(e) => set('date', e.target.value)}
            />
            <Field
              label="Anlass"
              placeholder="z. B. Schützenfest"
              value={v.occasion}
              error={errors.occasion}
              onChange={(e) => set('occasion', e.target.value)}
            />
            <Field
              label="Art"
              placeholder="z. B. Luftgewehr"
              value={v.discipline}
              error={errors.discipline}
              onChange={(e) => set('discipline', e.target.value)}
            />
            <Field
              label="Ort"
              value={v.location}
              error={errors.location}
              onChange={(e) => set('location', e.target.value)}
            />
            {!comp.own && (
              <Field
                label="Ausrichter"
                value={v.organizer}
                error={errors.organizer}
                onChange={(e) => set('organizer', e.target.value)}
              />
            )}
            <SeriesSelect
              org={org}
              value={v.series}
              disabled={!canManage}
              onChange={(id) => set('series', id)}
            />
            <SelectField
              label="Auf der Webseite"
              value={v.website}
              onChange={(e) => set('website', e.target.value as WebsiteMode)}
            >
              {Object.entries(WEBSITE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </SelectField>
            {v.website !== 'aus' && (
              <SelectField
                label={t('Umfang auf der Webseite')}
                value={v.website_depth}
                onChange={(e) => set('website_depth', e.target.value as WebsiteDepth)}
              >
                {Object.entries(WEBSITE_DEPTH_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </SelectField>
            )}
          </div>
          <Why k="comp_website" />
          {comp.from_call && (
            <Checkbox
              label={t('Ganze Rangliste an die meldenden Untereinheiten')}
              hint={t(
                'Nach dem Abschluss sieht jede meldende Untereinheit in ihrer Meldung ihre Starter, Mannschaften und die Wertung der Untereinheiten; eingeschaltet auch die ganze Einzelrangliste mit allen Namen.',
              )}
              checked={v.share_ranking}
              onChange={(on) => set('share_ranking', on)}
            />
          )}
          {comp.form === 'vogel' && (
            <>
              <h3>Vogelschießen</h3>
              <div className="grid-3">
                <Checkbox
                  label="Wer ein Pfand errungen hat, scheidet aus"
                  checked={v.drop_out}
                  onChange={(on) => set('drop_out', on)}
                />
                <Checkbox
                  label="Pfänder in fester Reihenfolge"
                  hint="aus: jeder Schuss kann jedes noch hängende Teil treffen"
                  checked={v.fixed_order}
                  onChange={(on) => set('fixed_order', on)}
                />
                <Field
                  label="Schüsse insgesamt"
                  type="number"
                  min={1}
                  hint="nur, wenn auf Papier gezählt wurde; live zählt der Standmodus"
                  value={v.total_shots ?? ''}
                  error={errors.total_shots}
                  onChange={(e) => set('total_shots', numOrNull(e.target.value))}
                />
                <Field
                  label="Lose im Hut"
                  type="number"
                  min={1}
                  hint="„Nummer ziehen“ zieht zufällig aus 1 bis zu dieser Zahl, z. B. 60; leer: bis zur Zahl der Schützen, dann bekommt ein Nachzügler meist die nächste Nummer"
                  value={v.lots ?? ''}
                  error={errors.lots}
                  onChange={(e) => set('lots', numOrNull(e.target.value))}
                />
              </div>
              <Why k="comp_bird_rules" />
              <Why k="comp_lots" />
            </>
          )}
          <label className="field">
            <span>Beschreibung</span>
            <textarea
              rows={3}
              value={v.description}
              onChange={(e) => set('description', e.target.value)}
            />
          </label>
          <h3>Weitere Angaben</h3>
          {v.details.map((d, i) => (
            <div className="grid-3" key={i}>
              <Field
                label="Angabe"
                placeholder="z. B. Entfernung"
                value={d.label}
                onChange={(e) => setDetail(i, { label: e.target.value })}
              />
              <Field
                label="Wert"
                placeholder="z. B. 10 m"
                value={d.value}
                onChange={(e) => setDetail(i, { value: e.target.value })}
              />
              <div className="button-row">
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() =>
                    set(
                      'details',
                      v.details.filter((_, j) => j !== i),
                    )
                  }
                >
                  Entfernen
                </button>
              </div>
            </div>
          ))}
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              onClick={() => set('details', [...v.details, { label: '', value: '' }])}
            >
              Angabe hinzufügen
            </button>
          </div>
        </fieldset>
        {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      </div>

      <EventCard
        org={org}
        comp={comp}
        onChanged={(res) => {
          // Ort und Beschreibung kommen aus dem Termin, wenn sie leer waren
          if (res.location !== v.location) set('location', res.location)
          if (res.description !== v.description) set('description', res.description)
          reload()
        }}
      />
      {comp.form === 'vogel' && <PrizesCard org={org} comp={comp} onChanged={reload} />}
      {comp.form !== 'vogel' && <h2>Wertungen</h2>}
      {comp.scorings.map((s) => (
        <ScoringCard
          key={s.id}
          org={org}
          comp={comp}
          scoring={s}
          canManage={canManage}
          onRemoved={reload}
        />
      ))}
      {canManage && comp.form !== 'vogel' && (
        <div className="button-row">
          <button
            type="button"
            className="button button-ghost"
            onClick={() =>
              void competitionsApi
                .createScoring(org, comp.id, { name: 'Einzelwertung', kind: 'einzel' })
                .then(reload)
            }
          >
            Einzelwertung hinzufügen
          </button>
          {!comp.own && (
            <button
              type="button"
              className="button button-ghost"
              onClick={() =>
                void competitionsApi
                  .createScoring(org, comp.id, { name: 'Mannschaftswertung', kind: 'mannschaft' })
                  .then(reload)
              }
            >
              Mannschaftswertung hinzufügen
            </button>
          )}
          {comp.own && comp.scorings.some((s) => s.kind === 'einzel') && (
            <button
              type="button"
              className="button button-ghost"
              onClick={() =>
                void competitionsApi
                  .createScoring(org, comp.id, {
                    name: 'Wertung der Untereinheiten',
                    kind: 'einheit',
                    team_mode: 'beste',
                    team_size: 5,
                  })
                  .then(reload)
              }
            >
              Wertung der Untereinheiten hinzufügen
            </button>
          )}
        </div>
      )}
      <AwardsCard org={org} comp={comp} />

      {canManage && (
        <div className="card card-wide">
          <h2>Zustand und Weiteres</h2>
          <p>
            Zustand: <strong>{STATUS_LABELS[comp.status]}</strong>
            <span className="muted">
              {' '}
              · erst <Term k="comp_provisional_term">vorläufig</Term>, nach dem Abschluss{' '}
              <Term k="comp_final_term">endgültig</Term>
            </span>
          </p>
          {comp.own && comp.status !== 'endgueltig' && <FinishChecklist org={org} comp={comp} />}
          <div className="button-row">
            {comp.status !== 'vorlaeufig' && comp.status !== 'endgueltig' && (
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void changeStatus('vorlaeufig')}
              >
                Als vorläufig kennzeichnen
              </button>
            )}
            {comp.status !== 'endgueltig' ? (
              <button
                type="button"
                className="button"
                onClick={() => void changeStatus('endgueltig')}
              >
                Endgültig abschließen
              </button>
            ) : (
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void changeStatus('vorlaeufig')}
              >
                Wieder öffnen
              </button>
            )}
            <button type="button" className="button button-ghost" onClick={() => void copy()}>
              Für das nächste Jahr kopieren
            </button>
            {comp.status !== 'endgueltig' && (
              <button type="button" className="button button-danger" onClick={() => void reset()}>
                Zurücksetzen …
              </button>
            )}
            <button type="button" className="button button-danger" onClick={() => void remove()}>
              Löschen
            </button>
          </div>
          <Why k="comp_provisional" />
          <Why k="comp_final" />
          {comp.status !== 'endgueltig' && <Why k="comp_reset" />}
        </div>
      )}
    </>
  )
}

const TEAM_MODES = [
  { value: 'beste', label: 'Summe der besten' },
  { value: 'summe', label: 'Summe aller' },
  { value: 'durchschnitt', label: 'Durchschnitt aller' },
]

function numOrNull(text: string): number | null {
  const n = parseInt(text, 10)
  return Number.isFinite(n) ? n : null
}

function ScoringCard({
  org,
  comp,
  scoring,
  canManage,
  onRemoved,
}: {
  org: number
  comp: CompetitionDetail
  scoring: Scoring
  canManage: boolean
  onRemoved: () => void
}) {
  const form = useForm({
    name: scoring.name,
    shots: scoring.shots,
    counted_shots: scoring.counted_shots,
    max_per_shot: scoring.max_per_shot,
    unit_label: scoring.unit_label,
    decimals: scoring.decimals,
    higher_better: scoring.higher_better,
    source: scoring.source,
    team_mode: scoring.team_mode,
    team_size: scoring.team_size,
    prize_places: scoring.prize_places,
    shootoff_shots: scoring.shootoff_shots,
    shootoff_counted: scoring.shootoff_counted,
    field_size: scoring.field_size,
    target: scoring.target ?? '',
    custom_target: scoring.custom_target ?? {},
    method: scoring.method ?? 'frei',
    tie_breaks: scoring.tie_breaks ?? [],
    series_size: scoring.series_size ?? 10,
  })
  const { values: v, set, errors } = form
  const auto = useAutoSave(
    form,
    (changes) => competitionsApi.updateScoring(org, comp.id, scoring.id, changes),
    {
      enabled: canManage,
      // Scheibe und Wertungsart stellen Nachkommastellen, Richtung und Höchstwert ein
      onSaved: (result) => {
        const r = result as Scoring | undefined
        if (!r || r.method === 'frei') return
        set('decimals', r.decimals)
        set('higher_better', r.higher_better)
        set('max_per_shot', r.max_per_shot)
        set('unit_label', r.unit_label)
      },
    },
  )
  const unit = scoring.kind === 'einheit'
  const singles = comp.scorings.filter((s) => s.kind === 'einzel')
  const foreign = !comp.own
  const single = !unit && !foreign
  const catalog = useLoad(
    () => (single ? competitionsApi.targets(org) : Promise.resolve(null)),
    [org, single],
  )
  const fromHits = single && v.method !== 'frei'

  async function remove() {
    const ok = await confirmDialog({
      title: 'Wertung löschen',
      message: `„${scoring.name}“ mit allen Ergebnissen und Stechen löschen?`,
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    await competitionsApi.removeScoring(org, comp.id, scoring.id)
    onRemoved()
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h3>
          {unit ? (
            <Term k="comp_unit_scoring">Wertung der Untereinheiten</Term>
          ) : scoring.kind === 'mannschaft' ? (
            'Mannschaftswertung'
          ) : (
            'Einzelwertung'
          )}
        </h3>
        {canManage && <SaveStatus auto={auto} />}
      </div>
      <fieldset disabled={!canManage}>
        <div className="grid-3">
          <Field
            label="Bezeichnung"
            value={v.name}
            error={errors.name}
            onChange={(e) => set('name', e.target.value)}
          />
          {foreign ? (
            <>
              <Field
                label="Teilnehmer insgesamt"
                type="number"
                min={1}
                hint="für „Platz 2 von 14“"
                value={v.field_size ?? ''}
                error={errors.field_size}
                onChange={(e) => set('field_size', numOrNull(e.target.value))}
              />
              <Field
                label="Einheit des Werts"
                value={v.unit_label}
                error={errors.unit_label}
                onChange={(e) => set('unit_label', e.target.value)}
              />
              <SelectField
                label="Nachkommastellen"
                value={v.decimals}
                onChange={(e) => set('decimals', Number(e.target.value))}
              >
                {[0, 1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </SelectField>
            </>
          ) : unit ? (
            <>
              <SelectField
                label="Aus der Wertung"
                value={v.source ?? ''}
                error={errors.source}
                onChange={(e) => set('source', numOrNull(e.target.value))}
              >
                {singles.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label="Rechenweise"
                value={v.team_mode}
                error={errors.team_mode}
                onChange={(e) => set('team_mode', e.target.value as Scoring['team_mode'])}
              >
                {TEAM_MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </SelectField>
              {v.team_mode === 'beste' && (
                <Field
                  label="Anzahl der besten"
                  type="number"
                  min={1}
                  hint="Weniger Schützen: die Einheit wird nicht gewertet."
                  value={v.team_size ?? ''}
                  error={errors.team_size}
                  onChange={(e) => set('team_size', numOrNull(e.target.value))}
                />
              )}
            </>
          ) : (
            <>
              <Field
                label="Schüsse je Schütze"
                type="number"
                min={1}
                value={v.shots ?? ''}
                error={errors.shots}
                onChange={(e) => set('shots', numOrNull(e.target.value))}
              />
              <Field
                label="davon in der Wertung"
                type="number"
                min={1}
                value={v.counted_shots ?? ''}
                error={errors.counted_shots}
                onChange={(e) => set('counted_shots', numOrNull(e.target.value))}
              />
              {!fromHits && (
                <>
                  <Field
                    label="Höchstwert je Schuss"
                    inputMode="decimal"
                    value={v.max_per_shot ?? ''}
                    error={errors.max_per_shot}
                    onChange={(e) => set('max_per_shot', e.target.value.replace(',', '.') || null)}
                  />
                  <Field
                    label="Einheit des Werts"
                    value={v.unit_label}
                    error={errors.unit_label}
                    onChange={(e) => set('unit_label', e.target.value)}
                  />
                  <SelectField
                    label="Nachkommastellen"
                    value={v.decimals}
                    onChange={(e) => set('decimals', Number(e.target.value))}
                  >
                    {[0, 1, 2, 3].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </SelectField>
                  <Checkbox
                    label="Größer ist besser"
                    hint="aus bei Zeit oder Teiler"
                    checked={v.higher_better}
                    onChange={(on) => set('higher_better', on)}
                  />
                </>
              )}
            </>
          )}
          <Field
            label="Preisplätze"
            type="number"
            min={0}
            value={v.prize_places}
            error={errors.prize_places}
            onChange={(e) => set('prize_places', numOrNull(e.target.value) ?? 0)}
          />
          {!foreign && (
            <Field
              label="Schüsse im Stechen (Vorschlag)"
              type="number"
              min={1}
              hint="beim Anlegen des Stechens vor Ort änderbar"
              value={v.shootoff_shots ?? ''}
              error={errors.shootoff_shots}
              onChange={(e) => set('shootoff_shots', numOrNull(e.target.value))}
            />
          )}
          {!unit && !foreign && (
            <Field
              label="davon gewertet (Vorschlag)"
              type="number"
              min={1}
              value={v.shootoff_counted ?? ''}
              error={errors.shootoff_counted}
              onChange={(e) => set('shootoff_counted', numOrNull(e.target.value))}
            />
          )}
        </div>
        {!foreign && !unit && (
          <p className="muted small">
            Mit <Term k="comp_counted">gewerteten Schüssen</Term> und Höchstwert prüft HUBIplan jede
            Eingabe.
            {fromHits &&
              (v.method === 'teiler'
                ? ' Teiler: kleiner ist besser, es zählt der beste Teiler (bei mehreren gewerteten Schüssen ihre Summe).'
                : ` Höchstwert je Schuss ${String(v.max_per_shot ?? '').replace('.', ',')}, ${v.decimals ? 'mit Zehnteln' : 'ganze Ringe'}.`)}
          </p>
        )}
        {single && catalog.data && (
          <TargetSettings
            catalog={catalog.data}
            values={v}
            set={(key, value) => set(key, value as (typeof v)[typeof key])}
            errors={errors}
          />
        )}
        {!foreign && (unit ? <Why k="comp_team_mode" /> : <Why k="comp_shots" />)}
        {!foreign && <Why k="comp_prize_places" />}
        {canManage && (
          <div className="button-row">
            <button type="button" className="button button-ghost" onClick={() => void remove()}>
              Wertung löschen
            </button>
          </div>
        )}
      </fieldset>
    </div>
  )
}

/** Prüfliste vor „Endgültig abschließen“; blockiert nichts (Lernhilfen Wettbewerbe). */
function FinishChecklist({ org, comp }: { org: number; comp: CompetitionDetail }) {
  const { data } = useLoad(() => competitionsApi.standings(org, comp.id), [org, comp.id])
  if (!data) return null
  return (
    <Checklist
      title="Vor dem endgültigen Abschluss"
      items={competitionFinishChecks({
        missing: data.scorings
          .filter((b) => b.kind === 'einzel')
          .reduce((n, b) => n + b.without_value.length, 0),
        openShootoffs: data.open_shootoffs,
        bird: comp.form === 'vogel',
        hangingPrizes: data.bird ? data.bird.prizes.filter((p) => !p.winner_name).length : 0,
        website: comp.website,
      })}
    />
  )
}
