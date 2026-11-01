// Formular zum Anlegen und Bearbeiten eines Termins.
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { REPEAT_LABELS, VISIBILITY_LABELS, eventApi } from '../../api/events.ts'
import type {
  CalendarBase,
  EventCategory,
  EventDetail,
  EventInput,
  Repeat,
  Visibility,
} from '../../api/events.ts'
import { useAutoSave, useForm } from '../forms.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../ui.tsx'
import { addDays, berlin, toApi } from './time.ts'
import { confirmDialog } from '../dialog.ts'
import { Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

/** Prüft vor dem Schließen des Dialogs, ob Eingaben verloren gingen; false = offen lassen. */
export type CloseGuard = () => Promise<boolean>

interface Values {
  title: string
  description: string
  location: string
  address: string
  category: string
  all_day: boolean
  start_date: string
  start_time: string
  end_date: string
  end_time: string
  visibility: Visibility
  repeat: Repeat
  repeat_interval: string
  repeat_until: string
  is_cancelled: boolean
  cancel_note: string
  rsvp_enabled: boolean
  rsvp_deadline_date: string
  rsvp_deadline_time: string
  rsvp_capacity: string
  rsvp_guests: boolean
  remind: boolean
  remind_days: string
  notify: boolean
  share_up: Share
  share_down: Share
}

/** Weitergabe am Termin: '' = wie voreingestellt */
type Share = '' | 'yes' | 'no'
const toShare = (v: boolean | null | undefined): Share => (v == null ? '' : v ? 'yes' : 'no')
const fromShare = (v: Share): boolean | null => (v === '' ? null : v === 'yes')

function initial(event: EventDetail | null, date: string): Values {
  if (!event) {
    return {
      title: '',
      description: '',
      location: '',
      address: '',
      category: '',
      all_day: false,
      start_date: date,
      start_time: '19:00',
      end_date: date,
      end_time: '21:00',
      visibility: 'members',
      repeat: 'none',
      repeat_interval: '1',
      repeat_until: '',
      is_cancelled: false,
      cancel_note: '',
      rsvp_enabled: false,
      rsvp_deadline_date: '',
      rsvp_deadline_time: '23:59',
      rsvp_capacity: '',
      rsvp_guests: false,
      remind: false,
      remind_days: '2',
      notify: false,
      share_up: '',
      share_down: '',
    }
  }
  const deadline = event.rsvp.deadline ? berlin(event.rsvp.deadline) : null
  const s = berlin(event.starts_at)
  const e = berlin(event.ends_at)
  return {
    title: event.title,
    description: event.description,
    location: event.location,
    address: event.address,
    category: event.category ? String(event.category.id) : '',
    all_day: event.all_day,
    start_date: s.date,
    start_time: s.time,
    end_date: e.date,
    end_time: e.time,
    visibility: event.visibility,
    repeat: event.repeat,
    repeat_interval: String(event.repeat_interval),
    repeat_until: event.repeat_until ?? '',
    is_cancelled: event.is_cancelled,
    cancel_note: event.cancel_note,
    rsvp_enabled: event.rsvp.enabled,
    rsvp_deadline_date: deadline?.date ?? '',
    rsvp_deadline_time: deadline?.time ?? '23:59',
    rsvp_capacity: event.rsvp.capacity ? String(event.rsvp.capacity) : '',
    rsvp_guests: event.rsvp.guests_allowed,
    remind: !!event.remind_days,
    remind_days: event.remind_days ? String(event.remind_days) : '2',
    notify: false,
    share_up: toShare(event.share_up),
    share_down: toShare(event.share_down),
  }
}

function toInput(v: Values): EventInput {
  return {
    title: v.title,
    description: v.description,
    location: v.location,
    address: v.address,
    category: v.category ? Number(v.category) : null,
    all_day: v.all_day,
    starts_at: toApi(v.start_date, v.all_day ? '00:00' : v.start_time),
    ends_at: toApi(v.end_date || v.start_date, v.all_day ? '00:00' : v.end_time),
    visibility: v.visibility,
    repeat: v.repeat,
    repeat_interval: Number(v.repeat_interval) || 1,
    repeat_until: v.repeat !== 'none' && v.repeat_until ? v.repeat_until : null,
    is_cancelled: v.is_cancelled,
    cancel_note: v.is_cancelled ? v.cancel_note : '',
    rsvp_enabled: v.rsvp_enabled,
    rsvp_deadline:
      v.rsvp_enabled && v.rsvp_deadline_date
        ? toApi(v.rsvp_deadline_date, v.rsvp_deadline_time || '23:59')
        : null,
    rsvp_capacity: v.rsvp_enabled && v.rsvp_capacity ? Number(v.rsvp_capacity) : null,
    rsvp_guests: v.rsvp_enabled && v.rsvp_guests,
    remind_days: v.repeat === 'none' && v.remind ? Number(v.remind_days) || 1 : null,
    share_up: fromShare(v.share_up),
    share_down: fromShare(v.share_down),
    notify: v.notify,
  }
}

const INTERVAL_UNIT: Record<Repeat, string> = {
  none: '',
  weekly: t('Wochen'),
  monthly: t('Monate'),
  yearly: t('Jahre'),
}

export function EventForm({
  base,
  event,
  date,
  categories,
  rsvpAllowed = false,
  onSaved,
  onCancel,
  guardRef,
}: {
  base: CalendarBase
  event: EventDetail | null
  date: string
  categories: EventCategory[]
  /** Zu- und Absagen und E-Mails gibt es bei Terminen eines Vereins oder Zugs */
  rsvpAllowed?: boolean
  onSaved: (event: EventDetail) => void
  onCancel: () => void
  /** Der Dialog fragt hierüber vor dem Schließen nach (Esc, Hintergrund, „Schließen“). */
  guardRef?: { current: CloseGuard | null }
}) {
  const form = useForm<Values>(initial(event, date))
  const pristine = useRef(JSON.stringify(form.values))
  const { values: v, set, errors } = form
  const [touchedEnd, setTouchedEnd] = useState(!!event)
  const choosable = categories.filter((c) => c.is_active !== false || String(c.id) === v.category)

  function setStartDate(value: string) {
    set('start_date', value)
    // Ende mitziehen, solange es nicht bewusst geändert wurde
    if (!touchedEnd || v.end_date < value) set('end_date', value)
  }

  // Bestehende Termine speichern automatisch (ohne Mail), neue erst mit „Termin anlegen“
  const lastSaved = useRef<EventDetail | null>(null)
  const auto = useAutoSave(
    form,
    (_changes, values) => eventApi.update(base, event!.id, { ...toInput(values), notify: false }),
    {
      enabled: !!event,
      onSaved: (saved) => {
        lastSaved.current = saved as EventDetail
      },
    },
  )
  const [mailBusy, setMailBusy] = useState(false)

  // Versehentliches Schließen darf keine Eingaben verwerfen
  const valuesRef = useRef(v)
  useEffect(() => {
    valuesRef.current = v
  })
  useEffect(() => {
    if (!guardRef) return
    guardRef.current = async () => {
      if (event) {
        if (await auto.flush()) return true
        return confirmDialog({
          title: t('Änderungen nicht gespeichert'),
          message: t(
            'Die letzten Änderungen am Termin konnten nicht gespeichert werden. Trotzdem schließen und sie verwerfen?',
          ),
          confirmLabel: t('Verwerfen und schließen'),
          cancelLabel: t('Weiter bearbeiten'),
        })
      }
      if (JSON.stringify(valuesRef.current) === pristine.current) return true
      return confirmDialog({
        title: t('Entwurf verwerfen?'),
        message: t('Deine Eingaben für den neuen Termin gehen dann verloren.'),
        confirmLabel: t('Verwerfen'),
        cancelLabel: t('Weiter bearbeiten'),
      })
    }
    return () => {
      guardRef.current = null
    }
  }, [guardRef, event, auto])

  async function sendMail() {
    if (!event) return
    setMailBusy(true)
    if (!(await auto.flush())) {
      form.setMessage({
        kind: 'error',
        text: t('Vor dem Versenden müssen alle Änderungen gespeichert sein.'),
      })
      setMailBusy(false)
      return
    }
    await form.submit(
      () => eventApi.notify(base, event.id, v.is_cancelled ? 'cancel' : 'change'),
      t('Die E-Mails werden verschickt.'),
    )
    setMailBusy(false)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (event) {
      if (!(await auto.flush())) return
      onSaved(lastSaved.current ?? event)
      return
    }
    const saved = await form.submit(
      () => eventApi.create(base, toInput(v)),
      t('Der Termin wurde angelegt.'),
    )
    if (saved) onSaved(saved as EventDetail)
  }

  return (
    <form onSubmit={submit} className="stack event-form" aria-label={t('Termin')}>
      {event && <SaveStatus auto={auto} />}
      {form.message && (event || form.message.kind === 'error') && (
        <Alert kind={form.message.kind}>{form.message.text}</Alert>
      )}
      <Field
        label={t('Titel')}
        value={v.title}
        required
        maxLength={200}
        error={errors.title}
        onChange={(e) => set('title', e.target.value)}
      />
      <div className="grid-2">
        <SelectField
          label={t('Kategorie')}
          value={v.category}
          error={errors.category}
          onChange={(e) => set('category', e.target.value)}
        >
          <option value="">{t('ohne Kategorie')}</option>
          {choosable.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label={t('Wer sieht den Termin?')}
          value={v.visibility}
          error={errors.visibility}
          hint={
            v.visibility === 'public'
              ? t('Auch ohne Anmeldung, z. B. auf der Webseite.')
              : v.visibility === 'board'
                ? t('Nur Vorstandsrollen dieser Ebene.')
                : t('Alle Mitglieder dieser Ebene.')
          }
          onChange={(e) => set('visibility', e.target.value as Visibility)}
        >
          {(Object.keys(VISIBILITY_LABELS) as Visibility[]).map((k) => (
            <option key={k} value={k}>
              {VISIBILITY_LABELS[k]}
            </option>
          ))}
        </SelectField>
      </div>
      <Why k="event_visibility" />
      {v.visibility !== 'board' && (
        <div className="grid-2">
          {(['up', 'down'] as const).map((dir) => {
            const key = dir === 'up' ? 'share_up' : 'share_down'
            const preset = event?.share_defaults?.[dir]
            return (
              <SelectField
                key={dir}
                label={dir === 'up' ? t('Nach oben weitergeben') : t('Nach unten weitergeben')}
                value={v[key]}
                hint={
                  dir === 'up'
                    ? t('Erscheint im Kalender der übergeordneten Einheit.')
                    : t('Erscheint bei den Untereinheiten und ihren Mitgliedern.')
                }
                onChange={(e) => set(key, e.target.value as Share)}
              >
                <option value="">
                  {preset === undefined
                    ? t('wie voreingestellt')
                    : t('wie voreingestellt ({x})', { x: preset ? 'ja' : 'nein' })}
                </option>
                <option value="yes">ja</option>
                <option value="no">nein</option>
              </SelectField>
            )
          })}
        </div>
      )}
      <Checkbox label={t('ganztägig')} checked={v.all_day} onChange={(x) => set('all_day', x)} />
      <div className="grid-2">
        <Field
          label={v.all_day ? t('Erster Tag') : t('Beginn (Datum)')}
          type="date"
          required
          value={v.start_date}
          error={errors.starts_at}
          onChange={(e) => setStartDate(e.target.value)}
        />
        {!v.all_day && (
          <Field
            label={t('Beginn (Uhrzeit)')}
            type="time"
            required
            value={v.start_time}
            onChange={(e) => set('start_time', e.target.value)}
          />
        )}
        <Field
          label={v.all_day ? t('Letzter Tag') : t('Ende (Datum)')}
          type="date"
          required
          min={v.start_date}
          value={v.end_date}
          error={errors.ends_at}
          onChange={(e) => {
            setTouchedEnd(true)
            set('end_date', e.target.value)
          }}
        />
        {!v.all_day && (
          <Field
            label={t('Ende (Uhrzeit)')}
            type="time"
            required
            value={v.end_time}
            onChange={(e) => set('end_time', e.target.value)}
          />
        )}
      </div>
      <div className="grid-2">
        <Field
          label={t('Ort')}
          value={v.location}
          maxLength={200}
          placeholder={t('z. B. Vereinsheim')}
          error={errors.location}
          onChange={(e) => set('location', e.target.value)}
        />
        <Field
          label={t('Anschrift')}
          value={v.address}
          maxLength={300}
          error={errors.address}
          onChange={(e) => set('address', e.target.value)}
        />
      </div>
      <label className="field">
        <span>{t('Beschreibung')}</span>
        <textarea
          rows={4}
          value={v.description}
          maxLength={5000}
          onChange={(e) => set('description', e.target.value)}
        />
      </label>
      <div className="grid-3">
        <SelectField
          label={t('Wiederholung')}
          value={v.repeat}
          error={errors.repeat}
          onChange={(e) => set('repeat', e.target.value as Repeat)}
        >
          {(Object.keys(REPEAT_LABELS) as Repeat[]).map((k) => (
            <option key={k} value={k}>
              {REPEAT_LABELS[k]}
            </option>
          ))}
        </SelectField>
        {v.repeat !== 'none' && (
          <>
            <Field
              label={t('alle … {x}', { x: INTERVAL_UNIT[v.repeat] })}
              type="number"
              min={1}
              max={52}
              value={v.repeat_interval}
              error={errors.repeat_interval}
              onChange={(e) => set('repeat_interval', e.target.value)}
            />
            <Field
              label={t('wiederholen bis (optional)')}
              type="date"
              min={addDays(v.start_date, 1)}
              value={v.repeat_until}
              error={errors.repeat_until}
              onChange={(e) => set('repeat_until', e.target.value)}
            />
          </>
        )}
      </div>
      {rsvpAllowed && v.repeat === 'none' && v.visibility !== 'board' && (
        <fieldset className="subcard stack-sm">
          <legend>{t('Zu- und Absagen')}</legend>
          <Checkbox
            label={t('Mitglieder können zu- oder absagen')}
            checked={v.rsvp_enabled}
            onChange={(x) => set('rsvp_enabled', x)}
          />
          {errors.rsvp_enabled && <Alert kind="error">{errors.rsvp_enabled}</Alert>}
          {v.rsvp_enabled && (
            <>
              <div className="grid-3">
                <Field
                  label={t('Anmeldeschluss (optional)')}
                  type="date"
                  max={v.start_date}
                  value={v.rsvp_deadline_date}
                  error={errors.rsvp_deadline}
                  onChange={(e) => set('rsvp_deadline_date', e.target.value)}
                />
                {v.rsvp_deadline_date && (
                  <Field
                    label={t('Uhrzeit')}
                    type="time"
                    value={v.rsvp_deadline_time}
                    onChange={(e) => set('rsvp_deadline_time', e.target.value)}
                  />
                )}
                <Field
                  label={t('Höchstzahl Personen (optional)')}
                  type="number"
                  min={1}
                  value={v.rsvp_capacity}
                  error={errors.rsvp_capacity}
                  onChange={(e) => set('rsvp_capacity', e.target.value)}
                />
              </div>
              <Checkbox
                label={t('Begleitpersonen erlaubt')}
                checked={v.rsvp_guests}
                onChange={(x) => set('rsvp_guests', x)}
              />
            </>
          )}
        </fieldset>
      )}
      {rsvpAllowed && v.visibility !== 'board' && (
        <fieldset className="subcard stack-sm">
          <legend>{t('E-Mail')}</legend>
          {v.repeat === 'none' && (
            <div className="grid-3">
              <Checkbox
                label={t('Erinnerung per E-Mail')}
                checked={v.remind}
                onChange={(x) => set('remind', x)}
              />
              {v.remind && (
                <Field
                  label={t('Tage vorher')}
                  type="number"
                  min={1}
                  max={60}
                  value={v.remind_days}
                  error={errors.remind_days}
                  onChange={(e) => set('remind_days', e.target.value)}
                />
              )}
            </div>
          )}
          {v.remind && v.rsvp_enabled && v.repeat === 'none' && (
            <p className="muted small">{t('Die Erinnerung geht an alle, die zugesagt haben.')}</p>
          )}
          {event ? (
            <div>
              <button
                type="button"
                className="button button-ghost"
                disabled={mailBusy}
                onClick={() => void sendMail()}
              >
                {v.is_cancelled
                  ? t('Absage per E-Mail an Eingeladene schicken')
                  : t('Änderung per E-Mail an Eingeladene schicken')}
              </button>
              <p className="muted small">
                {t(
                  'Änderungen werden ohne E-Mail gespeichert. Hat sich Zeit oder Ort geändert oder ist der Termin abgesagt, informierst du die Eingeladenen hiermit.',
                )}
              </p>
            </div>
          ) : (
            <Checkbox
              label={t('Einladung per E-Mail an alle Eingeladenen schicken')}
              checked={v.notify}
              onChange={(x) => set('notify', x)}
            />
          )}
        </fieldset>
      )}
      {event && (
        <>
          <Checkbox
            label={event.repeat !== 'none' ? t('ganze Serie abgesagt') : t('Termin abgesagt')}
            checked={v.is_cancelled}
            onChange={(x) => set('is_cancelled', x)}
          />
          {v.is_cancelled && (
            <Field
              label={t('Hinweis zur Absage')}
              value={v.cancel_note}
              maxLength={300}
              onChange={(e) => set('cancel_note', e.target.value)}
            />
          )}
        </>
      )}
      <div className="button-row">
        <button
          type="submit"
          className={event ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy}
        >
          {event ? t('Schließen') : t('Termin anlegen')}
        </button>
        {!event && (
          <button
            type="button"
            className="button button-ghost"
            onClick={async () => {
              // Abbrechen fragt wie Esc und Schließen (UX-Audit 31.10. W01)
              const ok = guardRef?.current ? await guardRef.current() : true
              if (ok) onCancel()
            }}
          >
            {t('Abbrechen')}
          </button>
        )}
      </div>
    </form>
  )
}
