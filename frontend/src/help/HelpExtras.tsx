// Hilfe, Teile mit Bezug zur Einheit und zur Person (konzepte/hilfe-funktion.md, H4–H6):
// „Warum sehe ich das nicht?“, Ansprechpartner, Hinweise des Vereins, „Für dich“ mit
// abhakbaren ersten Schritten und „Zeig es mir“.
import { useState } from 'react'
import type { ReactNode } from 'react'
import { helpApi } from '../api/help.ts'
import type { HelpContact } from '../api/help.ts'
import { errorMessage, useLoad } from '../components/forms.ts'
import { Alert, Field } from '../components/ui.tsx'
import { t } from '../i18n/index.ts'
import { TextArea } from '../pages/settings/TextArea.tsx'
import { AREAS } from './content.ts'
import type { HelpEntry } from './content.ts'
import { FIRST_STEPS, highlight, labelsIn } from './extras.ts'
import { useHelp } from './HelpContext.tsx'

const quote = (s: string) => t('„{x}“', { x: s })

/** Beschriftungen der Rechte (aus der Einheit, sonst der Schlüssel). */
function rightLabels(rights: string[], labels: Record<string, string> | undefined): string {
  return rights.map((r) => quote(labels?.[r] ?? r)).join(t(' oder '))
}

/** „Warum sehe ich das nicht?“: welches Recht fehlt und wer es vergeben kann. */
export function RightsHint({ rights }: { rights: string[] }) {
  const help = useHelp()
  if (!rights.length) return null
  const roles = help?.org?.admin_roles ?? []
  return (
    <span className="help-rights-hint">
      {t('Dafür brauchst du das Recht {rights}.', {
        rights: rightLabels(rights, help?.org?.rights),
      })}{' '}
      {roles.length > 0
        ? t('Vergeben kann es, wer die Rolle {roles} hat.', {
            roles: roles.map(quote).join(t(' oder ')),
          })
        : t('Vergeben kann es, wer Rollen verwalten darf.')}
    </span>
  )
}

/** Eine Anleitung, die wegen fehlender Rechte nicht offen ist (ausgegraut). */
export function BlockedGuide({ entry }: { entry: HelpEntry }) {
  const help = useHelp()
  return (
    <li className="help-blocked">
      <span className="help-blocked-title">{entry.title}</span>{' '}
      <small className="muted">
        <RightsHint rights={help?.missing(entry) ?? []} />
      </small>
    </li>
  )
}

/** „Wer hilft bei uns?“: Ansprechpartner der Einheit, sonst Rollennamen. */
export function HelpContacts({ compact = false }: { compact?: boolean }) {
  const help = useHelp()
  const org = help?.org
  if (!org) return null
  const Heading = compact ? 'h3' : 'h2'
  return (
    <section className={compact ? undefined : 'help-area'} aria-labelledby="hilfe-wer-hilft">
      <Heading id="hilfe-wer-hilft">{t('Wer hilft bei uns?')}</Heading>
      {org.contacts.length > 0 ? (
        <>
          <ul className="help-list">
            {org.contacts.map((c, i) => (
              <li key={i}>
                <strong>{c.name}</strong>
                {c.hint && <> ({c.hint})</>}
                {c.email && (
                  <>
                    {' · '}
                    <a href={`mailto:${c.email}`}>{c.email}</a>
                  </>
                )}
              </li>
            ))}
          </ul>
          {org.contacts_from && !org.contacts_from.own && (
            <p className="muted small">
              {t('Angegeben von {unit}.', { unit: org.contacts_from.name })}
            </p>
          )}
        </>
      ) : org.admin_roles.length > 0 ? (
        <p>
          {t('Bei Fragen zu HUBIplan hilft dir jemand mit der Rolle {roles}.', {
            roles: org.admin_roles.map(quote).join(t(' oder ')),
          })}
        </p>
      ) : (
        <p className="muted">{t('Hier sind noch keine Ansprechpartner eingetragen.')}</p>
      )}
      {org.can_edit && !compact && (
        <p className="muted small">
          {t('Ansprechpartner legst du unter Einstellungen › Organisation fest.')}
        </p>
      )}
    </section>
  )
}

