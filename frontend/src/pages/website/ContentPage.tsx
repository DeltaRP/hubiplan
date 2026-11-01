// Webseite › Texte: Begrüßung, Textseiten (z. B. Chronik) und Texte der
// Untereinheiten. Änderungen sind erst nach „Veröffentlichen“ sichtbar; frühere
// Fassungen lassen sich zurückholen. Bilder verwaltet Webseite › Bilder (images.tsx).
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { contentApi } from '../../api/website.ts'
import type {
  LinkTarget,
  WebsiteImage,
  WebsiteText,
  WebsiteTextSummary,
} from '../../api/website.ts'
import { confirmDialog } from '../../components/dialog.ts'
import {
  errorMessage,
  formatDateTime,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { TextEditor } from '../../components/texteditor/TextEditor.tsx'
import { ImageChoice, ImagePicker } from './images.tsx'
import { imageLabel } from './imageTools.ts'
import type { Unit } from './images.tsx'

function status(t: WebsiteTextSummary): string {
  if (!t.is_published) return 'Entwurf, nicht veröffentlicht'
  return t.has_changes ? 'veröffentlicht, Entwurf mit Änderungen' : 'veröffentlicht'
}

export function ContentPage() {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => contentApi.texts(org.id), [org.id])
  const [open, setOpen] = useState<number | null>(null)
  const [adding, setAdding] = useState<'page' | 'unit' | null>(null)
  // ?einheit=<id> (Link aus der Untereinheit): deren Text öffnen oder anlegen
  const [params] = useSearchParams()
  const wantedUnit = Number(params.get('einheit')) || null
  // ?text=<id> (Link aus „Bild bearbeiten › Verwendet in“): diesen Text öffnen
  const wantedText = Number(params.get('text')) || null
  const [handled, setHandled] = useState('')
  const wanted = `${wantedUnit ?? ''}/${wantedText ?? ''}`
  if (data && (wantedUnit || wantedText) && handled !== wanted) {
    setHandled(wanted)
    if (wantedText && data.texts.some((t) => t.id === wantedText)) setOpen(wantedText)
    else if (wantedUnit) {
      const text = data.texts.find((t) => t.kind === 'unit' && t.department === wantedUnit)
      if (text) setOpen(text.id)
      else if (data.units.some((u) => u.id === wantedUnit)) setAdding('unit')
    }
  }

  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>

  const groups: { title: string; kind: string }[] = [
    { title: 'Startseite', kind: 'greeting' },
    { title: 'Textseiten', kind: 'page' },
    { title: 'Texte der Untereinheiten', kind: 'unit' },
  ]

  return (
    <>
      <div className="card card-wide">
        <h2>Texte</h2>
        <p className="muted small">
          Texte gestaltest du mit den Knöpfen über dem Text: Überschriften, fett, kursiv, Listen,
          Links und Bilder. Wer lieber Markdown schreibt, schaltet mit „Markdown“ um. Besucher sehen
          erst, was du veröffentlichst. Bilder lädst und bearbeitest du unter{' '}
          <Link to="/webseite/bilder">Webseite › Bilder</Link>.
        </p>
        {groups.map((g) => {
          const items = data.texts.filter((t) => t.kind === g.kind)
          return (
            <div key={g.kind}>
              <h3>{g.title}</h3>
              {items.length === 0 && <p className="muted">Noch keine.</p>}
              {g.kind === 'page' && items.length > 0 && (
                <p className="muted small">
                  Wo die Textseiten im Menü stehen, legst du unter{' '}
                  <Link to="/webseite/aufbau">Webseite › Menü und Bereiche › Bausteine</Link> fest.
                </p>
              )}
              <TextList
                items={items}
                render={(t) => (
                  <>
                    <button
                      type="button"
                      className="link-button"
                      aria-expanded={open === t.id}
                      onClick={() => setOpen(open === t.id ? null : t.id)}
                    >
                      {t.kind === 'unit' ? t.department_name : t.title || t.kind_label}
                    </button>
                    {t.kind === 'page' && <span className="muted small"> /{t.slug}</span>}
                    <span className="muted small"> · {status(t)}</span>
                    {open === t.id && (
                      <TextPanel
                        id={t.id}
                        units={data.units}
                        linkTargets={data.link_targets ?? []}
                        onChanged={() => void reload()}
                        onDeleted={() => {
                          setOpen(null)
                          void reload()
                        }}
                      />
                    )}
                  </>
                )}
              />
            </div>
          )
        })}
        {adding ? (
          <NewText
            kind={adding}
            initialUnit={wantedUnit}
            units={data.units.filter(
              (u) => !data.texts.some((t) => t.kind === 'unit' && t.department === u.id),
            )}
            onDone={(id) => {
              setAdding(null)
              if (id) setOpen(id)
              void reload()
            }}
          />
        ) : (
          <div className="button-row">
            <button type="button" className="button" onClick={() => setAdding('page')}>
              Neue Textseite
            </button>
            {data.units.length > 0 && (
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setAdding('unit')}
              >
                Text für eine Untereinheit
              </button>
            )}
          </div>
        )}
      </div>
    </>
  )
}

