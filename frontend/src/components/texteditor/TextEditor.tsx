// Editor für die Texte der Webseite: zeigt den Text so, wie er auf der Webseite
// erscheint (fett, Überschriften, Listen, Links, Bilder), gespeichert wird Markdown.
// Texte mit Gestaltung, die der Editor nicht darstellen kann (z. B. Tabellen),
// bearbeitet man in der Markdown-Ansicht; sie gehen dabei nicht verloren.
import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { baseKeymap, setBlockType, toggleMark } from 'prosemirror-commands'
import { history, redo, redoDepth, undo, undoDepth } from 'prosemirror-history'
import { inputRules, textblockTypeInputRule, wrappingInputRule } from 'prosemirror-inputrules'
import { keymap } from 'prosemirror-keymap'
import type { MarkType, Node as PmNode, NodeType } from 'prosemirror-model'
import { liftListItem, sinkListItem, splitListItem, wrapInList } from 'prosemirror-schema-list'
import { EditorState, TextSelection } from 'prosemirror-state'
import type { Command, Transaction } from 'prosemirror-state'
import { EditorView } from 'prosemirror-view'
import type { NodeViewConstructor } from 'prosemirror-view'
import 'prosemirror-view/style/prosemirror.css'
import type { LinkTarget, WebsiteImage } from '../../api/website.ts'
import { Modal } from '../Modal.tsx'
import { useImageCrop } from '../ImageCrop.tsx'
import { RightsHint } from '../RightsHint.tsx'
import { Alert, Field, SelectField } from '../ui.tsx'
import { errorMessage } from '../forms.ts'
import {
  IMAGE_PREFIX,
  PAGE_PREFIX,
  editorSchema as schema,
  normalizeHref,
  parseMarkdown,
  toMarkdown,
} from './markdown.ts'

const MODE_KEY = 'hubiplan.texteditor.markdown'

function rememberedMarkdownMode(): boolean {
  try {
    return localStorage.getItem(MODE_KEY) === '1'
  } catch {
    return false
  }
}

function rememberMarkdownMode(on: boolean) {
  try {
    if (on) localStorage.setItem(MODE_KEY, '1')
    else localStorage.removeItem(MODE_KEY)
  } catch {
    // ohne Speicher
  }
}

const n = schema.nodes
const m = schema.marks

function insertHardBreak(): Command {
  return (state, dispatch) => {
    dispatch?.(state.tr.replaceSelectionWith(n.hard_break.create()).scrollIntoView())
    return true
  }
}

function plugins(onLink: () => void) {
  return [
    history(),
    inputRules({
      rules: [
        wrappingInputRule(/^\s*([-+*])\s$/, n.bullet_list),
        wrappingInputRule(
          /^(\d+)\.\s$/,
          n.ordered_list,
          (match) => ({ order: Number(match[1]) }),
          (match, node) => node.childCount + node.attrs.order === Number(match[1]),
        ),
        textblockTypeInputRule(/^(#{2,3})\s$/, n.heading, (match) => ({
          level: match[1].length,
        })),
      ],
    }),
    keymap({
      'Mod-z': undo,
      'Mod-y': redo,
      'Shift-Mod-z': redo,
      'Mod-b': toggleMark(m.strong),
      'Mod-i': toggleMark(m.em),
      'Mod-k': () => {
        onLink()
        return true
      },
      Enter: splitListItem(n.list_item),
      'Mod-[': liftListItem(n.list_item),
      'Mod-]': sinkListItem(n.list_item),
      'Shift-Enter': insertHardBreak(),
    }),
    keymap(baseKeymap),
  ]
}

function markActive(state: EditorState, type: MarkType): boolean {
  const { from, $from, to, empty } = state.selection
  if (empty) return !!type.isInSet(state.storedMarks || $from.marks())
  return state.doc.rangeHasMark(from, to, type)
}

function blockLevel(state: EditorState): number {
  const parent = state.selection.$from.parent
  return parent.type === n.heading ? Number(parent.attrs.level) : 0
}

function listType(state: EditorState): NodeType | null {
  const { $from } = state.selection
  for (let d = $from.depth; d > 0; d--) {
    const type = $from.node(d).type
    if (type === n.bullet_list || type === n.ordered_list) return type
  }
  return null
}

