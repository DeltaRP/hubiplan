// Erfassen am Stand (Kartenschießen): Schützen kommen in beliebiger Reihenfolge mit ihrer
// Karte. Ein Suchfeld ist immer aktiv: Name oder Startnummer, Enter, Punkte, Enter.
// Alle Eingaben landen erst auf dem Gerät und gleichen sich bei Empfang selbst ab
// (Schießstände im Keller, Ralf 2026-11-01).
import { useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { newRequestKey } from '../../api/client.ts'
import {
  foldName,
  showValue,
  type CompetitionDetail,
  type MemberChoice,
  type Scoring,
  type StandApi,
  type Starter,
  type SyncOp,
  type TargetInfo,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { Term, Why } from '../../learning/Aids.tsx'
import { StandEnd } from './StandEnd.tsx'
import { StandFinish } from './StandFinish.tsx'
import { PhotoButton } from './PhotoButton.tsx'
import type { PhotoSuggestion } from './photo.ts'
import { TargetPad, type PadHit } from './TargetPad.tsx'
import { scoreShot, totalText } from './targetMath.ts'
import { describe, guestOrigin, useStandStore } from './standStore.ts'
import { t } from '../../i18n/index.ts'

type Hit =
  | { kind: 'starter'; starter: Starter }
  | { kind: 'member'; member: MemberChoice }
  | { kind: 'guest'; name: string }

export function StandPanel({
  api,
  comp,
  fullscreen = false,
  org,
}: {
  api: StandApi
  comp: CompetitionDetail
  fullscreen?: boolean
  /** angemeldet im Standmodus: dazu „Schießen beenden“ und der Abschluss */
  org?: number
}) {
  const scoring: Scoring | undefined = comp.scorings.find((s) => s.kind === 'einzel')
  const [notice, setNotice] = useState<string | null>(null)
  const { local, setLocal, push, online, syncError, pending, statusText } = useStandStore(
    api,
    describe,
    (conflicts) => {
      const values = conflicts.filter((c) => c.value !== undefined)
      const notes = conflicts.filter((c) => c.value === undefined && c.note)
      setNotice(
        [
          values.length
            ? t('Auf einem anderen Gerät später geändert, dieser Wert gilt: {x}', {
                x: values
                  .map((c) => `${c.name} ${showValue(c.value, scoring?.decimals ?? 0)}`)
                  .join(', '),
              })
            : '',
          ...notes.map((c) => t('{name} {note}.', { name: c.name, note: c.note })),
        ]
          .filter(Boolean)
          .join(' '),
      )
    },
    // auch ohne eigene Eingaben regelmäßig den Stand holen: Eingaben anderer Geräte
    // (Standmodus, Standzugang) erscheinen so ohne Neuladen
    true,
  )
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [chosen, setChosen] = useState<Hit | null>(null)
  const [points, setPoints] = useState('')
  const [guestClub, setGuestClub] = useState('')
  // Antippen auf dem Scheibenbild (Schießscheiben Schritt 2); „nur Summe“ schaltet zurück
  const [padHits, setPadHits] = useState<PadHit[]>([])
  const [sumOnly, setSumOnly] = useState(false)
  // Vorschlag aus dem Foto (Schritt 4): Hinweis, bis gespeichert oder abgebrochen
  const [photoNote, setPhotoNote] = useState<PhotoSuggestion | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const pointsRef = useRef<HTMLInputElement>(null)
  const closed = (local.status ?? comp.status) === 'endgueltig'

  const hits: Hit[] = useMemo(() => {
    const q = foldName(query.trim())
    if (!q) return []
    const words = q.split(/\s+/)
    const match = (name: string, extra = '') => {
      const hay = foldName(t('{name} {extra}', { name, extra }))
      return words.every((w) => hay.includes(w))
    }
    const startersHit = local.starters
      .filter((s) => s.number === query.trim() || match(s.name, s.unit_name))
      .slice(0, 8)
      .map((s): Hit => ({ kind: 'starter', starter: s }))
    const taken = new Set(local.starters.map((s) => s.membership).filter(Boolean))
    const membersHit = local.members
      .filter((m) => !taken.has(m.membership) && match(m.name, m.unit_name))
      .slice(0, 8)
      .map((m): Hit => ({ kind: 'member', member: m }))
    return [...startersHit, ...membersHit, { kind: 'guest', name: query.trim() }]
  }, [query, local.starters, local.members])

  const target = scoring?.target_info ?? null
  const tapping = !!target && !!scoring && scoring.method !== 'frei' && !sumOnly
  // Plausibilität (Schritt 6): Summe der erkannten Treffer neben der Handeingabe
  const photoSum = useMemo(
    () =>
      photoNote && target && scoring && photoNote.hits.length
        ? totalText(
            scoring.method,
            photoNote.hits.map((h) => scoreShot(target, h.x, h.y)),
            scoring.counted_shots,
          )
        : '',
    [photoNote, target, scoring],
  )
  const photoDiffers =
    photoSum !== '' &&
    points.trim() !== '' &&
    Number(points.trim().replace(',', '.')) !== Number(photoSum)

  function storedHits(s: Starter | null): PadHit[] {
    if (!s || !scoring) return []
    return (s.hits?.[String(scoring.id)] ?? []).map((h) => ({
      x: Number(h.x),
      y: Number(h.y),
      spot: h.spot,
      source: h.source,
    }))
  }

  function choose(hit: Hit) {
    setChosen(hit)
    setPoints('')
    setGuestClub('')
    setPadHits(storedHits(hit.kind === 'starter' ? hit.starter : null))
    setPhotoNote(null)
    setTimeout(() => pointsRef.current?.focus(), 0)
  }

  function onSearchKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, hits.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter' && hits.length) {
      e.preventDefault()
      choose(hits[Math.min(active, hits.length - 1)])
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!chosen || !scoring) return
    if (tapping && target) {
      await submitHits(target)
      return
    }
    const value = points.trim().replace(',', '.')
    if (value !== '' && !Number.isFinite(Number(value))) {
      setNotice(t('Bitte eine Zahl eingeben.'))
      return
    }
    const max = scoring.max_per_shot
      ? Number(scoring.max_per_shot) * (scoring.counted_shots || scoring.shots || 0)
      : 0
    if (value !== '' && max && Number(value) > max) {
      setNotice(t('Höchstens {x}.', { x: showValue(String(max), 0) }))
      return
    }
    if (value !== '' && photoSum !== '' && Number(value) !== Number(photoSum)) {
      const ok = await confirmDialog({
        title: t('Weicht vom Foto ab'),
        message: t(
          'Eingegeben: {x} {unit_label}. Das Foto ergibt {x2}. Bitte die Scheibe prüfen. Die Eingabe trotzdem speichern?',
          {
            x: showValue(value, scoring.decimals),
            unit_label: scoring.unit_label,
            x2: showValue(photoSum, scoring.decimals),
          },
        ),
        confirmLabel: t('Eingabe speichern'),
        danger: false,
      })
      if (!ok) return
    }
    let ref: number | string
    let name: string
    if (chosen.kind === 'starter') {
      const s = chosen.starter
      ref = s.key ?? s.id
      name = s.name
      const old = s.values[String(scoring.id)]
      if (old !== undefined && old !== '' && value !== '' && Number(old) !== Number(value)) {
        const ok = await confirmDialog({
          title: t('Schon erfasst'),
          message: t('{name} hat schon {x} {unit_label}. Durch {x2} ersetzen?', {
            name: s.name,
            x: showValue(old, scoring.decimals),
            unit_label: scoring.unit_label,
            x2: showValue(value, scoring.decimals),
          }),
          confirmLabel: t('Ersetzen'),
          danger: false,
        })
        if (!ok) return
      }
    } else {
      ;({ ref, name } = addStarter(chosen))
    }
    if (value !== '') {
      const at = new Date().toISOString()
      push({ op: 'score', starter: ref, scoring: scoring.id, value, at }, (l) => ({
        ...l,
        starters: l.starters.map((s) =>
          (s.key ?? s.id) === ref ? { ...s, values: { ...s.values, [scoring.id]: value } } : s,
        ),
        recent: [{ ref, name, value, at }, ...l.recent].slice(0, 10),
      }))
      setNotice(
        t('{name}: {x} {unit_label}', {
          name,
          x: showValue(value, scoring.decimals),
          unit_label: scoring.unit_label,
        }),
      )
    } else {
      push(null)
      setNotice(t('{name} eingetragen.', { name }))
    }
    setChosen(null)
    setQuery('')
    setPoints('')
    setActive(0)
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  /** Neuer Schütze: als Starter vormerken; zurück kommt der Verweis für weitere Eingaben. */
  function addStarter(c: Exclude<Hit, { kind: 'starter' }>): { ref: string; name: string } {
    const key = newRequestKey()
    const name = c.kind === 'member' ? c.member.name : c.name
    const origin = guestOrigin(guestClub, comp.units)
    const starter: Starter & { key: string } = {
      id: 0,
      key,
      name,
      club: c.kind === 'guest' ? origin.club : '',
      guest: c.kind === 'guest',
      membership: c.kind === 'member' ? c.member.membership : null,
      unit: c.kind === 'member' ? c.member.unit : origin.unit,
      unit_name: c.kind === 'member' ? c.member.unit_name : origin.unit_name,
      number: '',
      out_of_competition: false,
      presence: '',
      drawn_how: '',
      values: {},
    }
    const op: SyncOp =
      c.kind === 'member'
        ? { op: 'starter', client_key: key, membership: c.member.membership }
        : { op: 'starter', client_key: key, name, club: origin.club, unit: origin.unit }
    setLocal((l) => ({ ...l, ops: [...l.ops, op], starters: [...l.starters, starter] }))
    return { ref: key, name }
  }

  async function submitHits(tm: NonNullable<typeof target>) {
    if (!chosen || !scoring) return
    const max = scoring.shots
    if (max && padHits.length > max) {
      setNotice(t('Höchstens {max} Treffer.', { max }))
      return
    }
    const before = chosen.kind === 'starter' ? storedHits(chosen.starter) : []
    const same =
      before.length === padHits.length &&
      before.every((h, i) => h.x === padHits[i].x && h.y === padHits[i].y)
    let ref: number | string
    let name: string
    if (chosen.kind === 'starter') {
      ref = chosen.starter.key ?? chosen.starter.id
      name = chosen.starter.name
    } else {
      ;({ ref, name } = addStarter(chosen))
    }
    const value = totalText(
      scoring.method,
      padHits.map((h) => scoreShot(tm, h.x, h.y)),
      scoring.counted_shots,
    )
    if (same && chosen.kind === 'starter') {
      push(null)
      setNotice(t('{name}: unverändert.', { name }))
    } else {
      const at = new Date().toISOString()
      const hits = padHits.map((h) => ({
        x: h.x,
        y: h.y,
        spot: h.spot ?? null,
        source: h.source ?? ('tippen' as const),
      }))
      const samples = photoNote?.samples.length ? photoNote.samples : undefined
      push({ op: 'hits', starter: ref, scoring: scoring.id, hits, at, samples }, (l) => ({
        ...l,
        starters: l.starters.map((s) =>
          (s.key ?? s.id) === ref
            ? {
                ...s,
                values: { ...s.values, [scoring.id]: value },
                hits: { ...s.hits, [scoring.id]: hits },
              }
            : s,
        ),
        recent: value ? [{ ref, name, value, at }, ...l.recent].slice(0, 10) : l.recent,
      }))
      setNotice(
        value
          ? t('{name}: {x} {unit_label}', {
              name,
              x: showValue(value, scoring.decimals),
              unit_label: scoring.unit_label,
            })
          : t('{name} eingetragen.', { name }),
      )
    }
    setPadHits([])
    setPhotoNote(null)
    backToSearch()
  }

  function backToSearch() {
    setChosen(null)
    setQuery('')
    setPoints('')
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  async function clearValue(s: Starter) {
    if (!scoring) return
    const ok = await confirmDialog({
      title: t('Wert löschen'),
      message: t('Den Wert von {name} löschen? {name2} steht danach wieder unter „Noch offen“.', {
        name: s.name,
        name2: s.name,
      }),
      confirmLabel: t('Löschen'),
    })
    if (!ok) return
    const ref = s.key ?? s.id
    const at = new Date().toISOString()
    push({ op: 'score', starter: ref, scoring: scoring.id, value: null, at }, (l) => ({
      ...l,
      starters: l.starters.map((x) =>
        (x.key ?? x.id) === ref ? { ...x, values: { ...x.values, [scoring.id]: '' } } : x,
      ),
      recent: l.recent.filter((r) => r.ref !== ref),
    }))
    setNotice(t('Wert von {name} gelöscht.', { name: s.name }))
    backToSearch()
  }

  async function removeStarter(s: Starter) {
    const ok = await confirmDialog({
      title: t('Aus dem Wettbewerb entfernen'),
      message: t('{name} mit allen Werten aus dem Wettbewerb entfernen?', { name: s.name }),
      confirmLabel: t('Entfernen'),
    })
    if (!ok) return
    const ref = s.key ?? s.id
    push({ op: 'starter_delete', starter: ref }, (l) => ({
      ...l,
      starters: l.starters.filter((x) => (x.key ?? x.id) !== ref),
      recent: l.recent.filter((r) => r.ref !== ref),
    }))
    setNotice(t('{name} entfernt.', { name: s.name }))
    backToSearch()
  }

  if (!scoring) return <p className="muted">{t('Zuerst eine Einzelwertung anlegen.')}</p>

  const open = local.starters.filter((s) => !s.values[String(scoring.id)])
  // Zuletzt erfasst über alle Geräte: Zeitpunkt vom Server, dazu eigene noch nicht
  // abgeglichene Eingaben; je Schütze nur die letzte mit seinem aktuellen Wert
  const latest = new Map<number | string, { ref: number | string; name: string; at: string }>()
  for (const s of local.starters)
    if (s.scored_at && s.values[String(scoring.id)])
      latest.set(s.key ?? s.id, { ref: s.key ?? s.id, name: s.name, at: s.scored_at })
  for (const r of local.recent) {
    const known = latest.get(r.ref)
    if (!known || Date.parse(r.at) > Date.parse(known.at))
      latest.set(r.ref, { ref: r.ref, name: r.name, at: r.at })
  }
  const recent = [...latest.values()]
    .map((r) => {
      const s = local.starters.find((x) => (x.key ?? x.id) === r.ref)
      return { ...r, value: s?.values[String(scoring.id)] ?? '' }
    })
    .filter((r) => r.value !== '')
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, 10)

  return (
    <div className={`stand${fullscreen ? ' stand-full' : ''}`}>
      <section className="stand-block" aria-label={t('Erfassen')}>
        <p className={`stand-sync ${pending ? 'stand-sync-wait' : 'stand-sync-ok'}`} role="status">
          {online ? '' : t('Kein Empfang · ')}
          {statusText}
        </p>
        {syncError && <p className="alert alert-error">{syncError}</p>}
        {closed ? (
          <p className="alert alert-info">
            {t('Der Wettbewerb ist endgültig, Eingaben sind gesperrt.')}
          </p>
        ) : (
          <form className="stand-entry" onSubmit={submit}>
            {!chosen ? (
              <>
                <label className="stand-label" htmlFor="stand-suche">
                  {t('Schütze (Name oder Startnummer)')}
                </label>
                <input
                  id="stand-suche"
                  ref={searchRef}
                  className="stand-input"
                  autoFocus
                  autoComplete="off"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value)
                    setActive(0)
                  }}
                  onKeyDown={onSearchKey}
                  aria-controls="stand-treffer"
                />
                {hits.length > 0 && (
                  <ul id="stand-treffer" className="stand-hits" role="listbox">
                    {hits.map((h, i) => (
                      <li key={hitKey(h)} role="option" aria-selected={i === active}>
                        <button
                          type="button"
                          className={`stand-hit${i === active ? ' active' : ''}`}
                          onClick={() => choose(h)}
                        >
                          {hitLabel(h, scoring)}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <>
                <p className="stand-chosen">
                  <strong>{hitName(chosen)}</strong>
                  {chosen.kind === 'member' && chosen.member.unit_name
                    ? t(' · {unit_name}', { unit_name: chosen.member.unit_name })
                    : ''}
                  {chosen.kind === 'starter' && chosen.starter.unit_name
                    ? t(' · {unit_name}', { unit_name: chosen.starter.unit_name })
                    : ''}
                  {chosen.kind === 'guest' ? t(' · neuer Gast') : ''}
                </p>
                {chosen.kind === 'guest' && (
                  <>
                    <label className="stand-label" htmlFor="stand-verein">
                      {t('Verein oder Einheit (optional)')}
                    </label>
                    <input
                      id="stand-verein"
                      className="stand-input"
                      list="stand-einheiten"
                      autoComplete="off"
                      value={guestClub}
                      onChange={(e) => setGuestClub(e.target.value)}
                    />
                    <datalist id="stand-einheiten">
                      {comp.units.map((u) => (
                        <option key={u.id} value={u.name} />
                      ))}
                    </datalist>
                  </>
                )}
                {tapping && target ? (
                  <>
                    <p className="stand-label">
                      {t('Treffer antippen')}
                      {scoring.counted_shots
                        ? ` (${scoring.counted_shots} von ${scoring.shots ?? '?'} zählen)`
                        : ''}
                    </p>
                    {target.photo && (
                      <PhotoButton
                        key={hitKey(chosen)}
                        disabled={!online}
                        autoLive={padHits.length === 0}
                        blackShare={blackShare(target)}
                        detect={(photo) => api.photo(scoring.id, photo)}
                        onResult={(sug) => {
                          setPadHits(sug.hits)
                          setPhotoNote(sug)
                        }}
                      />
                    )}
                    {target.photo && !online && (
                      <p className="muted small">
                        {t('Ohne Empfang geht die Fotoerkennung nicht; Antippen geht immer.')}
                      </p>
                    )}
                    {photoNote && (
                      <div
                        className={`pad-photo-note${photoNote.needsReview ? ' pad-photo-review' : ''}`}
                        role="status"
                      >
                        <strong>
                          {photoNote.hits.length
                            ? t('Vorschlag aus dem Foto: {n} Treffer.', {
                                n: photoNote.hits.length,
                              })
                            : t('Auf dem Foto wurden keine Treffer gefunden.')}
                        </strong>{' '}
                        {photoNote.needsReview ? t('Bitte genau prüfen') : t('Bitte prüfen')}
                        {t(', falls nötig verschieben, dann speichern.')}
                        {photoNote.note && <span className="small"> ({photoNote.note})</span>}
                        {/ineinander|überlappend/.test(photoNote.note) && (
                          <span className="small">
                            {' '}
                            <Term k="comp_hole_in_hole">{t('Loch in Loch')}</Term>
                          </span>
                        )}
                      </div>
                    )}
                    {photoNote && <Why k="comp_photo" />}
                    <TargetPad
                      target={target}
                      method={scoring.method}
                      counted={scoring.counted_shots}
                      maxShots={scoring.shots}
                      hits={padHits}
                      onChange={setPadHits}
                    />
                    <button type="button" className="link-button" onClick={() => setSumOnly(true)}>
                      {t('Nur die Summe eingeben')}
                    </button>
                  </>
                ) : (
                  <>
                    <label className="stand-label" htmlFor="stand-punkte">
                      {scoring.unit_label}
                      {scoring.counted_shots ? ` (${scoring.counted_shots} gewertete Schuss)` : ''}
                    </label>
                    <input
                      id="stand-punkte"
                      ref={pointsRef}
                      className="stand-input stand-points"
                      inputMode={scoring.decimals ? 'decimal' : 'numeric'}
                      autoComplete="off"
                      value={points}
                      onChange={(e) => setPoints(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') {
                          setChosen(null)
                          setTimeout(() => searchRef.current?.focus(), 0)
                        }
                      }}
                    />
                    {target?.photo && scoring.method !== 'frei' && online && (
                      <PhotoButton
                        blackShare={blackShare(target)}
                        detect={(photo) => api.photo(scoring.id, photo)}
                        onResult={(sug) => {
                          setPadHits(sug.hits)
                          setPhotoNote(sug)
                        }}
                      />
                    )}
                    {photoNote && (
                      <div
                        className={`pad-photo-note${photoDiffers ? ' pad-photo-review' : ''}`}
                        role="status"
                      >
                        {photoSum ? (
                          <>
                            <strong>
                              {t('Foto zum Vergleich: {x}  {unit_label} ({n} Treffer).', {
                                x: showValue(photoSum, scoring.decimals),
                                unit_label: scoring.unit_label,
                                n: photoNote.hits.length,
                              })}
                            </strong>{' '}
                            {photoDiffers &&
                              t('Weicht von der Eingabe ab, bitte die Scheibe prüfen. ')}
                            {photoNote.needsReview && t('Erkennung unsicher. ')}
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => setSumOnly(false)}
                            >
                              {t('Treffer ansehen')}
                            </button>
                          </>
                        ) : (
                          <strong>{t('Auf dem Foto wurden keine Treffer gefunden.')}</strong>
                        )}
                      </div>
                    )}
                    {photoNote && <Why k="comp_photo_sum" />}
                    {target && scoring.method !== 'frei' && (
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setSumOnly(false)}
                      >
                        {t('Treffer auf der Scheibe antippen')}
                      </button>
                    )}
                  </>
                )}
                <div className="button-row stand-buttons">
                  <button type="submit" className="button">
                    {t('Speichern')}
                  </button>
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => {
                      setChosen(null)
                      setTimeout(() => searchRef.current?.focus(), 0)
                    }}
                  >
                    {t('Abbrechen')}
                  </button>
                </div>
                {chosen.kind === 'starter' && (
                  <div className="button-row stand-buttons">
                    {!!chosen.starter.values[String(scoring.id)] && (
                      <button
                        type="button"
                        className="button button-ghost"
                        onClick={() => void clearValue(chosen.starter)}
                      >
                        {t('Wert löschen')}
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button-ghost"
                      onClick={() => void removeStarter(chosen.starter)}
                    >
                      {t('Aus dem Wettbewerb entfernen')}
                    </button>
                  </div>
                )}
              </>
            )}
          </form>
        )}
        {notice && (
          <p className="stand-notice" role="status">
            {notice}
          </p>
        )}
        <details className="stand-section" open={!fullscreen || undefined}>
          <summary>{t('Zuletzt erfasst ({n})', { n: recent.length })}</summary>
          <ul className="stand-list">
            {recent.map((r) => (
              <li key={`${r.ref}-${r.at}`}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    const s = local.starters.find((x) => (x.key ?? x.id) === r.ref)
                    if (s) choose({ kind: 'starter', starter: s })
                  }}
                >
                  {r.name}
                </button>{' '}
                <span className="push-right">{showValue(r.value, scoring.decimals)}</span>
              </li>
            ))}
          </ul>
        </details>
        <details className="stand-section">
          <summary>{t('Noch offen ({n})', { n: open.length })}</summary>
          <ul className="stand-list">
            {open.map((s) => (
              <li key={s.key ?? s.id}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => choose({ kind: 'starter', starter: s })}
                >
                  {s.name}
                </button>
                <span className="muted"> {s.unit_name || s.club}</span>
              </li>
            ))}
          </ul>
        </details>
      </section>
      {!closed && fullscreen ? (
        <StandEnd
          org={org}
          api={api}
          comp={comp}
          status={local.status ?? comp.status}
          pending={pending}
          online={online}
          onStatus={(status) => setLocal((l) => ({ ...l, status }))}
          local={local}
          setLocal={setLocal}
          push={(op) => push(op)}
        />
      ) : (
        !closed && (
          <StandFinish
            api={api}
            comp={comp}
            pending={pending}
            online={online}
            onFinished={() => setLocal((l) => ({ ...l, status: 'endgueltig' }))}
          />
        )
      )}
    </div>
  )
}

