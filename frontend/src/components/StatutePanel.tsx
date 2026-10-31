// Abschnitt „Satzung“, „Beitragsordnung“ oder „Gründungsurkunde“:
// Fassungen hochladen und auflisten, öffentlicher Link.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { statuteApi } from '../api/statutes.ts'
import type { StatuteKind } from '../api/statutes.ts'
import { errorMessage, useLoad } from './forms.ts'
import { Alert, Checkbox, Field } from './ui.tsx'
import { confirmDialog } from './dialog.ts'

const MAX_BYTES = 20 * 1024 * 1024

function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** Bezeichnungen je Dokumentart; Beitragsordnung und Gründungsurkunde sind optional (Ralf 31.10.). */
const STATUTE_TEXTS: Record<
  StatuteKind,
  { title: string; none: string; uploaded: string; intro: string; date?: string; version?: string }
> = {
  statute: {
    title: 'Satzung',
    none: 'Noch keine Satzung hinterlegt.',
    uploaded: 'Die Satzung wurde hochgeladen.',
    intro:
      'Die Satzung hat in HUBIplan keine Funktion. Sie lässt sich hier ablegen und bei Bedarf öffentlich abrufen, z. B. für die eigene Webseite.',
  },
  fee_rules: {
    title: 'Beitragsordnung',
    none: 'Keine Beitragsordnung hinterlegt (optional).',
    uploaded: 'Die Beitragsordnung wurde hochgeladen.',
    intro:
      'Die Beitragsordnung ist freiwillig und hat in HUBIplan keine Funktion (die Beiträge selbst werden davon nicht berechnet). Sie lässt sich hier ablegen und bei Bedarf öffentlich abrufen, z. B. für die eigene Webseite.',
  },
  founding_deed: {
    title: 'Gründungsurkunde',
    none: 'Keine Gründungsurkunde hinterlegt (optional).',
    uploaded: 'Die Gründungsurkunde wurde hochgeladen.',
    intro:
      'Die Gründungsurkunde ist freiwillig und hat in HUBIplan keine Funktion. Sie lässt sich hier ablegen (z. B. als eingescannte PDF) und bei Bedarf öffentlich abrufen, etwa für die eigene Webseite.',
    date: 'ausgestellt am',
    version: 'Urkunde vom',
  },
}

export function StatutePanel({
  orgId,
  departmentId,
  heading = 'h2',
  kind = 'statute',
}: {
  orgId: number
  departmentId?: number
  heading?: 'h2' | 'h3'
  kind?: StatuteKind
}) {
  const texts = STATUTE_TEXTS[kind]
  const { data, error, setData, reload } = useLoad(
    () => statuteApi.list(orgId, departmentId, kind),
    [orgId, departmentId, kind],
  )
  const [file, setFile] = useState<File | null>(null)
  const [validFrom, setValidFrom] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [inputKey, setInputKey] = useState(0)
  const Heading = heading

  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      if (success) setMessage({ kind: 'success', text: success })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file || !validFrom) return
    if (file.size > MAX_BYTES) {
      setMessage({ kind: 'error', text: 'Die Datei ist größer als 20 MB.' })
      return
    }
    await run(async () => {
      setData(await statuteApi.upload(orgId, file, validFrom, note, departmentId, kind))
      setFile(null)
      setValidFrom('')
      setNote('')
      setInputKey((k) => k + 1)
    }, texts.uploaded)
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  const pub = data.publication

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setMessage({ kind: 'success', text: 'Link kopiert.' })
    } catch {
      setMessage({ kind: 'error', text: 'Kopieren ging nicht. Bitte den Link markieren.' })
    }
  }

  return (
    <section className="statute-panel" aria-label={texts.title}>
      <Heading>{texts.title}</Heading>
      <p className="muted small">{texts.intro}</p>
      {data.versions.length === 0 ? (
        <p className="muted">{texts.none}</p>
      ) : (
        <ul className="statute-list">
          {data.versions.map((v) => (
            <li key={v.id}>
              <div>
                <strong>
                  {texts.version ?? 'Fassung vom'} {formatDate(v.valid_from)}
                </strong>
                {v.is_current && <span className="badge"> aktuell</span>}
                {v.note && <span className="muted"> · {v.note}</span>}
                <div className="muted small">
                  {v.name} · {formatSize(v.size)} · hochgeladen am {formatDate(v.uploaded_at)}
                  {v.uploaded_by && ` von ${v.uploaded_by}`}
                </div>
              </div>
              <div className="button-row">
                <a className="button button-ghost" href={v.url} target="_blank" rel="noreferrer">
                  Ansehen
                </a>
                <a className="button button-ghost" href={`${v.url}?download=1`}>
                  Herunterladen
                </a>
                {data.can_manage && (
                  <button
                    type="button"
                    className="button button-danger"
                    disabled={busy}
                    onClick={async () => {
                      if (
                        await confirmDialog({
                          title: `Fassung vom ${formatDate(v.valid_from)} löschen?`,
                          confirmLabel: 'Löschen',
                        })
                      ) {
                        void run(async () => {
                          await statuteApi.remove(orgId, v.id)
                          await reload()
                        }, 'Die Fassung wurde gelöscht.')
                      }
                    }}
                  >
                    Löschen
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {data.can_manage && (
        <form onSubmit={upload} className="inline-form">
          <div className="grid-3">
            <label className="field">
              <span>PDF-Datei (höchstens 20 MB)</span>
              <input
                key={inputKey}
                type="file"
                accept="application/pdf,.pdf"
                required
                aria-label={`${texts.title} als PDF`}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <Field
              label={texts.date ?? 'gültig ab / beschlossen am'}
              type="date"
              required
              value={validFrom}
              onChange={(e) => setValidFrom(e.target.value)}
            />
            <Field
              label="Bemerkung (optional)"
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <button type="submit" className="button button-primary" disabled={busy || !file}>
            Neue Fassung hochladen
          </button>
        </form>
      )}

      <Checkbox
        label={`${texts.title} öffentlich abrufbar (ohne Anmeldung)`}
        checked={pub.is_public}
        disabled={!data.can_manage || busy}
        onChange={(on) =>
          void run(async () => {
            const next = await statuteApi.publish(orgId, on, departmentId, kind)
            setData({ ...data, publication: next })
          })
        }
      />
      {pub.is_public && pub.pdf_url && (
        <div className="statute-link">
          <code>{pub.pdf_url}</code>{' '}
          <button
            type="button"
            className="button button-ghost"
            onClick={() => void copyLink(pub.pdf_url!)}
          >
            Link kopieren
          </button>
          <p className="muted small">
            Der Link zeigt immer die aktuelle Fassung. Angaben zu allen Fassungen für Webseiten:{' '}
            {pub.info_url && (
              <a href={pub.info_url} target="_blank" rel="noreferrer">
                JSON
              </a>
            )}
          </p>
        </div>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </section>
  )
}
