// Bilder der Webseite (Ralf 01.11.): Übersicht als Kacheln mit Suche und Filtern,
// Fenster „Bild bearbeiten“ (Ausschnitt neu wählen, Angaben, Zuordnung zu einer
// Untereinheit, ersetzen, kopieren, löschen) und ein Auswahl-Dialog für Texte, der
// auf Seiten einer Untereinheit zuerst deren Bilder zeigt.
import { useEffect, useRef, useState } from 'react'
import type { DragEvent, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { contentApi } from '../../api/website.ts'
import type { WebsiteImage, WebsiteImageDetail } from '../../api/website.ts'
import {
  errorMessage,
  formatDateTime,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { useImageCrop } from '../../components/ImageCrop.tsx'
import type { CropArea } from '../../components/ImageCrop.tsx'
import { Modal } from '../../components/Modal.tsx'
import { RightsHint } from '../../components/RightsHint.tsx'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { Why } from '../../learning/Aids.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import {
  IMAGE_ORDERS,
  imageLabel,
  needsAlt,
  removeImage,
  sortImages,
  useImageUpload,
} from './imageTools.ts'
import type { ImageOrder } from './imageTools.ts'
import { t, tn } from '../../i18n/index.ts'

export interface Unit {
  id: number
  name: string
}

const ACCEPT = 'image/jpeg,image/png,image/webp'
const PAGE_SIZE = 40
const FULL: CropArea = { x: 0, y: 0, width: 100, height: 100, rotation: 0, aspect: 'original' }

/** Knopf „Bilder hochladen“ (mehrere Dateien) samt Ziehen auf die Fläche */
function UploadButton({
  label = t('Bilder hochladen'),
  multiple = true,
  disabled,
  onFiles,
}: {
  label?: string
  multiple?: boolean
  disabled?: boolean
  onFiles: (files: File[]) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <>
      <button
        type="button"
        className="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
      >
        {label}
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple={multiple}
        hidden
        aria-label={label}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
    </>
  )
}

function droppedImages(e: DragEvent): File[] {
  return Array.from(e.dataTransfer.files).filter((f) => ACCEPT.split(',').includes(f.type))
}

// --- Filter ---

type Scope = 'all' | 'general' | number
type State = 'all' | 'unused' | 'no_alt'

function matches(i: WebsiteImage, q: string, scope: Scope, state: State): boolean {
  if (scope === 'general' && i.department) return false
  if (typeof scope === 'number' && i.department !== scope) return false
  if (state === 'unused' && i.used !== false) return false
  if (state === 'no_alt' && !needsAlt(i)) return false
  if (q) {
    const hay = t('{caption} {alt_text} {x}', {
      caption: i.caption,
      alt_text: i.alt_text,
      x: i.department_name ?? '',
    }).toLowerCase()
    if (
      !q
        .toLowerCase()
        .split(/\s+/)
        .every((w) => hay.includes(w))
    )
      return false
  }
  return true
}

function OrderField({
  value,
  onChange,
}: {
  value: ImageOrder
  onChange: (order: ImageOrder) => void
}) {
  return (
    <SelectField
      label={t('Sortieren')}
      value={value}
      onChange={(e) => onChange(e.target.value as ImageOrder)}
    >
      {IMAGE_ORDERS.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </SelectField>
  )
}

/** Kachelraster; mit ``selected`` zum Ankreuzen, sonst zum Öffnen */
function ImageTiles({
  images,
  selected,
  onClick,
  before,
}: {
  images: WebsiteImage[]
  selected?: number[]
  onClick: (image: WebsiteImage) => void
  before?: ReactNode
}) {
  return (
    <ul className="image-tiles">
      {before}
      {images.map((i) => {
        const index = selected?.indexOf(i.id) ?? -1
        return (
          <li key={i.id}>
            <button
              type="button"
              className="image-tile"
              aria-pressed={selected ? index >= 0 : undefined}
              onClick={() => onClick(i)}
            >
              <img src={i.small_url} alt="" loading="lazy" />
              {index >= 0 && <span className="image-tile-mark">{index + 1}</span>}
              <span className="image-tile-label">{imageLabel(i)}</span>
              <span className="image-tile-tags">
                {i.department_name && <small className="tag">{i.department_name}</small>}
                {i.used === false && (
                  <small className="tag tag-muted">{t('nicht verwendet')}</small>
                )}
                {needsAlt(i) && <small className="tag tag-warn">{t('ohne Beschreibung')}</small>}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

// --- Übersicht ---

export function ImagesPage() {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => contentApi.images(org.id), [org.id])
  const texts = useLoad(() => contentApi.texts(org.id), [org.id])
  const units = texts.data?.units ?? []
  const [q, setQ] = useState('')
  const [scope, setScope] = useState<Scope>('all')
  const [state, setState] = useState<State>('all')
  const [order, setOrder] = useState<ImageOrder>('newest')
  const [shown, setShown] = useState(PAGE_SIZE)
  const [open, setOpen] = useState<number | null>(null)
  const [dragging, setDragging] = useState(false)
  const uploader = useImageUpload()

  async function add(files: File[]) {
    const done = await uploader.upload(files, {
      department: typeof scope === 'number' ? scope : null,
    })
    if (done.length) void reload()
    if (done.length === 1) setOpen(done[0].id)
  }

  const all = data ?? []
  const filtered = sortImages(
    all.filter((i) => matches(i, q, scope, state)),
    order,
  )
  const scopeValue = typeof scope === 'number' ? String(scope) : scope

  return (
    <div
      className={`card card-wide${dragging ? ' drop-target' : ''}`}
      onDragOver={(e) => {
        if (Array.from(e.dataTransfer.types).includes('Files')) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        const files = droppedImages(e)
        if (files.length) void add(files)
      }}
    >
      <h2>{t('Bilder')}</h2>
      <div className="aid-row">
        <Why k="web_photos" />
        <Why k="web_alt_text" />
      </div>
      <p className="muted small">
        {t(
          'Bilder werden beim Hochladen verkleinert, und Angaben wie Kamera oder Aufnahmeort werden entfernt. Für Fotos mit Personen braucht es deren Einverständnis. Du kannst Bilder auch hierher ziehen. Ein Klick auf ein Bild öffnet es zum Bearbeiten.',
        )}
      </p>
      <RightsHint />
      <div className="image-filters">
        <Field
          label={t('Suchen')}
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setShown(PAGE_SIZE)
          }}
        />
        {units.length > 0 && (
          <SelectField
            label={t('Gehört zu')}
            value={scopeValue}
            onChange={(e) => {
              const v = e.target.value
              setScope(v === 'all' || v === 'general' ? v : Number(v))
              setShown(PAGE_SIZE)
            }}
          >
            <option value="all">alle</option>
            <option value="general">{t('Verein allgemein')}</option>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </SelectField>
        )}
        <SelectField
          label={t('Zustand')}
          value={state}
          onChange={(e) => {
            setState(e.target.value as State)
            setShown(PAGE_SIZE)
          }}
        >
          <option value="all">alle</option>
          <option value="unused">{t('nicht verwendet')}</option>
          <option value="no_alt">{t('ohne Beschreibung')}</option>
        </SelectField>
        <OrderField value={order} onChange={setOrder} />
        <div className="button-row">
          <UploadButton disabled={uploader.busy} onFiles={(files) => void add(files)} />
        </div>
      </div>
      {uploader.dialog}
      {uploader.busy && <p className="muted small">{t('Wird hochgeladen …')}</p>}
      {uploader.error && <Alert kind="error">{uploader.error}</Alert>}
      {error && <LoadError message={error} onRetry={() => void reload()} />}
      {data && all.length === 0 && <p className="muted">{t('Noch keine Bilder hochgeladen.')}</p>}
      {data && all.length > 0 && (
        <p className="muted small" aria-live="polite">
          {filtered.length === all.length
            ? tn('{n} Bild', '{n} Bilder', all.length)
            : t('{n} von {n2} Bildern', { n: filtered.length, n2: all.length })}
        </p>
      )}
      <ImageTiles images={filtered.slice(0, shown)} onClick={(i) => setOpen(i.id)} />
      {filtered.length > shown && (
        <div className="button-row">
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShown((n) => n + PAGE_SIZE)}
          >
            {t('Weitere laden')}
          </button>
        </div>
      )}
      {open !== null && (
        <ImageEditDialog
          id={open}
          units={units}
          onChanged={() => void reload()}
          onOpen={setOpen}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  )
}

// --- Bild bearbeiten ---

async function loadFile(url: string, name: string): Promise<File> {
  const res = await fetch(url, { credentials: 'same-origin' })
  if (!res.ok) throw new Error(t('Das Original ließ sich nicht laden.'))
  const blob = await res.blob()
  return new File([blob], name, { type: blob.type || 'image/jpeg' })
}

export function ImageEditDialog({
  id,
  units,
  onChanged,
  onOpen,
  onClose,
}: {
  id: number
  units: Unit[]
  onChanged: () => void
  /** anderes Bild öffnen (nach „Als Kopie bearbeiten“) */
  onOpen?: (id: number) => void
  onClose: () => void
}) {
  const org = useActiveOrg()
  const { data, error, reload, setData } = useLoad(() => contentApi.image(org.id, id), [org.id, id])
  // „Schließen“ oben im Fenster wartet, bis die Angaben gespeichert sind
  const flush = useRef<(() => Promise<boolean>) | null>(null)
  return (
    <Modal
      title={t('Bild bearbeiten')}
      onClose={onClose}
      beforeClose={() => flush.current?.() ?? true}
    >
      {error && <LoadError message={error} onRetry={() => void reload()} />}
      {!data && !error && <p className="muted">{t('Lädt …')}</p>}
      {data && (
        <ImageEditForm
          key={data.id}
          image={data}
          units={units}
          onChanged={(image) => {
            setData({ ...data, ...image })
            onChanged()
          }}
          onCopied={(copy) => {
            onChanged()
            onOpen?.(copy.id)
          }}
          onDeleted={() => {
            onChanged()
            onClose()
          }}
          onClose={onClose}
          flushRef={flush}
        />
      )}
    </Modal>
  )
}

function ImageEditForm({
  image,
  units,
  onChanged,
  onCopied,
  onDeleted,
  onClose,
  flushRef,
}: {
  image: WebsiteImageDetail
  units: Unit[]
  onChanged: (image: WebsiteImage) => void
  onCopied: (copy: WebsiteImage) => void
  onDeleted: () => void
  onClose: () => void
  /** zum Speichern vor dem Schließen des Fensters */
  flushRef: { current: (() => Promise<boolean>) | null }
}) {
  const org = useActiveOrg()
  const form = useForm({
    caption: image.caption,
    alt_text: image.alt_text,
    decorative: !!image.decorative,
    department: image.department ?? null,
  })
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) => contentApi.saveImage(org.id, image.id, changes), {
    onSaved: (saved) => onChanged(saved as WebsiteImage),
  })
  useEffect(() => {
    flushRef.current = auto.flush
    return () => {
      flushRef.current = null
    }
  }, [flushRef, auto.flush])
  const crop = useImageCrop({ title: t('Ausschnitt ändern') })
  const replace = useImageCrop({ title: t('Neues Bild zuschneiden') })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function run(action: () => Promise<void>) {
    setMessage(null)
    setBusy(true)
    try {
      await action()
    } catch (err) {
      setMessage(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function original(): Promise<File> {
    return loadFile(image.original_url ?? image.url, `bild-${image.key}.jpg`)
  }

  const recrop = () =>
    run(async () => {
      const file = await original()
      const result = await crop.pickArea(file, image.crop as CropArea)
      if (!result) return
      onChanged(await contentApi.cropImage(org.id, image.id, result.file, result.crop ?? FULL))
    })

  const copy = () =>
    run(async () => {
      const file = await original()
      const result = await crop.pickArea(file, image.crop as CropArea)
      if (!result) return
      onCopied(await contentApi.copyImage(org.id, image.id, result.file, result.crop ?? FULL))
    })

  const replaceWith = (file: File) =>
    run(async () => {
      const result = await replace.pickArea(file)
      if (!result) return
      onChanged(
        await contentApi.replaceImage(org.id, image.id, {
          file: result.file,
          original: result.crop ? file : null,
          crop: result.crop,
        }),
      )
    })

  const remove = () =>
    run(async () => {
      if (!(await auto.flush())) return
      if (await removeImage(org.id, image)) onDeleted()
    })

  return (
    <form
      className="image-edit"
      onSubmit={(e) => e.preventDefault()}
      aria-label={t('Bild bearbeiten')}
    >
      <div className="image-edit-preview">
        <img src={image.url} alt={image.alt_text} />
        <div className="button-row">
          <button type="button" className="button" disabled={busy} onClick={() => void recrop()}>
            {t('Ausschnitt ändern')}
          </button>
        </div>
        <p className="muted small">
          {t(
            'Der Ausschnitt wird aus dem Original neu gewählt; „Unverändert übernehmen“ zeigt wieder das ganze Bild.',
          )}
        </p>
      </div>
      <div className="image-edit-fields">
        <SaveStatus auto={auto} />
        <Field
          label={t('Bildunterschrift')}
          value={v.caption}
          maxLength={300}
          error={errors.caption}
          onChange={(e) => set('caption', e.target.value)}
        />
        <Field
          label={t('Alternativtext (was zu sehen ist)')}
          value={v.alt_text}
          maxLength={300}
          disabled={v.decorative}
          error={errors.alt_text}
          hint={
            !v.alt_text.trim() && !v.decorative
              ? t(
                  'Ohne Beschreibung erfahren blinde Besucher nicht, was auf dem Bild zu sehen ist.',
                )
              : undefined
          }
          onChange={(e) => set('alt_text', e.target.value)}
        />
        <Checkbox
          label={t('Nur Schmuck, das Bild zeigt nichts Wichtiges')}
          hint={t('dann ohne Beschreibung')}
          checked={v.decorative}
          onChange={(on) => set('decorative', on)}
        />
        {units.length > 0 && (
          <SelectField
            label={t('Gehört zu')}
            value={v.department ?? ''}
            error={errors.department}
            hint={t('Bei der Bildauswahl einer Untereinheit stehen ihre Bilder vorn.')}
            onChange={(e) => set('department', e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">{t('Verein allgemein')}</option>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </SelectField>
        )}
        <h3>{t('Verwendet in')}</h3>
        {image.usage.length === 0 ? (
          <p className="muted small">{t('Noch in keinem Text.')}</p>
        ) : (
          <>
            <ul className="plain-list small">
              {image.usage.map((u) => (
                <li key={u.text}>
                  <Link to={`/webseite/inhalte?text=${u.text}`} onClick={onClose}>
                    {u.label}
                  </Link>
                  : {u.places.join(', ')}
                </li>
              ))}
            </ul>
            <p className="muted small">
              {t(
                'Änderungen am Bild wirken sofort an allen Stellen, auch auf der veröffentlichten Webseite.',
              )}
            </p>
          </>
        )}
        {message && <Alert kind="error">{message}</Alert>}
        {crop.dialog}
        {replace.dialog}
        <details className="image-edit-more">
          <summary>{t('Mehr')}</summary>
          <div className="button-row">
            <UploadButton
              label={t('Datei ersetzen')}
              multiple={false}
              disabled={busy}
              onFiles={(files) => void replaceWith(files[0])}
            />
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => void copy()}
            >
              {t('Als Kopie bearbeiten')}
            </button>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => {
                void navigator.clipboard?.writeText(image.markdown)
                setCopied(true)
              }}
            >
              {copied ? t('Schnipsel kopiert') : t('Schnipsel kopieren')}
            </button>
          </div>
          <p className="muted small">
            {t(
              '„Datei ersetzen“ behält alle Stellen und Angaben. „Als Kopie bearbeiten“ legt ein zweites Bild aus demselben Original an, z. B. breit für den Seitenkopf und quadratisch fürs Karussell.',
            )}
          </p>
          <p className="muted small">
            {image.width} {t('× {height} Pixel · hochgeladen am', { height: image.height })}{' '}
            {formatDateTime(image.uploaded_at)}
            <br />
            <code>{image.markdown}</code>
          </p>
        </details>
        <div className="button-row">
          <button
            type="button"
            className="button button-danger"
            disabled={busy}
            onClick={() => void remove()}
          >
            {t('Löschen')}
          </button>
        </div>
      </div>
    </form>
  )
}

// --- Auswahl ---

/**
 * Bild(er) wählen. Auf Seiten einer Untereinheit stehen erst deren Bilder und die des
 * Vereins allgemein, „alle Bilder“ zeigt den Rest. Neue Bilder gehören gleich zur
 * Untereinheit und sind danach ausgewählt.
 */
export function ImagePicker({
  images,
  unit,
  title = t('Bild wählen'),
  multiple = false,
  initial = [],
  max,
  onUploaded,
  onPick,
  onCancel,
}: {
  images: WebsiteImage[]
  unit?: Unit | null
  title?: string
  multiple?: boolean
  initial?: number[]
  max?: number
  onUploaded: () => void
  onPick: (images: WebsiteImage[]) => void
  onCancel: () => void
}) {
  const [q, setQ] = useState('')
  const [scope, setScope] = useState<'unit' | 'suggested' | 'all'>('suggested')
  const [order, setOrder] = useState<ImageOrder>('newest')
  const [chosen, setChosen] = useState<number[]>(initial)
  const [extra, setExtra] = useState<WebsiteImage[]>([])
  const [shown, setShown] = useState(PAGE_SIZE)
  const uploader = useImageUpload()
  const all = [...extra.filter((e) => !images.some((i) => i.id === e.id)), ...images]
  const suggested = (i: WebsiteImage) => !i.department || (unit ? i.department === unit.id : false)
  const anyOther = all.some((i) => !suggested(i))
  // Gerade hochgeladene Bilder bleiben vorn, der Rest nach der gewählten Sortierung
  const fresh = new Set(extra.map((e) => e.id))
  const filtered = [
    ...all.filter((i) => fresh.has(i.id)),
    ...sortImages(
      all.filter((i) => !fresh.has(i.id)),
      order,
    ),
  ].filter(
    (i) =>
      (scope === 'all' || (scope === 'unit' ? !!unit && i.department === unit.id : suggested(i))) &&
      matches(i, q, 'all', 'all'),
  )
  const full = max !== undefined && chosen.length >= max

  function click(i: WebsiteImage) {
    if (!multiple) {
      onPick([i])
      return
    }
    setChosen((c) => (c.includes(i.id) ? c.filter((x) => x !== i.id) : full ? c : [...c, i.id]))
  }

  async function add(files: File[]) {
    const done = await uploader.upload(files, { department: unit?.id ?? null })
    if (!done.length) return
    setExtra((e) => [...done, ...e])
    onUploaded()
    if (!multiple) onPick([done[0]])
    else
      setChosen((c) => {
        const room = max === undefined ? done.length : Math.max(0, max - c.length)
        return [...c, ...done.slice(0, room).map((d) => d.id)]
      })
  }

  const byId = new Map(all.map((i) => [i.id, i]))
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="image-filters">
        <Field label={t('Suchen')} type="search" value={q} onChange={(e) => setQ(e.target.value)} />
        <OrderField value={order} onChange={setOrder} />
        {(anyOther || unit) && (
          <fieldset className="image-scope">
            <legend className="sr-only">{t('Welche Bilder')}</legend>
            {unit && (
              <label>
                <input
                  type="radio"
                  name="bildumfang"
                  checked={scope === 'unit'}
                  onChange={() => setScope('unit')}
                />{' '}
                nur {unit.name}
              </label>
            )}
            <label>
              <input
                type="radio"
                name="bildumfang"
                checked={scope === 'suggested'}
                onChange={() => setScope('suggested')}
              />{' '}
              {unit ? t('{name} und Verein allgemein', { name: unit.name }) : t('Verein allgemein')}
            </label>
            <label>
              <input
                type="radio"
                name="bildumfang"
                checked={scope === 'all'}
                onChange={() => setScope('all')}
              />{' '}
              {t('alle Bilder')}
            </label>
          </fieldset>
        )}
      </div>
      {uploader.dialog}
      {uploader.error && <Alert kind="error">{uploader.error}</Alert>}
      <ImageTiles
        images={filtered.slice(0, shown)}
        selected={multiple ? chosen : undefined}
        onClick={click}
        before={
          <li>
            <label className="image-tile image-tile-new">
              <span aria-hidden="true">＋</span>
              <span>{uploader.busy ? t('Wird hochgeladen …') : t('Neues Bild hochladen')}</span>
              <input
                type="file"
                accept={ACCEPT}
                multiple={multiple}
                className="sr-only"
                disabled={uploader.busy || (multiple && full)}
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? [])
                  e.target.value = ''
                  if (files.length) void add(files)
                }}
              />
            </label>
          </li>
        }
      />
      {filtered.length === 0 && <p className="muted small">{t('Keine passenden Bilder.')}</p>}
      {filtered.length > shown && (
        <div className="button-row">
          <button
            type="button"
            className="button button-ghost"
            onClick={() => setShown((n) => n + PAGE_SIZE)}
          >
            {t('Weitere laden')}
          </button>
        </div>
      )}
      <RightsHint />
      {multiple && (
        <div className="button-row">
          <button
            type="button"
            className="button button-primary"
            onClick={() => onPick(chosen.map((id) => byId.get(id)).filter((i) => !!i))}
          >
            {t('Übernehmen')}
            {max !== undefined ? ` (${chosen.length} von ${max})` : ''}
          </button>
          <button type="button" className="button button-ghost" onClick={onCancel}>
            {t('Abbrechen')}
          </button>
        </div>
      )}
    </Modal>
  )
}

/** Ein Bild am Text: Vorschau mit Ändern, Bearbeiten und Entfernen statt einer Liste. */
export function ImageChoice({
  label,
  value,
  images,
  unit,
  units,
  onChange,
  onImagesChanged,
}: {
  label: string
  value: number | null
  images: WebsiteImage[]
  unit?: Unit | null
  units: Unit[]
  onChange: (id: number | null) => void
  onImagesChanged: () => void
}) {
  const [picking, setPicking] = useState(false)
  const [editing, setEditing] = useState(false)
  const image = images.find((i) => i.id === value) ?? null
  return (
    <fieldset className="image-choice">
      <legend>{label}</legend>
      {image ? (
        <div className="image-choice-row">
          <img src={image.small_url} alt="" />
          <span>{imageLabel(image)}</span>
          <span className="button-row">
            <button type="button" className="button button-ghost" onClick={() => setPicking(true)}>
              {t('Ändern')}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setEditing(true)}>
              {t('Bearbeiten')}
            </button>
            <button type="button" className="button button-ghost" onClick={() => onChange(null)}>
              {t('Entfernen')}
            </button>
          </span>
        </div>
      ) : (
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={() => setPicking(true)}>
            {t('Bild wählen')}
          </button>
        </div>
      )}
      {picking && (
        <ImagePicker
          images={images}
          unit={unit}
          title={label}
          onUploaded={onImagesChanged}
          onPick={(picked) => {
            setPicking(false)
            if (picked[0]) onChange(picked[0].id)
          }}
          onCancel={() => setPicking(false)}
        />
      )}
      {editing && image && (
        <ImageEditDialog
          id={image.id}
          units={units}
          onChanged={onImagesChanged}
          onClose={() => setEditing(false)}
        />
      )}
    </fieldset>
  )
}