const EMPTY: HelpContact = { name: '', hint: '', email: '' }

/** Einstellungen › Organisation: Ansprechpartner für Fragen zu HUBIplan festlegen. */
export function HelpContactsCard({ orgId, editable }: { orgId: number; editable: boolean }) {
  const { data, error } = useLoad(() => helpApi.org(orgId), [orgId])
  return (
    <div className="card card-wide">
      <h2>{t('Ansprechpartner für Fragen zu HUBIplan')}</h2>
      <p className="muted small">
        {t(
          'Erscheinen in der Hilfe unter „Wer hilft bei uns?“ für alle mit einer Rolle hier und in den Untereinheiten, die keine eigenen eintragen. Ohne Eintrag nennt die Hilfe nur die Rollen, die Rechte vergeben dürfen.',
        )}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">{t('Lädt …')}</p>}
      {data && (
        <ContactsEditor key={orgId} orgId={orgId} initial={data.own_contacts} editable={editable} />
      )}
    </div>
  )
}

function ContactsEditor({
  orgId,
  initial,
  editable,
}: {
  orgId: number
  initial: HelpContact[]
  editable: boolean
}) {
  const [rows, setRows] = useState<HelpContact[]>(initial)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const help = useHelp()

  const update = (i: number, field: keyof HelpContact, value: string) =>
    setRows((r) => r.map((c, j) => (j === i ? { ...c, [field]: value } : c)))

  async function save() {
    setBusy(true)
    setMessage(null)
    try {
      const data = await helpApi.saveContacts(
        orgId,
        rows.filter((c) => c.name.trim()),
      )
      setRows(data.own_contacts)
      if (help?.orgId === orgId) help.setOrg(data)
      setMessage({ kind: 'success', text: t('Gespeichert.') })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {rows.length === 0 && <p className="muted">{t('Noch niemand eingetragen.')}</p>}
      {rows.map((c, i) => (
        <fieldset key={i} className="help-contact-row" disabled={!editable || busy}>
          <legend>{t('Ansprechpartner {n}', { n: i + 1 })}</legend>
          <div className="grid-2">
            <Field
              label={t('Name')}
              value={c.name}
              maxLength={100}
              onChange={(e) => update(i, 'name', e.target.value)}
            />
            <Field
              label={t('Wofür (z. B. Mitglieder, Kasse)')}
              value={c.hint}
              maxLength={200}
              onChange={(e) => update(i, 'hint', e.target.value)}
            />
            <Field
              label={t('E-Mail (freiwillig)')}
              type="email"
              value={c.email}
              maxLength={254}
              onChange={(e) => update(i, 'email', e.target.value)}
            />
          </div>
          {editable && (
            <button
              type="button"
              className="button button-ghost"
              onClick={() => setRows(rows.filter((_, j) => j !== i))}
            >
              {t('Entfernen')}
            </button>
          )}
        </fieldset>
      ))}
      {editable && (
        <div className="actions">
          {rows.length < 10 && (
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => setRows([...rows, { ...EMPTY }])}
            >
              {t('Ansprechpartner hinzufügen')}
            </button>
          )}
          <button type="button" className="button" disabled={busy} onClick={save}>
            {t('Speichern')}
          </button>
        </div>
      )}
    </>
  )
}

