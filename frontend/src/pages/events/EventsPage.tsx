// Termine: Kalender der aktiven Organisation, Abteilung oder des Mitgliederbereichs.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Route, Routes } from 'react-router-dom'
import { SubpageUnavailable } from '../NoticePages.tsx'
import { PERM } from '../../api/orgs.ts'
import { DEPT_PERM } from '../../api/portal.ts'
import { calendarBase, eventApi } from '../../api/events.ts'
import type { CalendarBase, EventCategory } from '../../api/events.ts'
import { CalendarView } from '../../components/calendar/CalendarView.tsx'
import { FeedPanel } from '../../components/calendar/Rsvp.tsx'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, SaveStatus, Tabs } from '../../components/ui.tsx'
import { useOrg } from '../../org/OrgContext.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { useTerms } from '../../org/terms.ts'
import { Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

export function EventsPage() {
  const { active, activeDept, activePortal } = useOrg()
  let base: CalendarBase | null = null
  let title = t('Termine')
  let subtitle = ''
  let manage = false
  let categories = false
  let isPortal = false
  if (active && (active.type === 'club' || active.type === 'federation')) {
    base = calendarBase.org(active.id)
    subtitle = active.name
    manage = active.permissions.includes(PERM.eventsManage)
    categories = manage
  } else if (activeDept) {
    base = calendarBase.dept(activeDept.id)
    title = t('Termine – {name}', { name: activeDept.name })
    subtitle = t('{label} · {club_name}', {
      label: activeDept.label,
      club_name: activeDept.club_name,
    })
    manage = activeDept.permissions.includes(DEPT_PERM.eventsManage)
  } else if (activePortal) {
    base = calendarBase.portal(activePortal.id)
    title = t('Meine Termine')
    isPortal = true
    subtitle = activePortal.club_name
  }
  if (!base) {
    return (
      <section>
        <h1>{t('Termine')}</h1>
        <p className="muted">{t('Für diesen Bereich gibt es keinen Kalender.')}</p>
      </section>
    )
  }
  const tabs = [
    { to: '/termine', label: t('Kalender') },
    ...(categories ? [{ to: '/termine/kategorien', label: t('Kategorien') }] : []),
    ...(manage ? [{ to: '/termine/weitergabe', label: t('Weitergabe') }] : []),
    ...(manage ? [{ to: '/termine/link', label: t('Öffentlicher Link') }] : []),
    ...(isPortal ? [{ to: '/termine/abo', label: t('Kalender-Abo') }] : []),
  ]
  return (
    <section>
      <div className="page-head">
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {tabs.length > 1 && <Tabs items={tabs} />}
      <Routes>
        <Route
          index
          element={
            <CalendarView
              key={base}
              base={base}
              emptyHint={
                manage ? t('Noch keine Termine. Mit „Neuer Termin“ geht es los.') : undefined
              }
            />
          }
        />
        {categories && <Route path="kategorien" element={<CategoriesPanel base={base} />} />}
        {manage && <Route path="weitergabe" element={<SharingPanel base={base} />} />}
        {manage && <Route path="link" element={<PublicationPanel base={base} />} />}
        {isPortal && <Route path="abo" element={<FeedPanel base={base} />} />}
        <Route path="*" element={<SubpageUnavailable to="/termine" label={t('Zum Kalender')} />} />
      </Routes>
    </section>
  )
}

function CategoriesPanel({ base }: { base: CalendarBase }) {
  const tm = useTerms()
  const { data, error, reload } = useLoad(() => eventApi.categories(base), [base])
  const [name, setName] = useState('')
  const [color, setColor] = useState('#2f6f4f')
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)

  async function run(action: () => Promise<unknown>, success: string) {
    setMessage(null)
    try {
      await action()
      await reload()
      setMessage({ kind: 'success', text: success })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    await run(async () => {
      await eventApi.createCategory(base, { name, color })
      setName('')
    }, t('Die Kategorie wurde angelegt.'))
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <div className="card card-wide stack">
      <p className="muted small">
        {t(
          'Kategorien gliedern den Kalender, z. B. Versammlung, Fest oder Umzug. {pl} nutzen die Kategorien {e_gen}.',
          { pl: tm.pl, e_gen: tm.e_gen },
        )}
      </p>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      <ul className="plain-list category-list">
        {data.map((c) => (
          <CategoryRow key={c.id} cat={c} base={base} run={run} />
        ))}
      </ul>
      <form onSubmit={add} className="inline-form">
        <div className="grid-3">
          <Field
            label={t('Neue Kategorie')}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
          />
          <Field
            label={t('Farbe')}
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
          />
        </div>
        <button type="submit" className="button button-primary">
          {t('Hinzufügen')}
        </button>
      </form>
    </div>
  )
}

function CategoryRow({
  cat,
  base,
  run,
}: {
  cat: EventCategory
  base: CalendarBase
  run: (action: () => Promise<unknown>, success: string) => Promise<void>
}) {
  const form = useForm({ name: cat.name, color: cat.color })
  // Name und Farbe speichern automatisch
  const auto = useAutoSave(form, (changes) => eventApi.updateCategory(base, cat.id, changes))
  return (
    <li className="category-row">
      <input
        type="color"
        value={form.values.color}
        aria-label={t('Farbe von {name}', { name: cat.name })}
        onChange={(e) => form.set('color', e.target.value)}
      />
      <input
        value={form.values.name}
        aria-label={t('Name von {name}', { name: cat.name })}
        maxLength={80}
        onChange={(e) => form.set('name', e.target.value)}
      />
      <Checkbox
        label="aktiv"
        checked={cat.is_active !== false}
        onChange={(v) =>
          void run(() => eventApi.updateCategory(base, cat.id, { is_active: v }), t('Gespeichert.'))
        }
      />
      {auto.state !== 'idle' && <SaveStatus auto={auto} />}
      <button
        type="button"
        className="button button-danger"
        onClick={async () => {
          if (
            await confirmDialog({
              title: t('Kategorie „{name}“ löschen?', { name: cat.name }),
              message: t('Termine bleiben erhalten.'),
              confirmLabel: t('Löschen'),
            })
          ) {
            void run(
              () => eventApi.removeCategory(base, cat.id),
              t('Die Kategorie wurde gelöscht.'),
            )
          }
        }}
      >
        {t('Löschen')}
      </button>
    </li>
  )
}

/** Voreinstellung, ob Termine nach oben und unten weitergegeben werden. */
export function SharingPanel({ base }: { base: CalendarBase }) {
  const { data, error, setData } = useLoad(() => eventApi.sharing(base), [base])
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const tm = useTerms()

  async function save(change: Parameters<typeof eventApi.updateSharing>[1]) {
    setBusy(true)
    setMessage(null)
    try {
      setData(await eventApi.updateSharing(base, change))
    } catch (err) {
      setMessage(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const nothing = !data.up_possible && !data.down_possible && data.units.length === 0
  return (
    <div className="card card-wide stack">
      <p className="muted small">
        {t(
          'Gilt für alle Termine außer „nur Vorstand“; die gehen nie weiter. Bei jedem Termin lässt sich die Weitergabe auch einzeln anders einstellen.',
        )}
      </p>
      {message && <Alert kind="error">{message}</Alert>}
      {nothing && <p className="muted">{t('Hier gibt es keine Einheit darüber oder darunter.')}</p>}
      {(data.up_possible || data.down_possible) && (
        <fieldset disabled={busy || !data.editable} className="stack-sm">
          <h3>{t('Eigene Termine')}</h3>
          {data.up_possible && (
            <Checkbox
              label={t('Nach oben weitergeben (im Kalender der übergeordneten Einheit)')}
              checked={data.share_up}
              onChange={(v) => void save({ share_up: v })}
            />
          )}
          {data.down_possible && (
            <Checkbox
              label={t('Nach unten weitergeben (bei den Untereinheiten und ihren Mitgliedern)')}
              checked={data.share_down}
              onChange={(v) => void save({ share_down: v })}
            />
          )}
          {!data.editable && (
            <p className="small muted">
              {t(
                'Das legt die übergeordnete Einheit fest, solange es hier keine eigene Verwaltung des Kalenders gibt.',
              )}
            </p>
          )}
        </fieldset>
      )}
      {data.units.length > 0 && (
        <div className="stack-sm">
          <h3>
            {t('Termine der')} {tm.pl}
          </h3>
          <p className="small muted">
            {t('Ohne eigene Verwaltung des Kalenders entscheidest du hier für sie.')}
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>{tm.Sg}</th>
                <th>{t('nach oben')}</th>
                <th>{t('nach unten')}</th>
              </tr>
            </thead>
            <tbody>
              {data.units.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.name}
                    {u.own_admin && <div className="small muted">{t('entscheidet selbst')}</div>}
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t('{name}: nach oben weitergeben', { name: u.name })}
                      checked={u.share_up}
                      disabled={busy || u.own_admin}
                      onChange={(e) =>
                        void save({ units: [{ id: u.id, share_up: e.target.checked }] })
                      }
                    />
                  </td>
                  <td>
                    {u.has_children ? (
                      <input
                        type="checkbox"
                        aria-label={t('{name}: nach unten weitergeben', { name: u.name })}
                        checked={u.share_down}
                        disabled={busy || u.own_admin}
                        onChange={(e) =>
                          void save({ units: [{ id: u.id, share_down: e.target.checked }] })
                        }
                      />
                    ) : (
                      <span className="muted small">–</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function PublicationPanel({ base }: { base: CalendarBase }) {
  const { data, error, setData } = useLoad(() => eventApi.publication(base), [base])
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function change(isPublic: boolean, renew = false) {
    setBusy(true)
    setMessage(null)
    try {
      setData(await eventApi.publish(base, isPublic, renew))
      if (renew)
        setMessage({ kind: 'success', text: t('Neuer Link erstellt. Der alte gilt nicht mehr.') })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setMessage({ kind: 'success', text: t('Link kopiert.') })
    } catch {
      setMessage({ kind: 'error', text: t('Kopieren ging nicht. Bitte den Link markieren.') })
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <div className="card card-wide stack">
      <p className="muted small">
        {t(
          'Über diesen Link lassen sich alle Termine mit der Sichtbarkeit „nach außen öffentlich“ ohne Anmeldung abrufen, z. B. für die eigene Webseite oder als Kalender-Abo. Er enthält nur Titel, Zeit, Ort, Beschreibung und Kategorie, nie Teilnehmer.',
        )}
      </p>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      <Checkbox
        label={t('Öffentliche Termine über einen Link abrufbar')}
        checked={data.is_public}
        disabled={busy}
        onChange={(v) => void change(v)}
      />
      <Why k="event_visibility" />
      {data.is_public && data.ics_url && data.json_url && (
        <div className="stack-sm">
          <div>
            <strong>{t('Kalender-Abo (iCal)')}</strong>
            <div className="statute-link">
              <code>{data.ics_url}</code>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => copy(data.ics_url!)}
              >
                {t('Link kopieren')}
              </button>
            </div>
          </div>
          <div>
            <strong>{t('Für Webseiten (JSON)')}</strong>
            <div className="statute-link">
              <code>{data.json_url}</code>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => copy(data.json_url!)}
              >
                {t('Link kopieren')}
              </button>
            </div>
          </div>
          <div>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={async () => {
                if (
                  await confirmDialog({
                    title: t('Neuen Link erstellen?'),
                    message: t(
                      'Webseiten und Abos mit dem alten Link bekommen dann keine Termine mehr.',
                    ),
                    confirmLabel: t('Neuen Link erstellen'),
                    danger: false,
                  })
                ) {
                  void change(true, true)
                }
              }}
            >
              {t('Neuen Link erstellen')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
