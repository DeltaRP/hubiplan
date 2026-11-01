// Kasse: Rücklagen nach § 62 AO (zuschaltbar). Eine Rücklage bindet Mittel für einen
// Zweck, bewegt aber kein Geld; Zuführungen und Auflösungen gehören zu einem
// Geschäftsjahr und sind nach dessen Abschluss gesperrt.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { euro, parseAmount, RESERVE_KINDS, reserveApi } from '../../api/finance.ts'
import type { Reserve, ReserveKind } from '../../api/finance.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Field, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function ReservesPage({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => reserveApi.list(org.id), [org.id])
  const [creating, setCreating] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{t('Rücklagen')}</h2>
        {canEdit && !creating && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setCreating(true)}
          >
            {t('Neue Rücklage')}
          </button>
        )}
      </div>
      <p className="muted small">
        {t('Eine')} <Term k="reserve">{t('Rücklage')}</Term>{' '}
        {t(
          'bindet einen Teil der Mittel für einen Zweck, etwa das nächste Fest (Projektrücklage) oder ein neues Zelt (Wiederbeschaffung). Das Geld bleibt auf den Konten. Die freie Rücklage darf höchstens ein Drittel des Überschusses aus der Vermögensverwaltung plus 10 % der übrigen zeitnah zu verwendenden Mittel betragen (§ 62 Abs. 1 Nr. 3 AO). Den Beschluss bitte im Vorstandsprotokoll festhalten.',
        )}
      </p>
      <Why k="reserves" />
      <table className="table">
        <tbody>
          <tr>
            <td>{t('Mittel auf allen Konten heute')}</td>
            <td className="num">{euro(data.funds)}</td>
          </tr>
          <tr>
            <td>{t('davon in Rücklagen gebunden')}</td>
            <td className="num">{euro(data.total)}</td>
          </tr>
          <tr>
            <td>
              <strong>{t('frei verfügbar')}</strong>
            </td>
            <td className="num">
              <strong>{euro(data.free)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <HowTo k="calc_reserve_free" />
      {Number(data.free) < 0 && (
        <Alert kind="error">
          {t('Die Rücklagen sind höher als die vorhandenen Mittel. Bitte Rücklagen auflösen.')}
        </Alert>
      )}
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      {creating && (
        <ReserveForm
          onCancel={() => setCreating(false)}
          onSaved={async (r) => {
            setCreating(false)
            setNotice({ kind: 'success', text: t('Rücklage „{name}“ angelegt.', { name: r.name }) })
            await reload()
          }}
        />
      )}
      {data.reserves.length === 0 ? (
        <p className="muted">{t('Noch keine Rücklagen.')}</p>
      ) : (
        data.reserves.map((r) => (
          <ReserveCard
            key={r.id}
            reserve={r}
            canEdit={canEdit}
            onChanged={async (text) => {
              setNotice(text ? { kind: 'success', text } : null)
              await reload()
            }}
            onError={(text) => setNotice({ kind: 'error', text })}
          />
        ))
      )}
    </div>
  )
}

function ReserveForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void
  onSaved: (r: Reserve) => Promise<void>
}) {
  const org = useActiveOrg()
  const [name, setName] = useState('')
  const [kind, setKind] = useState<ReserveKind>('purpose')
  const [purpose, setPurpose] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const needsPurpose = kind === 'purpose' || kind === 'replacement'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSaved(await reserveApi.create(org.id, { name, kind, purpose }))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="subcard" onSubmit={(e) => void submit(e)}>
      <h3>{t('Neue Rücklage')}</h3>
      <div className="grid-2">
        <Field
          label={t('Bezeichnung')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('z. B. Schützenfest 2027')}
          required
        />
        <SelectField
          label={t('Art')}
          value={kind}
          onChange={(e) => setKind(e.target.value as ReserveKind)}
        >
          {RESERVE_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </SelectField>
      </div>
      <Field
        label={needsPurpose ? t('Zweck bzw. Vorhaben') : t('Zweck bzw. Vorhaben (optional)')}
        value={purpose}
        onChange={(e) => setPurpose(e.target.value)}
        required={needsPurpose}
        hint={
          needsPurpose
            ? t('Konkret und mit Zeitraum, z. B. „Festzelt für das Schützenfest 2027“.')
            : undefined
        }
      />
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={busy}>
          {t('Anlegen')}
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          {t('Abbrechen')}
        </button>
      </div>
    </form>
  )
}

