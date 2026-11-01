// Datenschutzhinweise: Entwurf bearbeiten, prüfen, bewusst veröffentlichen
// (UI-Audit 29.10. NAF-02). Öffentlich gilt nur die veröffentlichte Fassung.
import { useState } from 'react'
import { confirmDialog } from './dialog.ts'
import { formatDateTime } from './forms.ts'
import { t } from '../i18n/index.ts'

/** Angaben in eckigen Klammern, die noch zu ergänzen sind. */
function openPlaceholders(text: string): string[] {
  return [...new Set(text.match(/\[[^\]\n]{2,160}\]/g) ?? [])]
}

export function PrivacyPublish({
  draft,
  publishedText,
  publishedAt,
  disabled,
  onPublish,
  onFill,
}: {
  draft: string
  publishedText: string | undefined
  publishedAt: string | null | undefined
  disabled?: boolean
  /** Speichert bei Bedarf den Entwurf und veröffentlicht ihn */
  onPublish: () => Promise<void>
  /** Offene Angabe direkt hier ausfüllen: bekommt den Entwurf mit eingesetztem Wert */
  onFill?: (next: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const open = openPlaceholders(draft)
  const changed = draft.trim() !== (publishedText ?? '').trim()

  async function publish() {
    const ok = await confirmDialog({
      title: t('Datenschutzhinweise veröffentlichen?'),
      message: open.length
        ? t(
            'Im Entwurf stehen noch {n} offene Angaben in eckigen Klammern: {x}. Erst ergänzen oder trotzdem veröffentlichen?',
            { n: open.length, x: open.join(', ') },
          )
        : t('Der Entwurf wird zur öffentlichen Fassung. Die bisherige Fassung wird ersetzt.'),
      confirmLabel: open.length ? t('Trotzdem veröffentlichen') : t('Veröffentlichen'),
      danger: open.length > 0,
    })
    if (!ok) return
    setBusy(true)
    try {
      await onPublish()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="subcard stack-sm">
      <p className="small" role="status">
        {publishedAt ? (
          <>
            <strong>{t('Veröffentlicht am {x}.', { x: formatDateTime(publishedAt) })}</strong>{' '}
            {changed
              ? t(
                  'Der Entwurf weicht davon ab; öffentlich gilt weiter die veröffentlichte Fassung.',
                )
              : t('Der Entwurf entspricht der veröffentlichten Fassung.')}
          </>
        ) : (
          <strong>
            {t('Noch nicht veröffentlicht: Öffentlich erscheinen noch keine Hinweise.')}
          </strong>
        )}
      </p>
      {open.length > 0 && (
        <div className="small">
          {t('Vor dem Veröffentlichen prüfen, noch offen:')}
          {onFill && !disabled ? (
            <ul className="placeholder-fill">
              {open.map((p) => (
                <PlaceholderInput
                  key={p}
                  placeholder={p}
                  onFill={(value) => onFill(draft.split(p).join(value))}
                />
              ))}
            </ul>
          ) : (
            <ul>
              {open.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={disabled || busy || !draft.trim() || !changed}
          onClick={() => void publish()}
        >
          {t('Datenschutzhinweise veröffentlichen')}
        </button>
      </div>
    </div>
  )
}

/** Eine offene Angabe: Feld zum Ausfüllen, „Einsetzen“ ersetzt sie überall im Entwurf. */
function PlaceholderInput({
  placeholder,
  onFill,
}: {
  placeholder: string
  onFill: (value: string) => void
}) {
  const [value, setValue] = useState('')
  const label = placeholder.slice(1, -1)
  const apply = () => {
    if (value.trim()) onFill(value.trim())
  }
  return (
    <li>
      <label className="placeholder-fill-row">
        <span>{label}</span>
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              apply()
            }
          }}
        />
      </label>
      <button
        type="button"
        className="button button-ghost"
        disabled={!value.trim()}
        onClick={apply}
        aria-label={t('{label} einsetzen', { label })}
      >
        {t('Einsetzen')}
      </button>
    </li>
  )
}
