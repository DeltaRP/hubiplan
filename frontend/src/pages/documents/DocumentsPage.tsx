// Dokumente: Ablage der aktiven Organisation, Abteilung oder des Mitgliederbereichs.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Route, Routes } from 'react-router-dom'
import { PERM } from '../../api/orgs.ts'
import { DEPT_PERM } from '../../api/portal.ts'
import { docApi, docBase, formatSize } from '../../api/documents.ts'
import type { DocBase, DocFolder, DocItem, DocOverview, Visibility } from '../../api/documents.ts'
import { StatutePanel } from '../../components/StatutePanel.tsx'
import { errorMessage, formatDate, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField, Tabs } from '../../components/ui.tsx'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { useOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { Why } from '../../learning/Aids.tsx'
import { RightsHint } from '../../components/RightsHint.tsx'
import { SubpageUnavailable } from '../NoticePages.tsx'
import { t, tn } from '../../i18n/index.ts'

const MAX_BYTES = 20 * 1024 * 1024
const ACCEPT =
  '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.ods,.jpg,.jpeg,.png,.txt,.csv,application/pdf,image/jpeg,image/png'

type Msg = { kind: 'error' | 'success'; text: string } | null

export function DocumentsPage() {
  const { active, activeDept, activePortal } = useOrg()
  let base: DocBase | null = null
  let title = t('Dokumente')
  let subtitle = ''
  let manage = false
  let orgId: number | null = null
  let canEditStatute = false
  if (
    active &&
    (active.type === 'club' || active.type === 'federation') &&
    active.permissions.includes(PERM.docsView)
  ) {
    base = docBase.org(active.id)
    subtitle = active.name
    manage = active.permissions.includes(PERM.docsManage)
    orgId = active.id
    canEditStatute = active.permissions.includes(PERM.orgEdit)
  } else if (activeDept) {
    base = docBase.dept(activeDept.id)
    title = t('Dokumente – {name}', { name: activeDept.name })
    subtitle = t('{label} · {club_name}', {
      label: activeDept.label,
      club_name: activeDept.club_name,
    })
    manage = activeDept.permissions.includes(DEPT_PERM.docsManage)
  } else if (activePortal) {
    return (
      <section>
        <div className="page-head">
          <h1>{t('Dokumente')}</h1>
          <p className="muted">{activePortal.club_name}</p>
        </div>
        <MemberDocuments base={docBase.portal(activePortal.id)} />
      </section>
    )
  }
  if (!base) {
    return (
      <section>
        <h1>{t('Dokumente')}</h1>
        <p className="muted">{t('Für diesen Bereich gibt es keine Dokumentenablage.')}</p>
      </section>
    )
  }
  const tabs = [
    { to: '/dokumente', label: t('Ablage') },
    ...(manage ? [{ to: '/dokumente/papierkorb', label: t('Papierkorb') }] : []),
  ]
  return (
    <section>
      <div className="page-head">
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {tabs.length > 1 && <Tabs items={tabs} />}
      <DocumentArea
        key={base}
        base={base}
        orgId={orgId}
        canEditStatute={canEditStatute}
        trash={manage}
      />
    </section>
  )
}

/** Ablage mit Auswahl der Abteilung (für Papierkorb und Ablage gemeinsam). */
function DocumentArea({
  base,
  orgId,
  canEditStatute,
  trash,
}: {
  base: DocBase
  orgId: number | null
  canEditStatute: boolean
  trash: boolean
}) {
  const { data, error, reload } = useLoad(() => docApi.overview(base), [base])
  return (
    <Routes>
      <Route
        index
        element={
          <>
            {error && <Alert kind="error">{error}</Alert>}
            {!data && !error && <p className="muted">{t('Lädt …')}</p>}
            {data && (
              <Library
                base={base}
                data={data}
                reload={reload}
                orgId={orgId}
                canEditStatute={canEditStatute}
              />
            )}
          </>
        }
      />
      {trash && <Route path="papierkorb" element={<TrashPanel base={base} />} />}
      <Route
        path="*"
        element={<SubpageUnavailable to="/dokumente" label={t('Zur Dokumentenablage')} />}
      />
    </Routes>
  )
}

function matches(doc: DocItem, query: string): boolean {
  if (!query) return true
  const q = query.toLocaleLowerCase('de')
  return (
    doc.title.toLocaleLowerCase('de').includes(q) || doc.note.toLocaleLowerCase('de').includes(q)
  )
}

function Library({
  base,
  data,
  reload,
  orgId,
  canEditStatute,
}: {
  base: DocBase
  data: DocOverview
  reload: () => Promise<void>
  orgId: number | null
  canEditStatute: boolean
}) {
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState<Msg>(null)
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [newVisibility, setNewVisibility] = useState<Visibility>('board')
  const [newShared, setNewShared] = useState(false)
  const tm = useTerms()
  const shareUp = data.share_up_label ?? null
  const manage = data.can_manage
  const visibilities = data.visibilities ?? []

  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      await reload()
      if (success) setMessage({ kind: 'success', text: success })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function createFolder(e: FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    await run(async () => {
      await docApi.createFolder(base, newName.trim(), newVisibility, newShared)
      setNewName('')
      setNewShared(false)
    }, t('Der Ordner wurde angelegt.'))
  }

  const ctx = { base, manage, busy, run, folders: data.folders, visibilities, setMessage, shareUp }
  const filtered = (f: DocFolder) => f.documents.filter((d) => matches(d, query))
  // Suche umfasst eigene, freigegebene Ordner und die festen Ordner (UX-Audit 31.10. W05)
  const allFolders = [...data.folders, ...(data.from_below ?? []), ...(data.shared ?? [])]
  const q = query.trim().toLocaleLowerCase('de')
  const fixedHit = (word: string) => !!orgId && !!q && (word.includes(q) || q.includes(word))
  const statuteHit = fixedHit('satzung')
  const feeRulesHit = fixedHit('beitragsordnung')
  const foundingDeedHit = fixedHit('gründungsurkunde') || fixedHit('gruendungsurkunde')
  const hits =
    allFolders.reduce((n, f) => n + filtered(f).length, 0) +
    (statuteHit ? 1 : 0) +
    (feeRulesHit ? 1 : 0) +
    (foundingDeedHit ? 1 : 0)
  const visible = (f: DocFolder) => !query || filtered(f).length > 0

  return (
    <div className="documents">
      <div className="documents-toolbar">
        <Field
          label={t('Suchen (Titel und Bemerkung, alle Ordner)')}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {data.used_bytes !== undefined && (
          <p className="muted small">
            {t('Belegter Platz:')} {formatSize(data.used_bytes)}
            {data.budget_bytes
              ? ` (Verein gesamt ${formatSize(data.total_bytes ?? 0)} von ${formatSize(data.budget_bytes)})`
              : ''}
            {data.trash_count
              ? t(' · {trash_count} im Papierkorb', { trash_count: data.trash_count })
              : ''}
          </p>
        )}
      </div>
      {data.budget_bytes && (data.total_bytes ?? 0) >= data.budget_bytes * 0.8 ? (
        <Alert kind="info">
          {t(
            'Der Speicherplatz der Ablage ist zu über 80 % belegt. Bitte alte Fassungen oder den Papierkorb leeren; mehr Platz gibt die Plattform-Verwaltung frei.',
          )}
        </Alert>
      ) : null}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}

      {query && (
        <p className="muted small" role="status">
          {hits === 0
            ? t(
                'Kein Dokument passt zur Suche (gesucht in allen eigenen und freigegebenen Ordnern).',
              )
            : tn(
                '{n} Treffer in eigenen und freigegebenen Ordnern.',
                '{n} Treffer in eigenen und freigegebenen Ordnern.',
                hits,
              )}
        </p>
      )}

      {orgId && (!query || statuteHit) && (
        <details className="doc-folder">
          <summary>
            <span className="doc-folder-name">{t('Satzung')}</span>
            <span className="badge">{t('fester Ordner')}</span>
          </summary>
          <StatutePanel orgId={orgId} heading="h3" />
          {!canEditStatute && (
            <p className="muted small">
              {t('Neue Fassungen lädt hoch, wer die Organisationsdaten bearbeiten darf.')}
            </p>
          )}
        </details>
      )}

      {orgId && (!query || feeRulesHit) && (
        <details className="doc-folder">
          <summary>
            <span className="doc-folder-name">{t('Beitragsordnung')}</span>
            <span className="badge">{t('fester Ordner')}</span>
          </summary>
          <StatutePanel orgId={orgId} heading="h3" kind="fee_rules" />
          {!canEditStatute && (
            <p className="muted small">
              {t('Neue Fassungen lädt hoch, wer die Organisationsdaten bearbeiten darf.')}
            </p>
          )}
        </details>
      )}

      {orgId && (!query || foundingDeedHit) && (
        <details className="doc-folder">
          <summary>
            <span className="doc-folder-name">{t('Gründungsurkunde')}</span>
            <span className="badge">{t('fester Ordner')}</span>
          </summary>
          <StatutePanel orgId={orgId} heading="h3" kind="founding_deed" />
          {!canEditStatute && (
            <p className="muted small">
              {t('Neue Fassungen lädt hoch, wer die Organisationsdaten bearbeiten darf.')}
            </p>
          )}
        </details>
      )}

      {data.folders.length === 0 && (
        <p className="muted">
          {manage
            ? t('Noch keine Ordner. Lege unten den ersten an, z. B. „Protokolle“ oder „Formulare“.')
            : t('Noch keine Dokumente.')}
        </p>
      )}
      {data.folders.map((f) =>
        query && filtered(f).length === 0 ? null : (
          <FolderView key={f.id} folder={f} docs={filtered(f)} open={!!query} {...ctx} />
        ),
      )}

      {manage && (
        <form className="inline-form doc-new-folder" onSubmit={createFolder}>
          <h3>{t('Neuer Ordner')}</h3>
          <div className="grid-3">
            <Field
              label={t('Name')}
              value={newName}
              maxLength={100}
              required
              onChange={(e) => setNewName(e.target.value)}
            />
            <SelectField
              label={t('Sichtbar für')}
              value={newVisibility}
              onChange={(e) => setNewVisibility(e.target.value as Visibility)}
            >
              {visibilities.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </SelectField>
          </div>
          {shareUp && <Checkbox label={shareUp} checked={newShared} onChange={setNewShared} />}
          <Why k="doc_visibility" />
          <button type="submit" className="button button-primary" disabled={busy}>
            {t('Ordner anlegen')}
          </button>
        </form>
      )}

      {data.from_below && data.from_below.some(visible) && (
        <section className="doc-shared" aria-label={t('Freigaben von unten')}>
          <h2>{t('Von den {pl_dat}', { pl_dat: tm.pl_dat })}</h2>
          <p className="muted small">{t('Diese Ordner sind für euch freigegeben (nur lesen).')}</p>
          {data.from_below.filter(visible).map((f) => (
            <FolderView
              key={`u${f.id}`}
              folder={f}
              docs={filtered(f)}
              open={!!query}
              {...ctx}
              manage={false}
              from={f.from}
            />
          ))}
        </section>
      )}

      {data.shared && data.shared.some(visible) && (
        <section className="doc-shared" aria-label={tm.dv_Vom}>
          <h2>{tm.dv_Vom}</h2>
          {data.shared.filter(visible).map((f) => (
            <FolderView
              key={`s${f.id}`}
              folder={f}
              docs={filtered(f)}
              open={!!query}
              {...ctx}
              manage={false}
              from={f.from}
            />
          ))}
        </section>
      )}
    </div>
  )
}

interface FolderCtx {
  base: DocBase
  manage: boolean
  busy: boolean
  run: (action: () => Promise<unknown>, success?: string) => Promise<void>
  folders: DocFolder[]
  visibilities: { value: Visibility; label: string }[]
  setMessage: (m: Msg) => void
  shareUp: string | null
}

function FolderView({
  folder,
  docs,
  open,
  from,
  ...ctx
}: FolderCtx & { folder: DocFolder; docs: DocItem[]; open: boolean; from?: string }) {
  const { base, manage, busy, run, visibilities, setMessage, shareUp } = ctx
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [note, setNote] = useState('')
  const [inputKey, setInputKey] = useState(0)

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    if (file.size > MAX_BYTES) {
      setMessage({ kind: 'error', text: t('Die Datei ist größer als 20 MB.') })
      return
    }
    await run(async () => {
      await docApi.upload(base, folder.id, file, {
        title: title.trim() || file.name.replace(/\.[^.]+$/, ''),
        date,
        note,
      })
      setFile(null)
      setTitle('')
      setDate('')
      setNote('')
      setInputKey((k) => k + 1)
    }, t('Das Dokument wurde hochgeladen.'))
  }

  async function rename() {
    const name = await promptDialog({
      title: t('Ordner umbenennen'),
      label: t('Name'),
      defaultValue: folder.name,
      confirmLabel: t('Umbenennen'),
      danger: false,
    })
    if (name && name.trim() && name.trim() !== folder.name) {
      await run(() => docApi.updateFolder(base, folder.id, { name: name.trim() }))
    }
  }

  async function remove() {
    if (folder.documents.length > 0) {
      setMessage({
        kind: 'error',
        text: t('Der Ordner ist nicht leer. Bitte zuerst die Dokumente verschieben oder löschen.'),
      })
      return
    }
    if (
      await confirmDialog({
        title: t('Ordner „{name}“ löschen?', { name: folder.name }),
        confirmLabel: t('Löschen'),
      })
    )
      await run(() => docApi.deleteFolder(base, folder.id), t('Der Ordner wurde gelöscht.'))
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setMessage({ kind: 'success', text: t('Link kopiert.') })
    } catch {
      setMessage({ kind: 'error', text: t('Kopieren ging nicht. Bitte den Link markieren.') })
    }
  }

  return (
    <details className="doc-folder" open={open || undefined}>
      <summary>
        <span className="doc-folder-name">{folder.name}</span>
        <span className="badge">{from ? t('von {from}', { from }) : folder.visibility_label}</span>
        {!from && folder.shared_up && <span className="badge">{t('nach oben freigegeben')}</span>}
        <span className="muted small">
          {' '}
          {tn('· {n} Dokument', '· {n} Dokumente', folder.documents.length)}
        </span>
      </summary>
      {manage && (
        <div className="doc-folder-tools">
          <SelectField
            label={t('Sichtbar für')}
            value={folder.visibility}
            disabled={busy}
            onChange={(e) =>
              void run(() =>
                docApi.updateFolder(base, folder.id, { visibility: e.target.value as Visibility }),
              )
            }
          >
            {visibilities.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </SelectField>
          {shareUp && (
            <Checkbox
              label={shareUp}
              checked={folder.shared_up}
              disabled={busy}
              onChange={(on) =>
                void run(() => docApi.updateFolder(base, folder.id, { shared_up: on }))
              }
            />
          )}
          <div className="button-row">
            <button type="button" className="button button-ghost" onClick={() => void rename()}>
              {t('Umbenennen')}
            </button>
            <button type="button" className="button button-danger" onClick={() => void remove()}>
              {t('Ordner löschen')}
            </button>
          </div>
          {folder.public_url && (
            <p className="statute-link small">
              {t('Öffentlicher Link (Liste als JSON, z. B. für die Webseite):')}{' '}
              <code>{folder.public_url}</code>{' '}
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void copy(folder.public_url!)}
              >
                {t('Link kopieren')}
              </button>
            </p>
          )}
        </div>
      )}
      {docs.length === 0 ? (
        <p className="muted small">{t('Keine Dokumente in diesem Ordner.')}</p>
      ) : (
        <ul className="statute-list doc-list">
          {docs.map((d) => (
            <DocumentRow key={d.id} doc={d} folder={folder} {...ctx} manage={manage} />
          ))}
        </ul>
      )}
      {manage && (
        <form onSubmit={upload} className="inline-form">
          <div className="grid-3">
            <label className="field">
              <span>{t('Datei (höchstens 20 MB)')}</span>
              <input
                key={inputKey}
                type="file"
                accept={ACCEPT}
                aria-label={t('Datei für {name}', { name: folder.name })}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <RightsHint />
            </label>
            <Field
              label={t('Titel')}
              value={title}
              maxLength={200}
              placeholder={file ? file.name.replace(/\.[^.]+$/, '') : ''}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Field
              label={t('Datum')}
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <Field
            label={t('Bemerkung (optional)')}
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="submit" className="button button-primary" disabled={busy || !file}>
            {t('Hochladen')}
          </button>
        </form>
      )}
    </details>
  )
}