function ReserveCard({
  reserve,
  canEdit,
  onChanged,
  onError,
}: {
  reserve: Reserve
  canEdit: boolean
  onChanged: (text: string) => Promise<void>
  onError: (text: string) => void
}) {
  const org = useActiveOrg()
  const [direction, setDirection] = useState<'add' | 'release' | null>(null)
  const [date, setDate] = useState(todayIso)
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!direction) return
    setBusy(true)
    setError(null)
    try {
      const m = await reserveApi.move(org.id, reserve.id, {
        direction,
        date,
        amount: parseAmount(amount),
        note,
      })
      setDirection(null)
      setAmount('')
      setNote('')
      await onChanged(
        t('{direction_label} von {x} für „{name}“ erfasst.', {
          direction_label: m.direction_label,
          x: euro(m.amount),
          name: reserve.name,
        }),
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function act(run: () => Promise<unknown>, text: string) {
    try {
      await run()
      await onChanged(text)
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  return (
    <div className="subcard">
      <div className="card-head">
        <h3>
          {reserve.name}
          {!reserve.is_active && <span className="muted small"> (archiviert)</span>}
        </h3>
        <strong className="push-right">{euro(reserve.balance)}</strong>
      </div>
      <p className="muted small">
        {reserve.kind_label}
        {reserve.purpose ? t(' · {purpose}', { purpose: reserve.purpose }) : ''}
      </p>
      {reserve.movements.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Datum')}</th>
              <th>{t('Bewegung')}</th>
              <th className="num">{t('Betrag')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {reserve.movements.map((m) => (
              <tr key={m.id}>
                <td>{formatDate(m.date)}</td>
                <td>
                  {m.direction_label} ({m.year_label})
                  {(m.note || m.created_by_name) && (
                    <div className="muted small">
                      {[
                        m.note,
                        m.created_by_name &&
                          t('erfasst von {created_by_name}', {
                            created_by_name: m.created_by_name,
                          }),
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  )}
                </td>
                <td className="num">
                  {m.direction === 'release' ? '−' : '+'}
                  {euro(m.amount)}
                </td>
                <td className="actions">
                  {canEdit && m.open && (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() =>
                        void (async () => {
                          if (
                            await confirmDialog({
                              title: t('{direction_label} löschen?', {
                                direction_label: m.direction_label,
                              }),
                              message: t('{direction_label} von {x} am {x2} wird gelöscht.', {
                                direction_label: m.direction_label,
                                x: euro(m.amount),
                                x2: formatDate(m.date),
                              }),
                              confirmLabel: t('Löschen'),
                            })
                          )
                            await act(
                              () => reserveApi.removeMove(org.id, reserve.id, m.id),
                              t('{direction_label} gelöscht.', {
                                direction_label: m.direction_label,
                              }),
                            )
                        })()
                      }
                    >
                      {t('Löschen')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && direction === null && (
        <div className="button-row">
          {reserve.is_active && (
            <button type="button" className="link-button" onClick={() => setDirection('add')}>
              {t('Zuführen')}
            </button>
          )}
          {Number(reserve.balance) > 0 && (
            <button type="button" className="link-button" onClick={() => setDirection('release')}>
              {t('Auflösen')}
            </button>
          )}
          {reserve.movements.length === 0 ? (
            <button
              type="button"
              className="link-button"
              onClick={() =>
                void act(
                  () => reserveApi.remove(org.id, reserve.id),
                  t('Rücklage „{name}“ gelöscht.', { name: reserve.name }),
                )
              }
            >
              {t('Löschen')}
            </button>
          ) : (
            <button
              type="button"
              className="link-button"
              onClick={() =>
                void act(
                  () => reserveApi.update(org.id, reserve.id, { is_active: !reserve.is_active }),
                  reserve.is_active
                    ? t('Rücklage „{name}“ archiviert.', { name: reserve.name })
                    : t('Rücklage „{name}“ wieder aktiv.', { name: reserve.name }),
                )
              }
            >
              {reserve.is_active ? t('Archivieren') : t('Wieder aktivieren')}
            </button>
          )}
        </div>
      )}
      {direction && (
        <form onSubmit={(e) => void submit(e)}>
          <div className="grid-3">
            <Field
              label={t('Datum')}
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              required
            />
            <Field
              label={direction === 'add' ? t('Zuführung in €') : t('Auflösung in €')}
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
            <Field
              label={t('Begründung')}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={
                direction === 'add' ? t('z. B. Vorstandsbeschluss vom …') : t('z. B. Zelt gekauft')
              }
            />
          </div>
          {error && <Alert kind="error">{error}</Alert>}
          <div className="button-row">
            <button type="submit" className="button button-primary" disabled={busy}>
              {direction === 'add' ? t('Zuführen') : t('Auflösen')}
            </button>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => {
                setDirection(null)
                setError(null)
              }}
            >
              {t('Abbrechen')}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