/** Bereich des Links an der Auswahl (auch bei Cursor im Link). */
function linkRange(state: EditorState): { from: number; to: number; href: string } | null {
  const { $from, from, to, empty } = state.selection
  if (!empty) {
    let found: { from: number; to: number; href: string } | null = null
    state.doc.nodesBetween(from, to, (node, pos) => {
      const mark = m.link.isInSet(node.marks)
      if (mark && !found) found = { from: pos, to: pos + node.nodeSize, href: mark.attrs.href }
    })
    return found
  }
  const mark = m.link.isInSet($from.marks())
  if (!mark) return null
  // zusammenhängende Stücke mit diesem Link suchen, das mit dem Cursor nehmen
  const runs: { from: number; to: number }[] = []
  let open: { from: number; to: number } | null = null
  $from.parent.forEach((child, offset) => {
    if (mark.isInSet(child.marks)) {
      if (open) open.to = offset + child.nodeSize
      else open = { from: offset, to: offset + child.nodeSize }
    } else if (open) {
      runs.push(open)
      open = null
    }
  })
  if (open) runs.push(open)
  const at = $from.parentOffset
  const run = runs.find((r) => r.from <= at && at <= r.to)
  if (!run) return null
  const base = $from.start()
  return { from: base + run.from, to: base + run.to, href: mark.attrs.href }
}

function imageLabel(i: WebsiteImage): string {
  return i.caption || i.alt_text || `Bild ${i.key}`
}

function makeState(doc: PmNode, onLink: () => void): EditorState {
  return EditorState.create({ doc, plugins: plugins(onLink) })
}

/** Bilder im Text: Vorschaubild aus HUBIplan statt bild:<schlüssel> */
function makeNodeViews(
  images: () => WebsiteImage[] | undefined,
): Record<string, NodeViewConstructor> {
  return {
    image: (node: PmNode) => {
      const img = document.createElement('img')
      const src = String(node.attrs.src || '')
      const key = src.startsWith(IMAGE_PREFIX) ? src.slice(IMAGE_PREFIX.length) : ''
      const image = images()?.find((i) => i.key === key)
      if (image) img.src = image.small_url
      // Die Webseite zeigt den aktuellen Alternativtext des Bildes, nicht den beim
      // Einfügen in den Text geschriebenen
      const current = image ? image.alt_text || (image.decorative ? '' : image.caption) : ''
      const alt = current || String(node.attrs.alt || '')
      const ok = !!alt || !!image?.decorative
      img.alt = alt || (image ? imageLabel(image) : 'Bild')
      img.className = ok ? 'texteditor-image' : 'texteditor-image texteditor-image-noalt'
      img.title = ok
        ? alt
        : 'Ohne Beschreibung für blinde Besucher; unter Webseite › Bilder ergänzen.'
      return { dom: img }
    },
  }
}

export interface TextEditorProps {
  label: string
  value: string
  onChange: (markdown: string) => void
  error?: string
  hint?: ReactNode
  /** Bilder der Webseite zum Einfügen (ohne: kein Bild-Knopf) */
  images?: WebsiteImage[]
  /** Bild hochladen; liefert das neue Bild */
  onUploadImage?: (file: File, alt: string) => Promise<WebsiteImage>
  /** Eigener Auswahl-Dialog statt der einfachen Bilderliste (Webseite › Texte) */
  renderImagePicker?: (insert: (image: WebsiteImage) => void, cancel: () => void) => ReactNode
  /** Seiten der eigenen Webseite für den Link-Dialog */
  linkTargets?: LinkTarget[]
  /** Mindesthöhe in Zeilen */
  rows?: number
}

type ToolKey =
  | 'undo'
  | 'redo'
  | 'h2'
  | 'h3'
  | 'strong'
  | 'em'
  | 'bullet'
  | 'ordered'
  | 'link'
  | 'image'
  | 'source'