function hitKey(h: Hit) {
  if (h.kind === 'starter') return `s-${h.starter.key ?? h.starter.id}`
  if (h.kind === 'member') return `m-${h.member.membership}`
  return 'gast'
}

function hitName(h: Hit) {
  if (h.kind === 'starter') return h.starter.name
  if (h.kind === 'member') return h.member.name
  return h.name
}

function hitLabel(h: Hit, scoring: Scoring) {
  if (h.kind === 'starter') {
    const v = h.starter.values[String(scoring.id)]
    return (
      <>
        <strong>{h.starter.name}</strong>
        <span className="muted"> {h.starter.unit_name || h.starter.club}</span>
        {v ? <span className="push-right">schon {showValue(v, scoring.decimals)}</span> : null}
      </>
    )
  }
  if (h.kind === 'member')
    return (
      <>
        <strong>{h.member.name}</strong>
        <span className="muted">
          {' '}
          {h.member.unit_name}
          {h.member.birth_year ? t(' · {birth_year}', { birth_year: h.member.birth_year }) : ''}
        </span>
        <span className="push-right muted">neu</span>
      </>
    )
  return (
    <>
      {t('Neu:')} <strong>„{h.name}“</strong> {t('als Gast hinzufügen')}
    </>
  )
}

/** Spiegel / äußerster Ring für die Live-Kamera; nur bei Karten mit einem Spiegel. */
function blackShare(tm: TargetInfo): number | null {
  return tm.black_diameter && tm.rings[0] && tm.spots === 1
    ? tm.black_diameter / tm.rings[0].diameter
    : null
}
