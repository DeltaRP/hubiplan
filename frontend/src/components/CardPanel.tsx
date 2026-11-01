// Mitgliedsausweis eines Mitglieds: QR-Code, Link, PDF, neu erzeugen, sperren.
import { useState } from 'react'
import type { ReactNode } from 'react'
import { cardApi } from '../api/cards.ts'
import type { CardAction, CardInfo } from '../api/cards.ts'
import { errorMessage, formatDateTime, useLoad } from './forms.ts'
import { Alert } from './ui.tsx'
import { confirmDialog } from './dialog.ts'
import type { ConfirmOptions } from './dialog.ts'
import { useTerms } from '../org/terms.ts'
import { t } from '../i18n/index.ts'

export function CardPanel({ base, pdfUrl }: { base: string; pdfUrl: string }) {
  const tm = useTerms()
  const { data, error, setData } = useLoad(() => cardApi.get(base), [base])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  async function run(action: CardAction, confirm?: ConfirmOptions, done?: string) {
    if (confirm && !(await confirmDialog(confirm))) return
    setBusy(true)
    setMessage(null)
    try {
      setData(await cardApi.act(base, action))
      if (done) setMessage({ kind: 'success', text: done })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>{t('Mitgliedsausweis')}</h2>
      {error && <Alert kind="error">{error}</Alert>}
      {!data ? (
        !error && <p className="muted">{t('Lädt …')}</p>
      ) : data.state === 'none' ? (
        <>
          <p className="muted">
            {t(
              'Noch kein Ausweis. Der QR-Code führt auf eine Seite mit Name, Foto (nur mit Einwilligung), aktuellem Status, {e_sg} und {sg}.',
              { e_sg: tm.e_sg, sg: tm.sg },
            )}
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => void run('create')}
          >
            {t('QR-Code erzeugen')}
          </button>
        </>
      ) : (
        <CardView
          card={data}
          pdfUrl={pdfUrl}
          busy={busy}
          onRenew={() =>
            void run(
              'renew',
              {
                title: t('Neuen QR-Code erzeugen?'),
                message: t('Der bisherige Code und alle Ausdrucke werden ungültig.'),
                confirmLabel: t('Neuen QR-Code erzeugen'),
              },
              t('Neuer QR-Code erzeugt. Der alte ist ungültig.'),
            )
          }
          onRevoke={() =>
            void run(
              'revoke',
              {
                title: t('Ausweis sperren?'),
                message: t('Beim Scannen erscheint dann „ungültig“.'),
                confirmLabel: t('Sperren'),
              },
              t('Ausweis gesperrt.'),
            )
          }
          onRestore={() => void run('restore', undefined, t('Ausweis wieder freigegeben.'))}
        />
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </div>
  )
}

function CardView({
  card,
  pdfUrl,
  busy,
  onRenew,
  onRevoke,
  onRestore,
}: {
  card: CardInfo
  pdfUrl: string
  busy: boolean
  onRenew: () => void
  onRevoke: () => void
  onRestore: () => void
}) {
  const revoked = card.state === 'revoked'
  return (
    <div className="card-qr-row">
      {card.qr && (
        <img
          src={card.qr}
          alt={t('QR-Code des Mitgliedsausweises')}
          className={`card-qr${revoked ? ' card-qr-revoked' : ''}`}
        />
      )}
      <div className="stack-sm">
        {revoked ? (
          <Alert kind="info">
            {t('Gesperrt seit')} {formatDateTime(card.revoked_at ?? '')}. Beim Scannen erscheint
            „ungültig“.
          </Alert>
        ) : (
          <p className="small">
            {t('Gültig seit')} {formatDateTime(card.issued_at ?? '')}
            <br />
            <a href={card.url} target="_blank" rel="noreferrer">
              {t('Seite nach dem Scan ansehen')}
            </a>
          </p>
        )}
        <div className="button-row">
          {!revoked && (
            <a className="button button-primary" href={pdfUrl}>
              {t('Ausweis als PDF')}
            </a>
          )}
          <button type="button" className="button button-ghost" disabled={busy} onClick={onRenew}>
            {t('Neuen QR-Code erzeugen')}
          </button>
          {revoked ? (
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={onRestore}
            >
              {t('Wieder freigeben')}
            </button>
          ) : (
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={onRevoke}
            >
              {t('Sperren')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** Eigener Ausweis im Mitgliederbereich (nur ansehen und drucken). */
export function OwnCardPanel({ accessId, empty }: { accessId: number; empty?: ReactNode }) {
  const tm = useTerms()
  const { data, error } = useLoad(() => cardApi.portal(accessId), [accessId])
  if (error) return empty ? <Alert kind="error">{error}</Alert> : null
  if (!data) return null
  if (data.state === 'none') return empty ?? null
  return (
    <div className="card card-wide">
      <h2>{t('Mein Mitgliedsausweis')}</h2>
      {data.state === 'revoked' ? (
        <Alert kind="info">
          {t('Dein Ausweis ist gesperrt. Bitte wende dich an {e_deinen}.', {
            e_deinen: tm.e_deinen,
          })}
        </Alert>
      ) : (
        <div className="card-qr-row">
          {data.qr && (
            <img src={data.qr} alt={t('QR-Code deines Mitgliedsausweises')} className="card-qr" />
          )}
          <div className="stack-sm">
            <p className="small">
              {t(
                'Zeig den QR-Code vor, wenn jemand deine Mitgliedschaft prüfen möchte. Wer ihn scannt, sieht deinen Namen, dein Foto (nur mit deiner Einwilligung), den aktuellen Status deiner Mitgliedschaft, {e_sg} und {sg}.',
                { e_sg: tm.e_sg, sg: tm.sg },
              )}
            </p>
            <div className="button-row">
              <a className="button button-primary" href={cardApi.portalPdfUrl(accessId)}>
                {t('Ausweis als PDF')}
              </a>
              <a className="button button-ghost" href={data.url} target="_blank" rel="noreferrer">
                {t('Seite ansehen')}
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
