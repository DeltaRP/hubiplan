// Ehrungen in der Mitgliederakte: verliehene Ehrungen mit Zeitraum, verleihen,
// nachträglich bearbeiten (Ralf 31.10.), beenden und falsche Einträge löschen.
// Ehrungen mit „nur Jahr der Verleihung“ haben statt von–bis nur ein Jahr.
// Darunter (nur lesen) die Ehrungen der anderen Ebene: im Verein die des Dachverbands, im Dachverband die des Vereins.
// Der Dachverband verleiht seine eigenen Ehrungen (``federation``).
import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { memberApi, todayIso } from '../../api/members.ts'
import type { HonoraryAward } from '../../api/members.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { DeleteIcon, EditIcon, IconButton } from '../../components/icons.tsx'
import { Alert, LoadError } from '../../components/ui.tsx'

function AwardLine({ a, children }: { a: HonoraryAward; children?: ReactNode }) {
  return (
    <li>
      <strong>{a.title_name}</strong> ·{' '}
      {a.year_only ? (
        `verliehen ${a.valid_from.split('-')[0]}`
      ) : (
        <>
          {formatDate(a.valid_from)} – {a.valid_until ? formatDate(a.valid_until) : 'heute'}
        </>
      )}
      {a.fee_text && <span className="muted small"> · Beitrag: {a.fee_text}</span>}
      {a.note && <span className="muted small"> · {a.note}</span>}
      {children}
    </li>
  )
}

type TitleOption = { id: number; name: string; year_only?: boolean }

/** Zeitraum von–bis oder (bei „nur Jahr der Verleihung“) nur das Jahr. */
function AwardDates({
  yearOnly,
  from,
  until,
  setFrom,
  setUntil,
}: {
  yearOnly: boolean
  from: string
  until: string
  setFrom: (v: string) => void
  setUntil: (v: string) => void
}) {
  if (yearOnly) {
    return (
      <input
        type="number"
        aria-label="Jahr der Verleihung"
        placeholder="Jahr"
        required
        min={1800}
        max={Number(todayIso().slice(0, 4))}
        value={from.split('-')[0]}
        onChange={(e) => setFrom(e.target.value ? `${e.target.value}-01-01` : '')}
      />
    )
  }
  return (
    <>
      <input
        type="date"
        aria-label="ab"
        required
        value={from}
        onChange={(e) => setFrom(e.target.value)}
      />
      <input
        type="date"
        aria-label="bis (optional)"
        title="bis (optional)"
        value={until}
        onChange={(e) => setUntil(e.target.value)}
      />
    </>
  )
}