/** Titel, Datum und Bemerkung eines Dokuments; speichert automatisch. */
function DocumentMetaForm({
  doc,
  base,
  onDone,
}: {
  doc: DocItem
  base: DocBase
  onDone: () => void
}) {
  const form = useForm({ title: doc.title, date: doc.date ?? '', note: doc.note })
  const auto = useAutoSave(form, (changes) =>
    docApi.update(base, doc.id, {
      ...changes,
      ...('date' in changes ? { date: changes.date || null } : {}),
    }),
  )
  const v = form.values
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault()
        void auto.flush().then((ok) => {
          if (ok) onDone()
        })
      }}
    >
      <SaveStatus auto={auto} />
      <div className="grid-3">
        <Field
          label={t('Titel')}
          value={v.title}
          required
          maxLength={200}
          error={form.errors.title}
          onChange={(e) => form.set('title', e.target.value)}
        />
        <Field
          label={t('Datum')}
          type="date"
          value={v.date}
          error={form.errors.date}
          onChange={(e) => form.set('date', e.target.value)}
        />
        <Field
          label={t('Bemerkung')}
          value={v.note}
          maxLength={500}
          error={form.errors.note}
          onChange={(e) => form.set('note', e.target.value)}
        />
      </div>
      <div className="button-row">
        <button type="submit" className="button button-ghost">
          {t('Schließen')}
        </button>
      </div>
    </form>
  )
}