export function TextEditor({
  label,
  value,
  onChange,
  error,
  hint,
  images,
  onUploadImage,
  renderImagePicker,
  linkTargets,
  rows = 8,
}: TextEditorProps) {
  const labelId = useId()
  const noteId = useId()
  const sourceId = useId()
  const [dialog, setDialog] = useState<'link' | 'image' | null>(null)
  const openLink = () => setDialog('link')
  // Zustand des Editors; null, wenn der Text nur als Markdown geht
  const [pm, setPm] = useState<EditorState | null>(() => {
    const doc = parseMarkdown(value)
    return doc ? makeState(doc, () => setDialog('link')) : null
  })
  const [unsupported, setUnsupported] = useState(pm === null)
  const [markdownMode, setMarkdownMode] = useState(() => pm === null || rememberedMarkdownMode())
  // zuletzt gemeldeter oder übernommener Text (Änderungen von außen erkennen)
  const [known, setKnown] = useState(value)
  const [focusKey, setFocusKey] = useState<ToolKey>('strong')

  // Text von außen geändert (z. B. frühere Fassung zurückgeholt)
  if (value !== known) {
    setKnown(value)
    const doc = parseMarkdown(value)
    if (doc) {
      setPm(makeState(doc, openLink))
    } else {
      setPm(null)
      setUnsupported(true)
      setMarkdownMode(true)
    }
  }

  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const knownRef = useRef(known)
  const pmRef = useRef(pm)
  const onChangeRef = useRef(onChange)
  const imagesRef = useRef(images)
  useEffect(() => {
    onChangeRef.current = onChange
    imagesRef.current = images
    knownRef.current = known
    pmRef.current = pm
  })

  // Editor anlegen (nur in der formatierten Ansicht)
  useEffect(() => {
    if (markdownMode || !host.current) return
    const start =
      pmRef.current ?? makeState(schema.topNodeType.createAndFill()!, () => setDialog('link'))
    const v = new EditorView(host.current, {
      state: start,
      nodeViews: makeNodeViews(() => imagesRef.current),
      dispatchTransaction(tr: Transaction) {
        const next = v.state.apply(tr)
        v.updateState(next)
        pmRef.current = next
        setPm(next)
        if (tr.docChanged) {
          const md = toMarkdown(next.doc)
          if (md !== knownRef.current) {
            knownRef.current = md
            setKnown(md)
            onChangeRef.current(md)
          }
        }
      },
    })
    view.current = v
    return () => {
      v.destroy()
      view.current = null
    }
  }, [markdownMode])

  // Zustand von außen (neuer Text) in den Editor übernehmen
  useEffect(() => {
    const v = view.current
    if (v && pm && v.state !== pm) v.updateState(pm)
  }, [pm])

  // Beschriftung und Fehler am Eingabebereich
  useEffect(() => {
    view.current?.setProps({
      attributes: {
        class: 'texteditor-content',
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-labelledby': labelId,
        ...(error || hint ? { 'aria-describedby': noteId } : {}),
        ...(error ? { 'aria-invalid': 'true' } : {}),
        style: `min-height: ${rows * 1.5}em`,
      },
    })
  }, [error, hint, labelId, noteId, rows, markdownMode])

  // Neue Bilderliste: Bilder im Text neu zeichnen
  useEffect(() => {
    view.current?.setProps({ nodeViews: makeNodeViews(() => imagesRef.current) })
  }, [images])

  const state = markdownMode ? null : pm

  function run(command: Command) {
    const v = view.current
    if (!v) return
    command(v.state, v.dispatch, v)
    v.focus()
  }

  function toggleHeading(level: number) {
    if (!state) return
    run(
      blockLevel(state) === level ? setBlockType(n.paragraph) : setBlockType(n.heading, { level }),
    )
  }

  function toggleList(type: NodeType) {
    if (!state) return
    const current = listType(state)
    if (current === type) {
      run(liftListItem(n.list_item))
      return
    }
    if (current) {
      // andere Listenart: Liste umwandeln
      run((s, dispatch) => {
        const { $from } = s.selection
        for (let d = $from.depth; d > 0; d--) {
          if ($from.node(d).type === current) {
            dispatch?.(s.tr.setNodeMarkup($from.before(d), type))
            return true
          }
        }
        return false
      })
      return
    }
    run(wrapInList(type))
  }

  function applyLink(href: string | null) {
    const v = view.current
    setDialog(null)
    if (!v) return
    const s = v.state
    const range = linkRange(s)
    let tr = s.tr
    if (href === null) {
      if (range) tr = tr.removeMark(range.from, range.to, m.link)
    } else {
      const mark = m.link.create({ href })
      if (s.selection.empty && !range) {
        const target = linkTargets?.find((tm) => tm.href === href)
        const text = target ? target.label.replace(/ \(noch nicht veröffentlicht\)$/, '') : href
        const from = s.selection.from
        tr = tr.insertText(text, from).addMark(from, from + text.length, mark)
        tr = tr.setSelection(TextSelection.create(tr.doc, from + text.length))
      } else if (s.selection.empty && range) {
        tr = tr.removeMark(range.from, range.to, m.link).addMark(range.from, range.to, mark)
      } else {
        tr = tr.removeMark(s.selection.from, s.selection.to, m.link)
        tr = tr.addMark(s.selection.from, s.selection.to, mark)
      }
    }
    v.dispatch(tr)
    v.focus()
  }

  function closeDialog() {
    setDialog(null)
    view.current?.focus()
  }

  function insertImage(image: WebsiteImage) {
    const v = view.current
    setDialog(null)
    if (!v) return
    const node = n.image.create({
      src: `${IMAGE_PREFIX}${image.key}`,
      alt: image.alt_text || image.caption || null,
    })
    v.dispatch(v.state.tr.replaceSelectionWith(node).scrollIntoView())
    v.focus()
  }

  function switchMode() {
    if (markdownMode) {
      const doc = parseMarkdown(known)
      if (doc === null) {
        setUnsupported(true)
        return
      }
      setPm(makeState(doc, openLink))
      setUnsupported(false)
      setMarkdownMode(false)
      rememberMarkdownMode(false)
    } else {
      setMarkdownMode(true)
      rememberMarkdownMode(true)
    }
  }

  // Werkzeugleiste: ein Tab-Stopp, Pfeiltasten wandern (WAI-ARIA toolbar)
  const tools: {
    key: ToolKey
    label: string
    text: ReactNode
    pressed?: boolean
    disabled?: boolean
    gapBefore?: boolean
  }[] = markdownMode
    ? []
    : [
        {
          key: 'undo',
          label: 'Rückgängig (Strg+Z)',
          text: '↶',
          disabled: !state || undoDepth(state) === 0,
        },
        {
          key: 'redo',
          label: 'Wiederholen (Strg+Y)',
          text: '↷',
          disabled: !state || redoDepth(state) === 0,
        },
        {
          key: 'h2',
          label: 'Überschrift',
          text: 'Ü1',
          pressed: !!state && blockLevel(state) === 2,
          gapBefore: true,
        },
        {
          key: 'h3',
          label: 'Zwischenüberschrift',
          text: 'Ü2',
          pressed: !!state && blockLevel(state) === 3,
        },
        {
          key: 'strong',
          label: 'Fett (Strg+B)',
          text: <strong>F</strong>,
          pressed: !!state && markActive(state, m.strong),
          gapBefore: true,
        },
        {
          key: 'em',
          label: 'Kursiv (Strg+I)',
          text: <em>K</em>,
          pressed: !!state && markActive(state, m.em),
        },
        {
          key: 'bullet',
          label: 'Aufzählung',
          text: '• Liste',
          pressed: !!state && listType(state) === n.bullet_list,
          gapBefore: true,
        },
        {
          key: 'ordered',
          label: 'Nummerierte Liste',
          text: '1. Liste',
          pressed: !!state && listType(state) === n.ordered_list,
        },
        {
          key: 'link',
          label: 'Link (Strg+K)',
          text: 'Link',
          pressed: !!state && !!linkRange(state),
          gapBefore: true,
        },
        ...(images
          ? [
              {
                key: 'image' as const,
                label: 'Bild einfügen',
                text: 'Bild',
              },
            ]
          : []),
      ]
  tools.push({
    key: 'source',
    label: 'Markdown anzeigen',
    text: 'Markdown',
    pressed: markdownMode,
    gapBefore: !markdownMode,
  })
  function act(key: ToolKey) {
    if (key === 'undo') run(undo)
    else if (key === 'redo') run(redo)
    else if (key === 'h2') toggleHeading(2)
    else if (key === 'h3') toggleHeading(3)
    else if (key === 'strong') run(toggleMark(m.strong))
    else if (key === 'em') run(toggleMark(m.em))
    else if (key === 'bullet') toggleList(n.bullet_list)
    else if (key === 'ordered') toggleList(n.ordered_list)
    else if (key === 'link') setDialog('link')
    else if (key === 'image') setDialog('image')
    else switchMode()
  }

  const enabled = tools.filter((tm) => !tm.disabled)
  const tabStop = enabled.some((tm) => tm.key === focusKey) ? focusKey : enabled[0]?.key

  function onToolbarKey(e: KeyboardEvent<HTMLDivElement>) {
    const keys = enabled.map((tm) => tm.key)
    const index = keys.indexOf(tabStop!)
    let next = -1
    if (e.key === 'ArrowRight') next = (index + 1) % keys.length
    else if (e.key === 'ArrowLeft') next = (index - 1 + keys.length) % keys.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = keys.length - 1
    if (next < 0) return
    e.preventDefault()
    setFocusKey(keys[next])
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-tool="${keys[next]}"]`)?.focus()
  }

  const currentLink = state ? linkRange(state) : null

  return (
    <div className={`field texteditor${error ? ' field-invalid' : ''}`}>
      <span id={labelId}>{label}</span>
      <div
        className="texteditor-toolbar"
        role="toolbar"
        aria-label={`Formatierung: ${label}`}
        aria-controls={markdownMode ? sourceId : undefined}
        onKeyDown={onToolbarKey}
      >
        {tools.map((tm) => (
          <button
            key={tm.key}
            type="button"
            data-tool={tm.key}
            className={tm.gapBefore ? 'texteditor-gap' : undefined}
            aria-label={tm.label}
            title={tm.label}
            aria-pressed={tm.pressed === undefined ? undefined : tm.pressed}
            disabled={tm.disabled}
            tabIndex={tm.key === tabStop ? 0 : -1}
            // Auswahl im Text behalten
            onMouseDown={(e) => e.preventDefault()}
            onFocus={() => setFocusKey(tm.key)}
            onClick={() => act(tm.key)}
          >
            {tm.text}
          </button>
        ))}
      </div>
      {unsupported && (
        <p className="small muted" role="status">
          Dieser Text enthält Gestaltung, die der Editor nicht anzeigen kann (z. B. eine Tabelle).
          Du bearbeitest ihn deshalb als Markdown; dabei geht nichts verloren.
        </p>
      )}
      {markdownMode ? (
        <textarea
          id={sourceId}
          aria-labelledby={labelId}
          aria-describedby={error || hint ? noteId : undefined}
          aria-invalid={!!error}
          rows={Math.max(rows, 6)}
          value={value}
          onChange={(e) => {
            setKnown(e.target.value)
            onChange(e.target.value)
          }}
        />
      ) : (
        <div ref={host} className="texteditor-frame" />
      )}
      {error ? (
        <small id={noteId} className="field-error">
          {error}
        </small>
      ) : hint ? (
        <small id={noteId} className="muted">
          {hint}
        </small>
      ) : null}
      {dialog === 'link' && (
        <LinkDialog
          current={currentLink?.href ?? ''}
          targets={linkTargets ?? []}
          onCancel={() => {
            setDialog(null)
            view.current?.focus()
          }}
          onApply={applyLink}
        />
      )}
      {dialog === 'image' && renderImagePicker && (
        <PickerSlot render={renderImagePicker} onPick={insertImage} onCancel={closeDialog} />
      )}
      {dialog === 'image' && !renderImagePicker && (
        <ImageDialog
          images={images ?? []}
          onUpload={onUploadImage}
          onCancel={() => {
            setDialog(null)
            view.current?.focus()
          }}
          onPick={insertImage}
        />
      )}
    </div>
  )
}

/** Eigener Auswahl-Dialog (renderImagePicker) als Bestandteil */
function PickerSlot({
  render,
  onPick,
  onCancel,
}: {
  render: NonNullable<TextEditorProps['renderImagePicker']>
  onPick: (image: WebsiteImage) => void
  onCancel: () => void
}) {
  return <>{render(onPick, onCancel)}</>
}

function LinkDialog({
  current,
  targets,
  onCancel,
  onApply,
}: {
  current: string
  targets: LinkTarget[]
  onCancel: () => void
  /** null: Link entfernen */
  onApply: (href: string | null) => void
}) {
  const isPage = current.startsWith(PAGE_PREFIX)
  const [kind, setKind] = useState<'page' | 'url'>(
    isPage || (!current && targets.length > 0) ? 'page' : 'url',
  )
  const [page, setPage] = useState(isPage ? current : '')
  const [url, setUrl] = useState(isPage ? '' : current)
  const [error, setError] = useState<string | null>(null)
  const pageOptions =
    isPage && !targets.some((tm) => tm.href === current)
      ? [...targets, { href: current, label: `${current.slice(PAGE_PREFIX.length)} (unbekannt)` }]
      : targets

  function submit() {
    if (kind === 'page') {
      if (!page) {
        setError('Bitte eine Seite wählen.')
        return
      }
      onApply(page)
      return
    }
    const href = normalizeHref(url)
    if (!href) {
      setError('Bitte eine Adresse wie https://www.beispiel.de oder name@beispiel.de angeben.')
      return
    }
    onApply(href)
  }

  return (
    <Modal title={current ? 'Link ändern' : 'Link einfügen'} onClose={onCancel}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          e.stopPropagation()
          submit()
        }}
      >
        {targets.length > 0 && (
          <fieldset className="texteditor-linkkind">
            <legend>Ziel</legend>
            <label>
              <input
                type="radio"
                name="ziel"
                checked={kind === 'page'}
                onChange={() => setKind('page')}
              />{' '}
              Seite unserer Webseite
            </label>
            <label>
              <input
                type="radio"
                name="ziel"
                checked={kind === 'url'}
                onChange={() => setKind('url')}
              />{' '}
              andere Adresse oder E-Mail
            </label>
          </fieldset>
        )}
        {kind === 'page' && targets.length > 0 ? (
          <SelectField label="Seite" value={page} onChange={(e) => setPage(e.target.value)}>
            <option value="">Seite wählen …</option>
            {pageOptions.map((tm) => (
              <option key={tm.href} value={tm.href}>
                {tm.label}
              </option>
            ))}
          </SelectField>
        ) : (
          <Field
            label="Adresse (https://… oder E-Mail)"
            value={url}
            autoFocus
            onChange={(e) => setUrl(e.target.value)}
          />
        )}
        {error && <Alert kind="error">{error}</Alert>}
        <div className="button-row">
          <button type="submit" className="button button-primary">
            {current ? 'Übernehmen' : 'Einfügen'}
          </button>
          {current && (
            <button type="button" className="button button-ghost" onClick={() => onApply(null)}>
              Link entfernen
            </button>
          )}
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        </div>
      </form>
    </Modal>
  )
}

function ImageDialog({
  images,
  onUpload,
  onCancel,
  onPick,
}: {
  images: WebsiteImage[]
  onUpload?: (file: File, alt: string) => Promise<WebsiteImage>
  onCancel: () => void
  onPick: (image: WebsiteImage) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const crop = useImageCrop()
  const [alt, setAlt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function upload() {
    if (!file || !onUpload) return
    setBusy(true)
    setError(null)
    try {
      onPick(await onUpload(file, alt.trim()))
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <Modal title="Bild einfügen" onClose={onCancel}>
      {images.length === 0 ? (
        <p className="muted">Noch keine Bilder hochgeladen.</p>
      ) : (
        <ul className="texteditor-images">
          {images.map((i) => (
            <li key={i.id}>
              <button type="button" onClick={() => onPick(i)}>
                <img src={i.small_url} alt="" width={120} />
                <span>{imageLabel(i)}</span>
                {!i.alt_text && !i.decorative && (
                  <small className="field-error">ohne Beschreibung</small>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {onUpload && (
        <fieldset className="texteditor-upload">
          <legend>Neues Bild hochladen</legend>
          <label className="field">
            <span>Datei</span>
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
            maxLength={300}
            hint={
              file && !alt.trim()
                ? 'Ohne Beschreibung erfahren blinde Besucher nicht, was auf dem Bild zu sehen ist.'
                : undefined
            }
            onChange={(e) => setAlt(e.target.value)}
          />
          {error && <Alert kind="error">{error}</Alert>}
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={!file || busy}
              onClick={() => void upload()}
            >
              Hochladen und einfügen
            </button>
          </div>
        </fieldset>
      )}
    </Modal>
  )
}
