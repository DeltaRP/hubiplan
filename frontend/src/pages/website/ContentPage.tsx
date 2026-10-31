// Webseite › Texte und Bilder: Begrüßung, Textseiten (z. B. Chronik), Texte der
// Untereinheiten und Bilder. Änderungen sind erst nach „Veröffentlichen“
// sichtbar; frühere Fassungen lassen sich zurückholen.
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client.ts'
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
import { Why } from '../../learning/Aids.tsx'
import { useImageCrop } from '../../components/ImageCrop.tsx'
import { RightsHint } from '../../components/RightsHint.tsx'
import { TextEditor } from '../../components/texteditor/TextEditor.tsx'

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
  const [handledUnit, setHandledUnit] = useState(false)
  if (data && wantedUnit && !handledUnit) {
    setHandledUnit(true)
    const text = data.texts.find((t) => t.kind === 'unit' && t.department === wantedUnit)
    if (text) setOpen(text.id)
    else if (data.units.some((u) => u.id === wantedUnit)) setAdding('unit')
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
          erst, was du veröffentlichst.
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
      <ImagesCard />
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
  linkTargets,
  onChanged,
  onDeleted,
}: {
  id: number
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
  linkTargets,
  onSaved,
  onDeleted,
}: {
  text: WebsiteText
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
        onUploadImage={async (file, alt) => {
          const image = await contentApi.upload(org.id, file, '', alt)
          await images.reload()
          return image
        }}
        linkTargets={linkTargets}
        onChange={(body) => set('body', body)}
      />
      <SelectField
        label={text.kind === 'unit' ? 'Bild der Untereinheit' : 'Bild oben auf der Seite'}
        value={v.image ?? ''}
        onChange={(e) => set('image', e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">kein Bild</option>
        {(images.data ?? []).map((i) => (
          <option key={i.id} value={i.id}>
            {i.caption || i.alt_text || `Bild ${i.key}`}
          </option>
        ))}
      </SelectField>
      {text.kind !== 'page' && (
        <GalleryPicker
          images={images.data ?? []}
          value={v.gallery}
          error={errors.gallery}
          onChange={(ids) => set('gallery', ids)}
          onUpload={async (file, alt) => {
            const image = await contentApi.upload(org.id, file, '', alt)
            await images.reload()
            return image.id
          }}
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

function ImagesCard() {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => contentApi.images(org.id), [org.id])
  const [file, setFile] = useState<File | null>(null)
  const crop = useImageCrop()
  const [caption, setCaption] = useState('')
  const [alt, setAlt] = useState('')
  const [decorative, setDecorative] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<unknown>) {
    setMessage(null)
    setBusy(true)
    try {
      await action()
      void reload()
      return true
    } catch (err) {
      setMessage(errorMessage(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function remove(image: WebsiteImage) {
    const ok = await confirmDialog({ title: 'Bild löschen?', confirmLabel: 'Löschen' })
    if (!ok) return
    try {
      setBusy(true)
      await contentApi.removeImage(org.id, image.id)
      void reload()
    } catch (err) {
      // Wird das Bild noch verwendet, die Stellen nennen und nachfragen
      if (!(err instanceof ApiError) || err.status !== 409) {
        setMessage(errorMessage(err))
        return
      }
      const again = await confirmDialog({
        title: 'Bild trotzdem löschen?',
        message: err.message,
        confirmLabel: 'Trotzdem löschen',
      })
      if (again) await run(() => contentApi.removeImage(org.id, image.id, true))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>Bilder</h2>
      <div className="aid-row">
        <Why k="web_photos" />
        <Why k="web_alt_text" />
      </div>
      <p className="muted small">
        Bilder werden beim Hochladen verkleinert, und Angaben wie Kamera oder Aufnahmeort werden
        entfernt. Für Fotos mit Personen braucht es deren Einverständnis.
      </p>
      {error && <LoadError message={error} onRetry={() => void reload()} />}
      <ul className="plain-list">
        {(data ?? []).map((i) => (
          <li key={i.id}>
            <img src={i.small_url} alt={i.alt_text} width={120} />{' '}
            <strong>{i.caption || i.alt_text || 'ohne Beschriftung'}</strong>
            <br />
            <AltTextEditor
              image={i}
              busy={busy}
              onSave={(data) => run(() => contentApi.saveImage(org.id, i.id, data))}
            />
            <code>{i.markdown}</code>
            <div className="button-row">
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void navigator.clipboard?.writeText(i.markdown)}
              >
                Schnipsel kopieren
              </button>
              <button
                type="button"
                className="button button-ghost"
                aria-label={`Bild ${i.caption || i.key} löschen`}
                onClick={() => void remove(i)}
              >
                Löschen
              </button>
            </div>
          </li>
        ))}
      </ul>
      {message && <Alert kind="error">{message}</Alert>}
      <form
        className="subcard"
        onSubmit={(e) => {
          e.preventDefault()
          if (!file) return
          void run(() => contentApi.upload(org.id, file, caption, alt, decorative)).then((ok) => {
            if (ok) {
              setFile(null)
              setCaption('')
              setAlt('')
              setDecorative(false)
            }
          })
        }}
      >
        <h3>Bild hochladen</h3>
        <label className="field">
          <span>Datei (JPEG, PNG oder WebP)</span>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => crop.choose(e, setFile)}
          />
          {crop.dialog}
          <RightsHint />
        </label>
        <div className="grid-2">
          <Field
            label="Bildunterschrift"
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
          />
          <Field
            label="Alternativtext (was zu sehen ist)"
            value={alt}
            disabled={decorative}
            hint={
              !alt.trim() && !decorative
                ? 'Ohne Beschreibung erfahren blinde Besucher nicht, was auf dem Bild zu sehen ist.'
                : undefined
            }
            onChange={(e) => setAlt(e.target.value)}
          />
        </div>
        <Checkbox
          label="Nur Schmuck, das Bild zeigt nichts Wichtiges"
          hint="dann ohne Beschreibung"
          checked={decorative}
          onChange={setDecorative}
        />
        <button type="submit" className="button" disabled={!file || busy}>
          Hochladen
        </button>
      </form>
    </div>
  )
}

const MAX_GALLERY = 10

/**
 * Hinweis bei Bildern ohne Alternativtext, mit Feld zum Ergänzen oder „nur Schmuck“
 * (Barrierefreiheit W-06). Ohne Text nutzt die Webseite die Bildunterschrift.
 */
function AltTextEditor({
  image,
  busy,
  onSave,
}: {
  image: WebsiteImage
  busy: boolean
  onSave: (data: { alt_text?: string; decorative?: boolean }) => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  if (image.alt_text || image.decorative) return null
  if (!open) {
    return (
      <p className="small field-error">
        Ohne Beschreibung für blinde Besucher
        {image.caption ? ' (die Webseite nimmt dafür die Bildunterschrift)' : ''}.{' '}
        <button type="button" className="link-button" onClick={() => setOpen(true)}>
          Beschreibung ergänzen
        </button>
      </p>
    )
  }
  return (
    <div className="subcard">
      <Field
        label="Was ist zu sehen? (Alternativtext)"
        value={text}
        maxLength={300}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="button-row">
        <button
          type="button"
          className="button"
          disabled={busy || !text.trim()}
          onClick={() => void onSave({ alt_text: text.trim() })}
        >
          Speichern
        </button>
        <button
          type="button"
          className="button button-ghost"
          disabled={busy}
          onClick={() => void onSave({ decorative: true })}
        >
          Nur Schmuck
        </button>
        <button type="button" className="button button-ghost" onClick={() => setOpen(false)}>
          Abbrechen
        </button>
      </div>
    </div>
  )
}

function imageLabel(i: WebsiteImage): string {
  return i.caption || i.alt_text || `Bild ${i.key}`
}

/** Bilderkarussell der Begrüßung: Bilder wählen und ordnen */
function GalleryPicker({
  images,
  value,
  error,
  onChange,
  onUpload,
}: {
  images: WebsiteImage[]
  value: number[]
  error?: string
  onChange: (ids: number[]) => void
  /** Foto hochladen; liefert die ID des neuen Bildes */
  onUpload: (file: File, alt: string) => Promise<number>
}) {
  const [file, setFile] = useState<File | null>(null)
  const crop = useImageCrop()
  const [alt, setAlt] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  async function upload() {
    if (!file) return
    setBusy(true)
    setUploadError(null)
    try {
      const id = await onUpload(file, alt)
      onChange([...chosen, id])
      setFile(null)
      setAlt('')
    } catch (err) {
      setUploadError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  const byId = new Map(images.map((i) => [i.id, i]))
  const chosen = value.filter((id) => byId.has(id))
  const free = images.filter((i) => !value.includes(i.id))
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
        Durchblättern. Es wechselt alle 7 Sekunden von selbst und lässt sich anhalten. Bilder lädst
        du unten unter „Bilder“ hoch.
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
      {free.length > 0 && chosen.length < MAX_GALLERY && (
        <SelectField
          label="Bild hinzufügen"
          value=""
          onChange={(e) => e.target.value && onChange([...chosen, Number(e.target.value)])}
        >
          <option value="">Bild wählen …</option>
          {free.map((i) => (
            <option key={i.id} value={i.id}>
              {imageLabel(i)}
            </option>
          ))}
        </SelectField>
      )}
      {chosen.length < MAX_GALLERY && (
        <div className="grid-2">
          <label className="field">
            <span>Neues Foto hochladen</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => crop.choose(e, setFile)}
            />
            {crop.dialog}
            <RightsHint />
          </label>
          <Field
            label="Was ist zu sehen? (Alternativtext)"
            value={alt}
            hint={
              file && !alt.trim()
                ? 'Ohne Beschreibung erfahren blinde Besucher nicht, was auf dem Bild zu sehen ist.'
                : undefined
            }
            onChange={(e) => setAlt(e.target.value)}
          />
        </div>
      )}
      {file && (
        <div className="button-row">
          <button type="button" className="button" disabled={busy} onClick={() => void upload()}>
            Hochladen und hinzufügen
          </button>
        </div>
      )}
      {uploadError && <Alert kind="error">{uploadError}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
    </fieldset>
  )
}