function DocumentRow({ doc, folder, ...ctx }: FolderCtx & { doc: DocItem; folder: DocFolder }) {
  const { base, manage, busy, run, folders, setMessage } = ctx
  const [editing, setEditing] = useState(false)
  const [inputKey, setInputKey] = useState(0)
  const current = doc.current

  async function addVersion(file: File | undefined) {
    if (!file) return
    if (file.size > MAX_BYTES) {
      setMessage({ kind: 'error', text: t('Die Datei ist größer als 20 MB.') })
      return
    }
    await run(async () => {
      await docApi.addVersion(base, doc.id, file)
      setInputKey((k) => k + 1)
    }, t('Die neue Fassung wurde hochgeladen.'))
  }

  return (
    <li>
      <div className="doc-main">
        <strong>{doc.title}</strong>
        {doc.date && <span className="muted"> · {formatDate(doc.date)}</span>}
        {doc.note && <div className="muted small">{doc.note}</div>}
        {current && (
          <div className="muted small">
            {current.name} {t('· {x} · hochgeladen am', { x: formatSize(current.size) })}{' '}
            {formatDate(current.uploaded_at)}
            {current.uploaded_by && t(' von {uploaded_by}', { uploaded_by: current.uploaded_by })}
          </div>
        )}
        {doc.versions && doc.versions.length > 1 && (
          <details className="doc-versions">
            <summary className="small">
              {t('Ältere Fassungen ({n})', { n: doc.versions.length - 1 })}
            </summary>
            <ul>
              {doc.versions.slice(1).map((v) => (
                <li key={v.id} className="small">
                  <a href={v.url} target="_blank" rel="noreferrer">
                    {v.name}
                  </a>{' '}
                  <span className="muted">
                    · {formatSize(v.size)} · {formatDate(v.uploaded_at)}
                  </span>
                  {manage && (
                    <button
                      type="button"
                      className="button button-ghost"
                      disabled={busy}
                      onClick={async () => {
                        if (
                          await confirmDialog({
                            title: t('Fassung „{name}“ löschen?', { name: v.name }),
                            confirmLabel: t('Löschen'),
                          })
                        )
                          await run(
                            () => docApi.removeVersion(v.url),
                            t('Die Fassung wurde gelöscht.'),
                          )
                      }}
                    >
                      {t('Löschen')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
        {editing && (
          <DocumentMetaForm
            doc={doc}
            base={base}
            onDone={() => {
              setEditing(false)
              void run(async () => {})
            }}
          />
        )}
      </div>
      <div className="button-row">
        {current && (
          <a
            className="button button-ghost"
            href={current.inline ? current.url : `${current.url}?download=1`}
            target={current.inline ? '_blank' : undefined}
            rel="noreferrer"
          >
            {current.inline ? t('Ansehen') : t('Herunterladen')}
          </a>
        )}
        {manage && (
          <>
            <label className="button button-ghost doc-file-button">
              {t('Neue Fassung')}
              <input
                key={inputKey}
                type="file"
                accept={ACCEPT}
                className="file-input"
                aria-label={t('Neue Fassung von {title}', { title: doc.title })}
                onChange={(e) => void addVersion(e.target.files?.[0])}
              />
            </label>
            <button type="button" className="button button-ghost" onClick={() => setEditing(true)}>
              {t('Bearbeiten')}
            </button>
            {folders.length > 1 && (
              <select
                aria-label={t('{title} verschieben', { title: doc.title })}
                className="doc-move"
                value=""
                disabled={busy}
                onChange={(e) =>
                  e.target.value &&
                  void run(
                    () => docApi.update(base, doc.id, { folder: Number(e.target.value) }),
                    t('Das Dokument wurde verschoben.'),
                  )
                }
              >
                <option value="">{t('Verschieben …')}</option>
                {folders
                  .filter((f) => f.id !== folder.id)
                  .map((f) => (
                    <option key={f.id} value={f.id}>
                      {t('nach „{name}“', { name: f.name })}
                    </option>
                  ))}
              </select>
            )}
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={async () => {
                if (
                  await confirmDialog({
                    title: t('„{title}“ löschen?', { title: doc.title }),
                    message: t('Das Dokument kommt in den Papierkorb und bleibt dort 30 Tage.'),
                    confirmLabel: t('In den Papierkorb'),
                  })
                )
                  await run(
                    () => docApi.trashDocument(base, doc.id),
                    t('Das Dokument liegt jetzt im Papierkorb.'),
                  )
              }}
            >
              {t('Löschen')}
            </button>
          </>
        )}
      </div>
    </li>
  )
}

function TrashPanel({ base }: { base: DocBase }) {
  const { data, error, reload } = useLoad(() => docApi.trash(base), [base])
  const [message, setMessage] = useState<Msg>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      await reload()
      setMessage({ kind: 'success', text: success })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <div>
      <p className="muted small">
        {t(
          'Gelöschte Dokumente bleiben 30 Tage im Papierkorb und werden danach endgültig entfernt.',
        )}
      </p>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {data.length === 0 ? (
        <p className="muted">{t('Der Papierkorb ist leer.')}</p>
      ) : (
        <ul className="statute-list">
          {data.map((d) => (
            <li key={d.id}>
              <div>
                <strong>{d.title}</strong> <span className="muted">· {d.folder_name}</span>
                <div className="muted small">
                  {t('gelöscht am')} {d.deleted_at && formatDate(d.deleted_at)}
                  {d.deleted_by && t(' von {deleted_by}', { deleted_by: d.deleted_by })}
                </div>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={busy}
                  onClick={() =>
                    void run(() => docApi.restore(base, d.id), t('Das Dokument ist wieder da.'))
                  }
                >
                  {t('Wiederherstellen')}
                </button>
                <button
                  type="button"
                  className="button button-danger"
                  disabled={busy}
                  onClick={async () => {
                    if (
                      await confirmDialog({
                        title: t('„{title}“ endgültig löschen?', { title: d.title }),
                        message: t('Das lässt sich nicht rückgängig machen.'),
                        confirmLabel: t('Endgültig löschen'),
                      })
                    )
                      await run(() => docApi.purge(base, d.id), t('Das Dokument wurde gelöscht.'))
                  }}
                >
                  {t('Endgültig löschen')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Mitgliederbereich: freigegebene Dokumente des Vereins und der eigenen Abteilungen. */
function MemberDocuments({ base }: { base: DocBase }) {
  const { data, error } = useLoad(() => docApi.overview(base), [base])
  const [query, setQuery] = useState('')
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const folders = data.folders.filter((f) => f.documents.length > 0)
  if (folders.length === 0)
    return <p className="muted">{t('Für dich sind keine Dokumente freigegeben.')}</p>
  return (
    <div className="documents">
      <Field
        label={t('Suchen (Titel und Bemerkung)')}
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {folders.map((f) => {
        const docs = f.documents.filter((d) => matches(d, query))
        if (query && docs.length === 0) return null
        return (
          <section key={f.id} className="doc-member-folder">
            <h2>
              {f.name}
              {f.department && <span className="badge">{f.department}</span>}
            </h2>
            <ul className="statute-list">
              {docs.map((d) => (
                <li key={d.id}>
                  <div>
                    <strong>{d.title}</strong>
                    {d.date && <span className="muted"> · {formatDate(d.date)}</span>}
                    {d.note && <div className="muted small">{d.note}</div>}
                  </div>
                  {d.current && (
                    <a
                      className="button button-ghost"
                      href={d.current.inline ? d.current.url : `${d.current.url}?download=1`}
                      target={d.current.inline ? '_blank' : undefined}
                      rel="noreferrer"
                    >
                      {d.current.inline ? t('Ansehen') : t('Herunterladen')}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
