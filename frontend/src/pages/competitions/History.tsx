// Wettbewerbe Schritt 4: Auszeichnungen einrichten, vergebene Titel und Würdenvorschläge,
// Reihen mit Archiv und Bestenliste, Wanderpokale mit Inhabern.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  historyApi,
  type Award,
  type Grant,
  type Series,
  type Trophy,
} from '../../api/competitionHistory.ts'
import type { CompetitionDetail } from '../../api/competitions.ts'
import { honorsApi } from '../../api/honors.ts'
import type { MemberRow } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { t, tn } from '../../i18n/index.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'

function places(a: { place_from: number; place_to: number }): string {
  return a.place_from === a.place_to
    ? t('Platz {n}', { n: a.place_from })
    : t('Platz {a} bis {b}', { a: a.place_from, b: a.place_to })
}

function awardText(a: Award): string {
  return [
    a.title,
    a.item,
    a.dignity_name && t('Würde: {name}', { name: a.dignity_name }),
    a.trophy_name && t('Wanderpokal: {name}', { name: a.trophy_name }),
  ]
    .filter(Boolean)
    .join(' · ')
}

/** Einrichten: Auszeichnungen je Wertung (Plätze) oder je Pfand. */
export function AwardsCard({ org, comp }: { org: number; comp: CompetitionDetail }) {
  const active = useActiveOrg()
  const { data, error, reload } = useLoad(
    () => historyApi.awards.list(org, comp.id),
    [org, comp.id],
  )
  const extras = useLoad(
    () => Promise.all([honorsApi.dignities(org).catch(() => []), historyApi.trophies.list(org)]),
    [org],
  )
  const bird = comp.form === 'vogel'
  const targets = bird
    ? comp.prizes.map((p) => ({ value: `p${p.id}`, label: p.name }))
    : comp.scorings.map((s) => ({ value: `s${s.id}`, label: s.name }))
  const empty = {
    target: targets[0]?.value ?? '',
    place_from: '1',
    place_to: '1',
    title: '',
    item: '',
    dignity: '',
    trophy: '',
  }
  const [v, setV] = useState(empty)
  const [message, setMessage] = useState<string | null>(null)
  const canManage = comp.can_manage
  const canHonors = active.permissions.includes(PERM.membersView)

  async function add(e: FormEvent) {
    e.preventDefault()
    setMessage(null)
    try {
      await historyApi.awards.create(org, comp.id, {
        scoring: v.target.startsWith('s') ? Number(v.target.slice(1)) : null,
        prize: v.target.startsWith('p') ? Number(v.target.slice(1)) : null,
        place_from: Number(v.place_from) || 1,
        place_to: Number(v.place_to) || Number(v.place_from) || 1,
        title: v.title,
        item: v.item,
        dignity: v.dignity ? Number(v.dignity) : null,
        trophy: v.trophy ? Number(v.trophy) : null,
      })
      setV({ ...empty, target: v.target })
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function remove(a: Award) {
    try {
      await historyApi.awards.remove(org, comp.id, a.id)
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  const name = (a: Award) =>
    a.prize
      ? comp.prizes.find((p) => p.id === a.prize)?.name
      : comp.scorings.find((s) => s.id === a.scoring)?.name
  const [dignities, trophies] = extras.data ?? [[], []]

  return (
    <div className="card card-wide">
      <h2>{t('Auszeichnungen')}</h2>
      <p className="muted">
        {bird
          ? t('Was es für ein Pfand gibt, z. B. Titel „Schützenkönig“ mit der Würde König.')
          : t(
              'Was es für welche Plätze gibt: Titel (z. B. „Vereinsmeister“, das Jahr kommt dazu), Preis, Würde oder Wanderpokal.',
            )}{' '}
        {t(
          'Vergeben wird, sobald der Wettbewerb endgültig ist; eine Würde erst, wenn ihr den Vorschlag bestätigt.',
        )}
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {data && data.length > 0 && (
        <ul className="plain-list">
          {data.map((a) => (
            <li key={a.id}>
              <strong>{name(a)}</strong>
              {!a.prize && ` · ${places(a)}`}: {awardText(a)}
              {canManage && (
                <button
                  type="button"
                  className="button button-ghost button-small"
                  onClick={() => void remove(a)}
                >
                  {t('Entfernen')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {data && data.length === 0 && <p className="muted">{t('Noch keine Auszeichnungen.')}</p>}
      {canManage && targets.length > 0 && (
        <form onSubmit={add}>
          <div className="grid-3">
            <SelectField
              label={bird ? t('Pfand') : t('Wertung')}
              value={v.target}
              onChange={(e) => setV({ ...v, target: e.target.value })}
            >
              {targets.map((x) => (
                <option key={x.value} value={x.value}>
                  {x.label}
                </option>
              ))}
            </SelectField>
            {!bird && (
              <>
                <Field
                  label={t('ab Platz')}
                  type="number"
                  min={1}
                  value={v.place_from}
                  onChange={(e) => setV({ ...v, place_from: e.target.value })}
                />
                <Field
                  label={t('bis Platz')}
                  type="number"
                  min={1}
                  value={v.place_to}
                  onChange={(e) => setV({ ...v, place_to: e.target.value })}
                />
              </>
            )}
            <Field
              label={t('Titel')}
              placeholder={t('z. B. Vereinsmeister')}
              value={v.title}
              onChange={(e) => setV({ ...v, title: e.target.value })}
            />
            <Field
              label={t('Preis')}
              placeholder={t('z. B. Pokal, Medaille')}
              value={v.item}
              onChange={(e) => setV({ ...v, item: e.target.value })}
            />
            {canHonors && (
              <SelectField
                label={t('Würde vorschlagen')}
                value={v.dignity}
                onChange={(e) => setV({ ...v, dignity: e.target.value })}
              >
                <option value="">{t('keine')}</option>
                {dignities
                  .filter((d) => !d.is_archived)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.unit_name ? `${d.name} (${d.unit_name})` : d.name}
                    </option>
                  ))}
              </SelectField>
            )}
            <SelectField
              label={t('Wanderpokal')}
              value={v.trophy}
              hint={t('Wanderpokale legt ihr unter Wettbewerbe › Wanderpokale an')}
              onChange={(e) => setV({ ...v, trophy: e.target.value })}
            >
              <option value="">{t('keiner')}</option>
              {trophies
                .filter((x) => !x.is_archived)
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
            </SelectField>
          </div>
          {message && <Alert kind="error">{message}</Alert>}
          <div className="button-row">
            <button type="submit" className="button">
              {t('Auszeichnung hinzufügen')}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

function grantLine(g: Grant): string {
  const parts = [g.full_title || g.trophy_name]
  if (g.scoring_name && !g.title) parts.push(g.scoring_name)
  if (g.place) parts.push(t('Platz {n}', { n: g.place }))
  return parts.filter(Boolean).join(' · ')
}

/** Auswertung: vergebene Auszeichnungen und Würdenvorschläge des Wettbewerbs. */
export function GrantsCard({
  org,
  comp,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  onChanged: () => void
}) {
  const active = useActiveOrg()
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const grants = comp.grants ?? []
  if (comp.status !== 'endgueltig' && grants.length === 0) return null
  const canConfirm = active.permissions.includes(PERM.membersEdit)

  async function decide(g: Grant, decision: 'bestaetigen' | 'ablehnen') {
    setMessage(null)
    try {
      await historyApi.grants.decide(org, g.id, decision)
      setMessage({
        kind: 'success',
        text:
          decision === 'bestaetigen'
            ? t('{name} ist als {dignity} {year} eingetragen.', {
                name: g.name,
                dignity: g.dignity_name,
                year: g.year,
              })
            : t('Vorschlag abgelehnt.'),
      })
      onChanged()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function again() {
    try {
      await historyApi.awards.grantAgain(org, comp.id)
      onChanged()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{t('Vergebene Auszeichnungen')}</h2>
        {comp.can_manage && comp.status === 'endgueltig' && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => void again()}
          >
            {t('Neu vergeben')}
          </button>
        )}
      </div>
      {grants.length === 0 ? (
        <p className="muted">
          {t('Keine. Auszeichnungen richtet ihr unter „Einrichten“ ein, dann „Neu vergeben“.')}
        </p>
      ) : (
        <ul className="plain-list">
          {grants.map((g) => (
            <li key={g.id}>
              <strong>{g.name}</strong>: {grantLine(g)}
              {g.dignity_state === 'vorschlag' && (
                <>
                  {' · '}
                  {t('Vorschlag: {dignity} {year}', { dignity: g.dignity_name, year: g.year })}{' '}
                  {canConfirm && comp.can_manage && (
                    <button
                      type="button"
                      className="button button-small"
                      onClick={() => void decide(g, 'bestaetigen')}
                    >
                      {t('Würde eintragen')}
                    </button>
                  )}{' '}
                  {comp.can_manage && (
                    <button
                      type="button"
                      className="button button-ghost button-small"
                      onClick={() => void decide(g, 'ablehnen')}
                    >
                      {t('Ablehnen')}
                    </button>
                  )}
                </>
              )}
              {g.dignity_state === 'bestaetigt' && (
                <span className="muted">
                  {' '}
                  · {t('{dignity} eingetragen', { dignity: g.dignity_name })}
                </span>
              )}
              {g.dignity_state === 'abgelehnt' && (
                <span className="muted"> · {t('Würde abgelehnt')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {grants.some((g) => g.dignity_state === 'vorschlag') && !canConfirm && (
        <p className="muted small">
          {t('Würden eintragen darf, wer zusätzlich „Mitglieder bearbeiten“ hat.')}
        </p>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </div>
  )
}

/** Einrichten: Reihe zuordnen (Archiv über die Jahre). */
export function SeriesSelect({
  org,
  value,
  disabled,
  onChange,
}: {
  org: number
  value: number | null
  disabled?: boolean
  onChange: (id: number | null) => void
}) {
  const { data, reload } = useLoad(() => historyApi.series.list(org), [org])
  async function create() {
    const name = await promptDialog({
      title: t('Neue Reihe'),
      label: t('Bezeichnung, z. B. „Vereinsmeisterschaft“'),
      confirmLabel: t('Anlegen'),
    })
    if (!name?.trim()) return
    const s = await historyApi.series.create(org, { name: name.trim() })
    reload()
    onChange(s.id)
  }
  return (
    <SelectField
      label={t('Reihe')}
      value={value ?? ''}
      disabled={disabled}
      hint={t('verbindet denselben Wettbewerb über die Jahre (Archiv, Bestenliste)')}
      onChange={(e) => {
        if (e.target.value === 'neu') void create()
        else onChange(e.target.value ? Number(e.target.value) : null)
      }}
    >
      <option value="">{t('keine')}</option>
      {(data ?? []).map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
      <option value="neu">{t('Neue Reihe …')}</option>
    </SelectField>
  )
}

// --- Seiten in der Seitenleiste ---

export function SeriesListPage() {
  const org = useActiveOrg()
  const canManage = org.permissions.includes(PERM.competitionsManage)
  const { data, error, reload } = useLoad(() => historyApi.series.list(org.id), [org.id])
  const [name, setName] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    try {
      await historyApi.series.create(org.id, { name })
      setName('')
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <section>
      <h1>{t('Reihen')}</h1>
      <p className="muted">
        {t(
          'Eine Reihe verbindet denselben Wettbewerb über die Jahre, z. B. „Vereinsmeisterschaft“: Sieger je Jahr, Titel, Bestenliste und eure Untereinheiten im Vergleich.',
        )}
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {data && data.length === 0 && <p className="muted">{t('Noch keine Reihen.')}</p>}
      {data && data.length > 0 && (
        <ul className="plain-list">
          {data.map((s: Series) => (
            <li key={s.id}>
              <Link to={`/wettbewerbe/reihen/${s.id}`}>{s.name}</Link>{' '}
              <span className="muted">
                · {tn('{n} Wettbewerb', '{n} Wettbewerbe', s.competition_count)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form onSubmit={add} className="card">
          <Field
            label={t('Neue Reihe')}
            placeholder={t('z. B. Vereinsmeisterschaft')}
            value={name}
            required
            onChange={(e) => setName(e.target.value)}
          />
          {message && <Alert kind="error">{message}</Alert>}
          <div className="button-row">
            <button type="submit" className="button">
              {t('Anlegen')}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

export function SeriesPage() {
  const org = useActiveOrg()
  const id = Number(useParams().id)
  const canManage = org.permissions.includes(PERM.competitionsManage)
  const { data, error, reload } = useLoad(() => historyApi.series.archive(org.id, id), [org.id, id])
  const [series, setSeries] = useState<Series | null>(null)
  if (error) return <LoadError message={error} onRetry={reload} />
  if (!data) return <p className="muted">{t('Wird geladen …')}</p>
  const s = series ?? {
    id: data.id,
    name: data.name,
    description: data.description,
    on_website: true,
    competition_count: data.years.length,
  }

  async function save(changes: Partial<Series>) {
    const saved = await historyApi.series.update(org.id, id, changes)
    setSeries(saved)
  }

  return (
    <section>
      <p>
        <Link to="/wettbewerbe/reihen">← {t('Alle Reihen')}</Link>
      </p>
      <h1>{data.name}</h1>
      {data.description && <p>{data.description}</p>}
      {canManage && (
        <Checkbox
          label={t('Archiv auf der Webseite zeigen')}
          checked={s.on_website}
          onChange={(on) => void save({ on_website: on })}
        />
      )}
      <h2>{t('Sieger je Jahr')}</h2>
      {data.years.length === 0 && (
        <p className="muted">
          {t(
            'Noch keine Wettbewerbe in dieser Reihe. Die Reihe wählt ihr beim Wettbewerb unter „Einrichten“.',
          )}
        </p>
      )}
      {data.years.map((y) => (
        <div key={y.competition} className="card card-wide">
          <h3>
            <Link to={`/wettbewerbe/${y.competition}/auswertung`}>{y.title}</Link>{' '}
            <span className="muted">· {y.year}</span>
          </h3>
          {y.winners.map((w) => (
            <p key={w.scoring}>
              <strong>{w.scoring}:</strong>{' '}
              {w.podium.length === 0
                ? '–'
                : w.podium
                    .map((r) =>
                      [r.place ? `${r.place}.` : '', r.name, r.value_text && `(${r.value_text})`]
                        .filter(Boolean)
                        .join(' '),
                    )
                    .join(', ')}
            </p>
          ))}
        </div>
      ))}
      {data.records.length > 0 && (
        <>
          <h2>{t('Bestenliste')}</h2>
          <p className="muted small">
            {t(
              'Bester Wert aller Jahre je Wertung; verglichen werden nur Jahre mit gleichen Regeln.',
            )}
          </p>
          <ul className="plain-list">
            {data.records.map((r) => (
              <li key={`${r.scoring}-${r.counted_shots}`}>
                <strong>{r.scoring}:</strong> {r.value_text} {r.unit_label} · {r.name} ({r.year})
              </li>
            ))}
          </ul>
        </>
      )}
      {data.units.length > 0 && (
        <>
          <h2>{t('Untereinheiten im Vergleich')}</h2>
          <ul className="plain-list">
            {data.units.map((u) => (
              <li key={u.unit}>
                <strong>{u.name}:</strong>{' '}
                {u.years.map((y) => t('{year} Platz {place}', y)).join(', ')}
              </li>
            ))}
          </ul>
        </>
      )}
      <TitlesList
        org={org.id}
        grants={data.titles}
        canManage={canManage}
        defaults={{ series: id }}
        onChanged={reload}
        heading={t('Titel')}
      />
    </section>
  )
}

export function TrophiesPage() {
  const org = useActiveOrg()
  const canManage = org.permissions.includes(PERM.competitionsManage)
  const { data, error, reload } = useLoad(() => historyApi.trophies.list(org.id), [org.id])
  const [name, setName] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    try {
      await historyApi.trophies.create(org.id, { name })
      setName('')
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function update(tr: Trophy, changes: Partial<Trophy>) {
    try {
      await historyApi.trophies.update(org.id, tr.id, changes)
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function remove(tr: Trophy) {
    const ok = await confirmDialog({
      title: t('Wanderpokal löschen'),
      message: t('„{name}“ löschen? Die Inhaber bleiben als Titel erhalten.', { name: tr.name }),
      confirmLabel: t('Löschen'),
    })
    if (!ok) return
    await historyApi.trophies.remove(org.id, tr.id)
    reload()
  }

  return (
    <section>
      <h1>{t('Wanderpokale')}</h1>
      <p className="muted">
        {t(
          'Ein Wanderpokal wechselt seine Inhaber. Ihr verknüpft ihn beim Wettbewerb unter „Einrichten“ › Auszeichnungen mit einem Platz; frühere Inhaber tragt ihr hier nach.',
        )}
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {message && <Alert kind="error">{message}</Alert>}
      {data?.map((tr) => (
        <div key={tr.id} className="card card-wide">
          <div className="card-head">
            <h2>{tr.name}</h2>
            {canManage && (
              <button
                type="button"
                className="button button-ghost push-right"
                onClick={() => void remove(tr)}
              >
                {t('Löschen')}
              </button>
            )}
          </div>
          {canManage && (
            <div className="grid-3">
              <Field
                label={t('In den Besitz nach Siegen in Folge')}
                type="number"
                min={1}
                max={20}
                defaultValue={tr.keep_after ?? ''}
                hint={t('leer: bleibt immer ein Wanderpokal')}
                onBlur={(e) => {
                  const n = e.target.value ? Number(e.target.value) : null
                  if (n !== tr.keep_after) void update(tr, { keep_after: n })
                }}
              />
              <Checkbox
                label={t('Inhaber auf der Webseite')}
                checked={tr.on_website}
                onChange={(on) => void update(tr, { on_website: on })}
              />
              <Checkbox
                label={t('nicht mehr vergeben')}
                checked={tr.is_archived}
                onChange={(on) => void update(tr, { is_archived: on })}
              />
            </div>
          )}
          {tr.holders.length === 0 ? (
            <p className="muted">{t('Noch keine Inhaber.')}</p>
          ) : (
            <ul className="plain-list">
              {tr.holders.map((h) => (
                <li key={h.id}>
                  {h.year}: <strong>{h.name}</strong>
                  {h.streak > 1 && ` · ${tn('{n}. Sieg in Folge', '{n}. Sieg in Folge', h.streak)}`}
                  {h.kept && ` · ${t('in den Besitz übergegangen')}`}
                </li>
              ))}
            </ul>
          )}
          {canManage && (
            <ManualGrant
              org={org.id}
              defaults={{ trophy: tr.id }}
              onSaved={reload}
              label={t('Früheren Inhaber nachtragen')}
            />
          )}
        </div>
      ))}
      {canManage && (
        <form onSubmit={add} className="card">
          <Field
            label={t('Neuer Wanderpokal')}
            placeholder={t('z. B. Zugpokal')}
            value={name}
            required
            onChange={(e) => setName(e.target.value)}
          />
          <div className="button-row">
            <button type="submit" className="button">
              {t('Anlegen')}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

export function TitlesPage() {
  const org = useActiveOrg()
  const canManage = org.permissions.includes(PERM.competitionsManage)
  const { data, error, reload } = useLoad(() => historyApi.grants.list(org.id), [org.id])
  const proposals = (data ?? []).filter((g) => g.dignity_state === 'vorschlag')
  return (
    <section>
      <h1>{t('Titel und Auszeichnungen')}</h1>
      <p className="muted">
        {t('Alles, was in Wettbewerben vergeben wurde, und von Hand nachgetragene frühere Jahre.')}
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {proposals.length > 0 && (
        <Alert kind="info">
          {tn(
            '{n} Würdenvorschlag wartet auf eure Entscheidung (beim Wettbewerb unter „Auswertung“).',
            '{n} Würdenvorschläge warten auf eure Entscheidung (beim Wettbewerb unter „Auswertung“).',
            proposals.length,
          )}
        </Alert>
      )}
      {data && <TitlesList org={org.id} grants={data} canManage={canManage} onChanged={reload} />}
    </section>
  )
}

function TitlesList({
  org,
  grants,
  canManage,
  defaults = {},
  onChanged,
  heading,
}: {
  org: number
  grants: Grant[]
  canManage: boolean
  defaults?: Partial<Grant>
  onChanged: () => void
  heading?: string
}) {
  async function remove(g: Grant) {
    await historyApi.grants.remove(org, g.id)
    onChanged()
  }
  return (
    <>
      {heading && <h2>{heading}</h2>}
      {grants.length === 0 ? (
        <p className="muted">{t('Noch keine Titel.')}</p>
      ) : (
        <ul className="plain-list">
          {grants.map((g) => (
            <li key={g.id}>
              {g.year}: <strong>{g.name}</strong> · {grantLine(g)}
              {g.competition && (
                <>
                  {' · '}
                  <Link to={`/wettbewerbe/${g.competition}/auswertung`}>{g.competition_title}</Link>
                </>
              )}
              {g.manual && <span className="muted"> · {t('nachgetragen')}</span>}
              {g.manual && canManage && (
                <button
                  type="button"
                  className="button button-ghost button-small"
                  onClick={() => void remove(g)}
                >
                  {t('Entfernen')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && <ManualGrant org={org} defaults={defaults} onSaved={onChanged} />}
    </>
  )
}

/** Früheres Jahr nachtragen (Altdaten, auch nur „Sieger je Jahr“). */
function ManualGrant({
  org,
  defaults,
  onSaved,
  label = t('Früheres Jahr nachtragen'),
}: {
  org: number
  defaults: Partial<Grant>
  onSaved: () => void
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const [member, setMember] = useState<MemberRow | null>(null)
  const [v, setV] = useState({ year: '', title: '', item: '', name: '', place: '' })
  const [message, setMessage] = useState<string | null>(null)
  if (!open)
    return (
      <div className="button-row">
        <button type="button" className="button button-ghost" onClick={() => setOpen(true)}>
          {label}
        </button>
      </div>
    )

  async function save(e: FormEvent) {
    e.preventDefault()
    setMessage(null)
    try {
      await historyApi.grants.create(org, {
        ...defaults,
        year: Number(v.year),
        title: v.title,
        item: v.item,
        place: v.place ? Number(v.place) : null,
        membership: member?.id ?? null,
        name: v.name,
      })
      setV({ year: '', title: v.title, item: '', name: '', place: '' })
      setMember(null)
      onSaved()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <form onSubmit={save} className="card">
      <h3>{label}</h3>
      <div className="grid-3">
        <Field
          label={t('Jahr')}
          type="number"
          required
          value={v.year}
          onChange={(e) => setV({ ...v, year: e.target.value })}
        />
        {!defaults.trophy && (
          <Field
            label={t('Titel')}
            placeholder={t('z. B. Vereinsmeister')}
            value={v.title}
            onChange={(e) => setV({ ...v, title: e.target.value })}
          />
        )}
        <Field
          label={t('Platz')}
          type="number"
          min={1}
          value={v.place}
          onChange={(e) => setV({ ...v, place: e.target.value })}
        />
        <MemberPicker orgId={org} value={member} onChange={setMember} />
        {!member && (
          <Field
            label={t('oder Name')}
            hint={t('für frühere Mitglieder und Gäste')}
            value={v.name}
            onChange={(e) => setV({ ...v, name: e.target.value })}
          />
        )}
      </div>
      {message && <Alert kind="error">{message}</Alert>}
      <div className="button-row">
        <button type="submit" className="button">
          {t('Speichern')}
        </button>
        <button type="button" className="button button-ghost" onClick={() => setOpen(false)}>
          {t('Schließen')}
        </button>
      </div>
    </form>
  )
}