/** Liste der Texte (die Reihenfolge der Textseiten im Menü steht unter Menü und Bereiche › Bausteine). */
function TextList({
  items,
  render,
}: {
  items: WebsiteTextSummary[]
  render: (t: WebsiteTextSummary) => ReactNode
}) {
  return (
    <ul className="plain-list">
      {items.map((t) => (
        <li key={t.id}>{render(t)}</li>
      ))}
    </ul>
  )
}

function NewText({
  kind,
  units,
  initialUnit,
  onDone,
}: {
  kind: 'page' | 'unit'
  units: { id: number; name: string }[]
  /** vorgewählte Untereinheit, falls sie zur Wahl steht */
  initialUnit?: number | null
  onDone: (id: number | null) => void
}) {
  const org = useActiveOrg()
  const form = useForm({
    title: '',
    slug: '',
    department: units.find((u) => u.id === initialUnit)?.id ?? units[0]?.id ?? 0,
  })
  const { values: v, set, errors } = form

  async function save() {
    const created = (await form.submit(() =>
      contentApi.create(
        org.id,
        kind === 'page'
          ? { kind, title: v.title, slug: v.slug }
          : {
              kind,
              department: v.department,
              title: units.find((u) => u.id === v.department)?.name ?? '',
            },
      ),
    )) as WebsiteText | undefined
    if (created) onDone(created.id)
  }

  return (
    <form
      className="subcard"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      <h3>{kind === 'page' ? 'Neue Textseite' : 'Text für eine Untereinheit'}</h3>
      {kind === 'page' ? (
        <div className="grid-2">
          <Field
            label="Titel"
            required
            value={v.title}
            error={errors.title}
            onChange={(e) => {
              const title = e.target.value
              set('title', title)
              set(
                'slug',
                title
                  .toLowerCase()
                  .replace(/ä/g, 'ae')
                  .replace(/ö/g, 'oe')
                  .replace(/ü/g, 'ue')
                  .replace(/ß/g, 'ss')
                  .replace(/[^a-z0-9]+/g, '-')
                  .replace(/^-|-$/g, '')
                  // Die Chronik der Webseite liest die Textseite „geschichte“
                  .replace(/^chronik$/, 'geschichte'),
              )
            }}
          />
          <Field
            label="Adresse (z. B. anfahrt; „geschichte“ erscheint als Chronik)"
            required
            value={v.slug}
            error={errors.slug}
            onChange={(e) => set('slug', e.target.value)}
          />
        </div>
      ) : (
        <SelectField
          label="Untereinheit"
          value={v.department}
          error={errors.department}
          onChange={(e) => set('department', Number(e.target.value))}
        >
          {units.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </SelectField>
      )}
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={form.busy}>
          Anlegen
        </button>
        <button type="button" className="button button-ghost" onClick={() => onDone(null)}>
          Abbrechen
        </button>
      </div>
    </form>
  )
}

function TextPanel({
  id,
  units,
  linkTargets,
  onChanged,
  onDeleted,
}: {
  id: number
  units: Unit[]
  linkTargets: LinkTarget[]
  onChanged: () => void
  onDeleted: () => void
}) {
  const org = useActiveOrg()
  const { data, error, reload, setData } = useLoad(() => contentApi.text(org.id, id), [org.id, id])
  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>
  return (
    <TextForm
      key={`${data.id}-${data.updated_at}-${data.revisions.length}`}
      text={data}
      units={units}
      linkTargets={linkTargets}
      onSaved={(t) => {
        setData(t)
        onChanged()
      }}
      onDeleted={onDeleted}
    />
  )
}

function TextForm({
  text,
  units,
  linkTargets,
  onSaved,
  onDeleted,
}: {
  text: WebsiteText
  units: Unit[]
  linkTargets: LinkTarget[]
  onSaved: (t: WebsiteText) => void
  onDeleted: () => void
}) {
  const org = useActiveOrg()
  const form = useForm({
    title: text.title,
    slug: text.slug,
    show_in_menu: text.show_in_menu,
    body: text.body,
    image: text.image,
    gallery: text.gallery ?? [],
  })
  const { values: v, set, errors } = form
  const [current, setCurrent] = useState(text)
  const auto = useAutoSave(form, (changes) => contentApi.save(org.id, text.id, changes), {
    onSaved: (saved) => setCurrent(saved as WebsiteText),
  })
  const images = useLoad(() => contentApi.images(org.id), [org.id])
  const [message, setMessage] = useState<string | null>(null)
  // Text einer Untereinheit: in der Bildauswahl stehen deren Bilder vorn
  const unit: Unit | null =
    text.kind === 'unit' && text.department
      ? (units.find((u) => u.id === text.department) ?? {
          id: text.department,
          name: text.department_name ?? 'Untereinheit',
        })
      : null
  const reloadImages = () => void images.reload()

  async function act(action: () => Promise<WebsiteText>) {
    setMessage(null)
    if (!(await auto.flush())) return
    try {
      onSaved(await action())
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: `„${text.title}“ löschen?`,
      message: 'Die Seite verschwindet von der Webseite, frühere Fassungen werden mit gelöscht.',
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    try {
      await contentApi.remove(org.id, text.id)
      onDeleted()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <form className="subcard" onSubmit={(e) => e.preventDefault()} aria-label="Text bearbeiten">
      <SaveStatus auto={auto} />
      <p className="muted small">
        {current.is_published
          ? `Veröffentlicht am ${formatDateTime(current.published_at!)}.`
          : 'Noch nicht veröffentlicht.'}{' '}
        {current.is_published && current.has_changes && 'Der Entwurf hat Änderungen.'}
      </p>
      <Field
        label="Titel"
        value={v.title}
        error={errors.title}
        onChange={(e) => set('title', e.target.value)}
      />
      {text.kind === 'page' && (
        <div className="grid-2">
          <Field
            label="Adresse"
            value={v.slug}
            error={errors.slug}
            onChange={(e) => set('slug', e.target.value)}
          />
          <Checkbox
            label="im Menü zeigen"
            checked={v.show_in_menu}
            onChange={(on) => set('show_in_menu', on)}
          />
        </div>
      )}
      <TextEditor
        label="Text"
        value={v.body}
        error={errors.body}
        rows={12}
        images={images.data ?? []}
        renderImagePicker={(insert, cancel) => (
          <ImagePicker
            images={images.data ?? []}
            unit={unit}
            title="Bild einfügen"
            onUploaded={reloadImages}
            onPick={(picked) => (picked[0] ? insert(picked[0]) : cancel())}
            onCancel={cancel}
          />
        )}
        linkTargets={linkTargets}
        onChange={(body) => set('body', body)}
      />
      <ImageChoice
        label={text.kind === 'unit' ? 'Bild der Untereinheit' : 'Bild oben auf der Seite'}
        value={v.image}
        images={images.data ?? []}
        unit={unit}
        units={units}
        onChange={(id) => set('image', id)}
        onImagesChanged={reloadImages}
      />
      {text.kind !== 'page' && (
        <GalleryPicker
          images={images.data ?? []}
          value={v.gallery}
          error={errors.gallery}
          unit={unit}
          onChange={(ids) => set('gallery', ids)}
          onImagesChanged={reloadImages}
        />
      )}
      {message && <Alert kind="error">{message}</Alert>}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          onClick={() => void act(() => contentApi.publish(org.id, text.id))}
        >
          Veröffentlichen
        </button>
        {current.is_published && (
          <button
            type="button"
            className="button button-ghost"
            onClick={() => void act(() => contentApi.unpublish(org.id, text.id))}
          >
            Veröffentlichung zurücknehmen
          </button>
        )}
        {text.kind !== 'greeting' && (
          <button type="button" className="button button-danger" onClick={() => void remove()}>
            Löschen
          </button>
        )}
      </div>
      {text.revisions.length > 0 && (
        <>
          <h4>Frühere Fassungen</h4>
          <ul className="plain-list">
            {text.revisions.map((r) => (
              <li key={r.id}>
                {formatDateTime(r.published_at)}
                {r.published_by && ` · ${r.published_by}`}{' '}
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => void act(() => contentApi.restore(org.id, text.id, r.id))}
                >
                  In den Entwurf holen
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </form>
  )
}

const MAX_GALLERY = 10

/** Bilderkarussell: Bilder im Auswahl-Dialog ankreuzen, Reihenfolge hier ändern */
function GalleryPicker({
  images,
  value,
  error,
  unit,
  onChange,
  onImagesChanged,
}: {
  images: WebsiteImage[]
  value: number[]
  error?: string
  unit: Unit | null
  onChange: (ids: number[]) => void
  onImagesChanged: () => void
}) {
  const [picking, setPicking] = useState(false)
  const byId = new Map(images.map((i) => [i.id, i]))
  const chosen = value.filter((id) => byId.has(id))
  const move = (index: number, delta: number) => {
    const next = [...chosen]
    const [item] = next.splice(index, 1)
    next.splice(index + delta, 0, item)
    onChange(next)
  }
  return (
    <fieldset className="gallery-picker">
      <legend>Bilderkarussell (optional)</legend>
      <p className="muted small">
        Mit zwei oder mehr Bildern zeigt die Startseite statt des einzelnen Bildes ein Karussell zum
        Durchblättern. Es wechselt alle 7 Sekunden von selbst und lässt sich anhalten. Bis zu{' '}
        {MAX_GALLERY} Bilder.
      </p>
      {chosen.length > 0 && (
        <ol className="gallery-list">
          {chosen.map((id, index) => (
            <li key={id}>
              <img src={byId.get(id)!.small_url} alt="" width={64} height={40} />
              <span>{imageLabel(byId.get(id)!)}</span>
              <span className="button-row">
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={index === 0}
                  aria-label={`${imageLabel(byId.get(id)!)} nach vorn`}
                  onClick={() => move(index, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={index === chosen.length - 1}
                  aria-label={`${imageLabel(byId.get(id)!)} nach hinten`}
                  onClick={() => move(index, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  aria-label={`${imageLabel(byId.get(id)!)} entfernen`}
                  onClick={() => onChange(chosen.filter((x) => x !== id))}
                >
                  Entfernen
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
      <div className="button-row">
        <button type="button" className="button button-ghost" onClick={() => setPicking(true)}>
          {chosen.length ? 'Bilder ändern' : 'Bilder wählen'}
        </button>
      </div>
      {picking && (
        <ImagePicker
          images={images}
          unit={unit}
          title="Bilder fürs Karussell"
          multiple
          max={MAX_GALLERY}
          initial={chosen}
          onUploaded={onImagesChanged}
          onPick={(picked) => {
            setPicking(false)
            onChange(picked.map((i) => i.id))
          }}
          onCancel={() => setPicking(false)}
        />
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </fieldset>
  )
}