/** Verleihung nachträglich ändern: Ehrung, von, bis, Bemerkung. */
function AwardEdit({
  a,
  options,
  busy,
  onSave,
  onCancel,
}: {
  a: HonoraryAward
  options: TitleOption[]
  busy: boolean
  onSave: (data: Partial<HonoraryAward>) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(String(a.title))
  const [from, setFrom] = useState(a.valid_from)
  const [until, setUntil] = useState(a.valid_until ?? '')
  const [note, setNote] = useState(a.note ?? '')
  // Archivierte Ehrung bleibt wählbar, solange sie hier vergeben ist.
  const list = options.some((t) => t.id === a.title)
    ? options
    : [{ id: a.title, name: a.title_name, year_only: a.year_only }, ...options]
  const yearOnly = list.find((t) => String(t.id) === title)?.year_only ?? false
  return (
    <li>
      <form
        className="inline-edit"
        aria-label={`${a.title_name} bearbeiten`}
        onSubmit={(e) => {
          e.preventDefault()
          onSave({
            title: Number(title),
            valid_from: from,
            valid_until: yearOnly ? null : until || null,
            note,
          })
        }}
      >
        <select aria-label="Ehrung" value={title} onChange={(e) => setTitle(e.target.value)}>
          {list.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        <AwardDates
          yearOnly={yearOnly}
          from={from}
          until={until}
          setFrom={setFrom}
          setUntil={setUntil}
        />
        <input
          type="text"
          aria-label="Bemerkung"
          placeholder="Bemerkung (optional)"
          maxLength={200}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <span className="button-row">
          <button type="submit" className="button" disabled={busy}>
            Speichern
          </button>
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        </span>
      </form>
    </li>
  )
}

export function HonoraryAwards({
  orgId,
  memberId,
  awards,
  otherAwards,
  otherLabel,
  canEdit,
  federation = false,
  onChanged,
}: {
  orgId: number
  memberId: number
  awards: HonoraryAward[]
  otherAwards?: HonoraryAward[]
  otherLabel?: string
  canEdit: boolean
  federation?: boolean
  onChanged: () => Promise<void> | void
}) {
  const titles = useLoad(() => memberApi.honoraryTitles(orgId), [orgId])
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [from, setFrom] = useState(todayIso)
  const [until, setUntil] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const options = titles.data?.filter((t) => !t.is_archived) ?? []
  const addYearOnly = options.find((t) => String(t.id) === title)?.year_only ?? false

  async function run(action: () => Promise<unknown>) {
    setError(null)
    setBusy(true)
    try {
      await action()
      await onChanged()
      return true
    } catch (err) {
      setError(errorMessage(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    if (!title) return
    const ok = await run(() =>
      memberApi.addAward(
        orgId,
        memberId,
        {
          title: Number(title),
          valid_from: from,
          valid_until: addYearOnly ? null : until || null,
          note,
        },
        federation,
      ),
    )
    if (ok) {
      setTitle('')
      setUntil('')
      setNote('')
    }
  }

  async function remove(a: HonoraryAward) {
    const ok = await confirmDialog({
      title: `„${a.title_name}“ löschen?`,
      message:
        'Nur für falsche Einträge. Endet die Ehrung, besser „beenden“ wählen, dann bleibt sie im Verlauf.',
      confirmLabel: 'Löschen',
    })
    if (ok) await run(() => memberApi.deleteAward(orgId, memberId, a.id, federation))
  }

  return (
    <div className="card card-wide">
      <h2>Ehrungen</h2>
      {awards.length === 0 ? (
        <p className="muted">Keine.</p>
      ) : (
        <ul className="plain-list">
          {awards.map((a) =>
            canEdit && editing === a.id ? (
              <AwardEdit
                key={a.id}
                a={a}
                options={options}
                busy={busy}
                onCancel={() => setEditing(null)}
                onSave={(data) =>
                  void run(() =>
                    memberApi.updateAward(orgId, memberId, a.id, data, federation),
                  ).then((ok) => ok && setEditing(null))
                }
              />
            ) : (
              <AwardLine key={a.id} a={a}>
                {canEdit && (
                  <span className="inline-actions">
                    <IconButton
                      label={`${a.title_name} bearbeiten`}
                      icon={<EditIcon />}
                      disabled={busy}
                      onClick={() => setEditing(a.id)}
                    />
                    {!a.year_only && (!a.valid_until || a.valid_until > todayIso()) && (
                      <button
                        type="button"
                        className="link-button"
                        disabled={busy}
                        onClick={() =>
                          void run(() =>
                            memberApi.updateAward(
                              orgId,
                              memberId,
                              a.id,
                              { valid_until: todayIso() },
                              federation,
                            ),
                          )
                        }
                      >
                        beenden
                      </button>
                    )}
                    <IconButton
                      label={`${a.title_name} löschen`}
                      icon={<DeleteIcon />}
                      danger
                      disabled={busy}
                      onClick={() => void remove(a)}
                    />
                  </span>
                )}
              </AwardLine>
            ),
          )}
        </ul>
      )}
      {otherAwards && otherAwards.length > 0 && (
        <>
          <h3>{otherLabel ?? 'Weitere Ehrungen'}</h3>
          <ul className="plain-list">
            {otherAwards.map((a) => (
              <AwardLine key={a.id} a={a} />
            ))}
          </ul>
        </>
      )}
      {canEdit &&
        (options.length > 0 ? (
          <form className="inline-add" onSubmit={add} aria-label="Ehrung verleihen">
            <select
              aria-label="Ehrung verleihen"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            >
              <option value="">Ehrung verleihen …</option>
              {options.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <AwardDates
              yearOnly={addYearOnly}
              from={from}
              until={until}
              setFrom={setFrom}
              setUntil={setUntil}
            />
            <input
              type="text"
              aria-label="Bemerkung"
              placeholder="Bemerkung (optional)"
              maxLength={200}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button type="submit" className="button button-ghost" disabled={busy || !title}>
              Verleihen
            </button>
          </form>
        ) : titles.error ? (
          <LoadError
            message={`Die Ehrungen konnten nicht geladen werden. ${titles.error}`}
            onRetry={() => void titles.reload()}
          />
        ) : titles.data ? (
          <p className="muted small">
            Noch keine Ehrungen angelegt (Mitglieder › Einrichtung › Ehrungen).
          </p>
        ) : (
          <p className="muted small">Ehrungen werden geladen …</p>
        ))}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