/** Hinweise des Vereins zu einer Anleitung; die eigene Einheit kann ihren ändern. */
export function GuideNotes({ entry, editable = false }: { entry: HelpEntry; editable?: boolean }) {
  const help = useHelp()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const org = help?.org
  if (!org || entry.kind !== 'guide') return null
  const notes = org.notes[entry.key] ?? []
  const own = notes.find((n) => n.own)
  const canEdit = editable && org.can_edit && help.orgId !== null && !help.previewRole

  async function save() {
    if (!help || help.orgId === null) return
    setBusy(true)
    setError(null)
    try {
      help.setOrg(await helpApi.saveNote(help.orgId, entry.key, text))
      setEditing(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!notes.length && !canEdit) return null
  return (
    <section className="help-notes" aria-labelledby={`hinweise-${entry.slug}`}>
      <h2 id={`hinweise-${entry.slug}`}>{t('Hinweise bei uns')}</h2>
      {notes.map((n, i) => (
        <div key={i} className="help-note">
          <p className="help-note-text">{n.text}</p>
          <p className="muted small">{t('Hinweis von {unit}', { unit: n.from })}</p>
        </div>
      ))}
      {canEdit && !editing && (
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setText(own?.text ?? '')
            setEditing(true)
          }}
        >
          {own ? t('Eigenen Hinweis ändern') : t('Hinweis für unsere Einheit ergänzen')}
        </button>
      )}
      {canEdit && editing && (
        <div>
          {error && <Alert kind="error">{error}</Alert>}
          <TextArea
            label={t('Hinweis zu dieser Anleitung')}
            hint={t('Höchstens 500 Zeichen. Leer speichern entfernt den Hinweis.')}
            value={text}
            onChange={(v) => setText(v.slice(0, 500))}
          />
          <div className="actions">
            <button type="button" className="button" disabled={busy} onClick={save}>
              {t('Speichern')}
            </button>
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              {t('Abbrechen')}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

/** „Für dich“: erste Schritte nach den eigenen Rechten, zum Abhaken. */
export function ForYou({
  areaLabel,
  linkTo,
}: {
  areaLabel: (area: string) => string
  linkTo: (entry: HelpEntry) => ReactNode
}) {
  const help = useHelp()
  if (!help?.entries) return null
  const byKey = new Map(help.entries.filter(help.visible).map((e) => [e.key, e]))
  const steps = FIRST_STEPS.map((k) => byKey.get(k)).filter((e): e is HelpEntry => !!e)
  if (!steps.length) return null
  const groups = AREAS.map((a) => ({ area: a, items: steps.filter((s) => s.area === a) })).filter(
    (g) => g.items.length > 0,
  )
  const done = help.done
  const doneCount = done ? steps.filter((s) => done.has(s.key)).length : 0
  const locked = !!help.previewRole
  return (
    <section className="help-area help-for-you" aria-labelledby="hilfe-fuer-dich">
      <h2 id="hilfe-fuer-dich">{t('Für dich: erste Schritte')}</h2>
      {help.previewRole ? (
        <p className="muted small">
          {t(
            'Du siehst die Hilfe, wie sie Personen mit der Rolle „{role}“ sehen. Abhaken geht hier nicht.',
            {
              role: help.previewRole,
            },
          )}
        </p>
      ) : (
        <p className="muted small" role="status">
          {t('{done} von {all} erledigt. Die Haken siehst nur du.', {
            done: doneCount,
            all: steps.length,
          })}
        </p>
      )}
      {groups.map((g) => (
        <div key={g.area} className="help-step-group">
          <h3>{areaLabel(g.area)}</h3>
          <ul className="help-steps">
            {g.items.map((s) => {
              const checked = !!done?.has(s.key)
              return (
                <li key={s.key} className={checked ? 'help-step-done' : undefined}>
                  <input
                    type="checkbox"
                    id={`schritt-${s.slug}`}
                    checked={checked}
                    disabled={locked || !done}
                    aria-label={t('{title} erledigt', { title: s.title })}
                    onChange={() => help.toggleDone(s.key)}
                  />{' '}
                  {linkTo(s)}
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </section>
  )
}

export function ShowMe({ entry }: { entry: HelpEntry }) {
  const [result, setResult] = useState<boolean | null>(null)
  const labels = labelsIn(entry.body)
  if (!labels.length) return null
  return (
    <p className="help-show-me">
      <button
        type="button"
        className="button button-ghost"
        onClick={() => setResult(highlight(labels))}
      >
        {t('Zeig es mir')}
      </button>{' '}
      {result !== null && (
        <span className="muted small" role="status">
          {result
            ? t('Hervorgehoben.')
            : t('Auf dieser Seite nicht zu sehen. Öffne zuerst die Seite aus Schritt 1.')}
        </span>
      )}
    </p>
  )
}
