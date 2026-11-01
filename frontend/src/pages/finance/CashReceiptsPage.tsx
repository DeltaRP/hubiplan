// Quittungen mit Unterschrift: vorbereiten, beide unterschreiben lassen (Gegenseite im
// Vollbild auf dem Telefon), abschließen mit Belegnummer aus dem Kassenbuch.
// Konzept: konzepte/digitale-quittung.md
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { newRequestKey } from '../../api/client.ts'
import { euro, financeApi, parseAmount } from '../../api/finance.ts'
import type {
  CashReceipt,
  CashReceiptInput,
  SignatureInput,
  SignatureRole,
} from '../../api/finance.ts'
import type { MemberRow } from '../../api/members.ts'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { SignatureFullscreen, SignatureImage } from '../../components/SignaturePad.tsx'
import { Alert, Checkbox, Field, SelectField } from '../../components/ui.tsx'
import { ApiError } from '../../api/client.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { Term, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

export function CashReceiptsArea({ canEdit }: { canEdit: boolean }) {
  return (
    <Routes>
      <Route index element={<CashReceiptList canEdit={canEdit} />} />
      <Route
        path="neu"
        element={canEdit ? <CashReceiptForm /> : <CashReceiptList canEdit={false} />}
      />
      <Route path=":id" element={<CashReceiptDetail canEdit={canEdit} />} />
    </Routes>
  )
}

function CashReceiptList({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const { data, error } = useLoad(() => financeApi.cashReceipts(org.id), [org.id])
  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>
          <Term k="cash_receipt">{t('Quittungen')}</Term>
        </h2>
        {canEdit && (
          <Link className="button button-primary" to="/finanzen/quittungen/neu">
            {t('Quittung ausstellen')}
          </Link>
        )}
      </div>
      <p className="muted small">
        {t(
          'Für Barzahlungen: Du bereitest die Quittung vor, beide unterschreiben auf dem Bildschirm, und beim Abschluss bekommt sie die Belegnummer aus dem Kassenbuch. Das PDF hängt dann als Beleg an der Buchung.',
        )}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">{t('Lädt …')}</p>}
      {data && data.results.length === 0 && <p className="muted">{t('Noch keine Quittungen.')}</p>}
      {data && data.results.length > 0 && (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{t('Beleg-Nr.')}</th>
                <th>{t('Datum')}</th>
                <th>{t('Richtung')}</th>
                <th>{t('Gegenseite')}</th>
                <th className="num">{t('Betrag')}</th>
                <th>{t('Status')}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/finanzen/quittungen/${r.id}`}>{r.number || t('Entwurf')}</Link>
                  </td>
                  <td>{r.receipt_date ? formatDate(r.receipt_date) : '–'}</td>
                  <td>{r.direction === 'in' ? 'erhalten' : 'ausgezahlt'}</td>
                  <td>{r.counterparty_name}</td>
                  <td className="num">{euro(r.amount)}</td>
                  <td>{r.status_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const EMPTY: CashReceiptInput = {
  direction: 'out',
  counterparty_name: '',
  counterparty_address: '',
  membership: null,
  email: '',
  amount: '',
  purpose: '',
  vat_rate: null,
  account: null,
  category: null,
  project: null,
}

function useChoices(orgId: number) {
  return useLoad(
    () => Promise.all([financeApi.accounts(orgId), financeApi.categories(orgId)]),
    [orgId],
  )
}

/** Schritt 1: Quittung vorbereiten (Richtung, Gegenseite, Betrag, Zweck). */
function CashReceiptForm({
  initial,
  onSaved,
}: {
  initial?: CashReceipt
  onSaved?: (r: CashReceipt) => void
}) {
  const org = useActiveOrg()
  const navigate = useNavigate()
  const choices = useChoices(org.id)
  const [v, setV] = useState<CashReceiptInput>(initial ?? EMPTY)
  const [amountText, setAmountText] = useState(initial ? initial.amount.replace('.', ',') : '')
  const [member, setMember] = useState<MemberRow | null>(null)
  const [vat, setVat] = useState(!!initial?.vat_rate)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof CashReceiptInput>(k: K, value: CashReceiptInput[K]) =>
    setV((x) => ({ ...x, [k]: value }))

  const [accounts, categories] = choices.data ?? [[], []]
  const cash = accounts.filter((a) => a.kind === 'cash' && a.is_active)
  const kind = v.direction === 'in' ? 'income' : 'expense'
  const cats = categories.filter((c) => c.is_active && (c.kind === kind || c.kind === 'both'))
  const fromInvoice = !!initial?.invoice

  // Einzige Barkasse vorwählen
  useEffect(() => {
    if (v.account === null && cash.length === 1) set('account', cash[0].id)
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [cash.length])

  function pickMember(m: MemberRow | null) {
    setMember(m)
    set('membership', m?.id ?? null)
    if (m) set('counterparty_name', `${m.first_name} ${m.last_name}`.trim())
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    setMessage(null)
    const data = { ...v, amount: parseAmount(amountText), vat_rate: vat ? v.vat_rate : null }
    try {
      const saved = initial
        ? await financeApi.updateCashReceipt(org.id, initial.id, data)
        : await financeApi.createCashReceipt(org.id, data)
      if (onSaved) onSaved(saved)
      else navigate(`/finanzen/quittungen/${saved.id}`, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors)
      setMessage(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (choices.error) return <Alert kind="error">{choices.error}</Alert>
  if (!choices.data) return <p className="muted">{t('Lädt …')}</p>
  if (cash.length === 0)
    return (
      <Alert kind="info">
        {t('Für Quittungen braucht es eine Barkasse. Lege sie unter')}{' '}
        <Link to="/finanzen/einstellungen/konten">{t('Einrichtung › Konten')}</Link>{' '}
        {t('an (Art „Barkasse“).')}
      </Alert>
    )

  return (
    <form className="card receipt-form" onSubmit={submit}>
      <h2>{initial ? t('Quittung ändern') : t('Quittung ausstellen')}</h2>
      {!fromInvoice && (
        <div className="segmented" role="group" aria-label={t('Richtung')}>
          <button
            type="button"
            className={`button button-ghost${v.direction === 'in' ? ' is-active' : ''}`}
            aria-pressed={v.direction === 'in'}
            onClick={() => {
              set('direction', 'in')
              set('category', null)
            }}
          >
            {t('Verein erhält Geld')}
          </button>
          <button
            type="button"
            className={`button button-ghost${v.direction === 'out' ? ' is-active' : ''}`}
            aria-pressed={v.direction === 'out'}
            onClick={() => {
              set('direction', 'out')
              set('category', null)
            }}
          >
            {t('Verein zahlt aus')}
          </button>
        </div>
      )}
      {!fromInvoice && <MemberPicker orgId={org.id} value={member} onChange={pickMember} />}
      <Field
        label={v.direction === 'in' ? t('Zahler (Name)') : t('Empfänger (Name)')}
        value={v.counterparty_name}
        onChange={(e) => set('counterparty_name', e.target.value)}
        error={errors.counterparty_name}
        required
        maxLength={200}
      />
      <label className="field">
        <span>{t('Anschrift (optional)')}</span>
        <textarea
          rows={2}
          value={v.counterparty_address}
          onChange={(e) => set('counterparty_address', e.target.value)}
          maxLength={500}
        />
      </label>
      <Field
        label={t('Betrag in €')}
        inputMode="decimal"
        value={amountText}
        onChange={(e) => setAmountText(e.target.value)}
        error={errors.amount}
        disabled={fromInvoice}
        required
      />
      <Field
        label={t('Zweck')}
        value={v.purpose}
        onChange={(e) => set('purpose', e.target.value)}
        error={errors.purpose}
        required
        maxLength={200}
        hint={t('z. B. Auslagen Kranzniederlegung')}
      />
      {cash.length > 1 && (
        <SelectField
          label={t('Barkasse')}
          value={v.account ?? ''}
          onChange={(e) => set('account', e.target.value ? Number(e.target.value) : null)}
          error={errors.account}
          required
        >
          <option value="">{t('bitte wählen')}</option>
          {cash.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </SelectField>
      )}
      {errors.account && cash.length <= 1 && <Alert kind="error">{errors.account}</Alert>}
      {!fromInvoice && (
        <SelectField
          label={t('Kategorie')}
          value={v.category ?? ''}
          onChange={(e) => set('category', e.target.value ? Number(e.target.value) : null)}
          error={errors.category}
          required
        >
          <option value="">{t('bitte wählen')}</option>
          {cats.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </SelectField>
      )}
      <Field
        label={t('E-Mail für das PDF (optional)')}
        type="email"
        value={v.email}
        onChange={(e) => set('email', e.target.value)}
        error={errors.email}
      />
      <Checkbox
        label={t('Umsatzsteuer ausweisen')}
        checked={vat}
        onChange={setVat}
        hint={t('nur bei Bedarf')}
      />
      <Why k="receipt_vat" />
      {vat && (
        <Field
          label={t('Steuersatz in %')}
          inputMode="decimal"
          value={v.vat_rate ?? ''}
          onChange={(e) => set('vat_rate', parseAmount(e.target.value) || null)}
          error={errors.vat_rate}
        />
      )}
      {message && <Alert kind="error">{message}</Alert>}
      <div className="button-row">
        <button className="button button-primary" type="submit" disabled={busy}>
          {initial ? t('Speichern') : t('Weiter zur Unterschrift')}
        </button>
        <Link
          className="button button-ghost"
          to={initial ? `/finanzen/quittungen/${initial.id}` : '/finanzen/quittungen'}
          onClick={(e) => {
            if (initial && onSaved) {
              e.preventDefault()
              onSaved(initial)
            }
          }}
        >
          {t('Abbrechen')}
        </Link>
      </div>
    </form>
  )
}

/** Schritt 2 und 3: unterschreiben, abschließen; danach PDF, Mail, Storno. */
function CashReceiptDetail({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const navigate = useNavigate()
  const id = Number(useParams().id)
  const {
    data: r,
    error,
    setData,
  } = useLoad(() => financeApi.cashReceipt(org.id, id), [org.id, id])
  const [editing, setEditing] = useState(false)
  const [signing, setSigning] = useState<SignatureRole | null>(null)
  const [signError, setSignError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [sendMail, setSendMail] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const finalizeKey = useRef(newRequestKey())
  const prefilled = useRef(false)

  // Hinterlegte Kassierer-Unterschrift vorbelegen
  useEffect(() => {
    if (!r || prefilled.current || !canEdit) return
    if (r.status === 'draft' && r.has_stored_signature && !r.treasurer_signature) {
      prefilled.current = true
      financeApi
        .signCashReceipt(org.id, r.id, 'treasurer', { use_stored: true })
        .then(setData)
        .catch(() => undefined)
    }
  }, [r, org.id, canEdit, setData])

  if (error) return <Alert kind="error">{error}</Alert>
  if (!r) return <p className="muted">{t('Lädt …')}</p>
  if (editing)
    return (
      <CashReceiptForm
        initial={r}
        onSaved={(saved) => {
          setData(saved)
          setEditing(false)
        }}
      />
    )

  const draft = r.status === 'draft'
  const receives = r.direction === 'in'

  async function act(fn: () => Promise<CashReceipt>, success?: string) {
    setBusy(true)
    setNotice(null)
    try {
      setData(await fn())
      if (success) setNotice({ kind: 'success', text: success })
      return true
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function sign(value: SignatureInput) {
    if (!signing || !r) return
    const role = signing
    // Fehler im Vollbild zeigen, nicht verdeckt dahinter (UX-Audit 31.10. C01)
    setBusy(true)
    setSignError(null)
    try {
      setData(await financeApi.signCashReceipt(org.id, r.id, role, value))
      setSigning(null)
    } catch (err) {
      setSignError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function decline() {
    if (!r) return
    const reason = await promptDialog({
      title: t('Zahler unterschreibt nicht'),
      message: t('Dann gilt nur deine Unterschrift als Kassierer, wie bei einer Papierquittung.'),
      label: t('Grund'),
      confirmLabel: t('Übernehmen'),
      danger: false,
    })
    if (reason === null) return
    await act(() => financeApi.signCashReceipt(org.id, r.id, 'counterparty', { declined: reason }))
  }

  async function finalize() {
    if (!r) return
    const ok = await act(
      () =>
        financeApi.finalizeCashReceipt(org.id, r.id, finalizeKey.current, sendMail && !!r.email),
      t('Die Quittung ist abgeschlossen.'),
    )
    if (ok) finalizeKey.current = newRequestKey()
  }

  async function cancel() {
    if (!r) return
    const reason = await promptDialog({
      title: t('Quittung {number} stornieren?', { number: r.number }),
      message:
        t('Es entsteht eine Gegenbuchung im laufenden Geschäftsjahr und ein neues PDF mit ') +
        t('Storno-Vermerk. Die Quittung bleibt sichtbar. Ist ihr Jahr schon abgeschlossen, ') +
        t('bleibt es unverändert; die Gegenbuchung verweist auf die alte Quittung.'),
      label: t('Grund'),
      confirmLabel: t('Stornieren'),
    })
    if (reason === null) return
    await act(
      () => financeApi.cancelCashReceipt(org.id, r.id, reason),
      t('Die Quittung ist storniert.'),
    )
  }

  async function send() {
    if (!r) return
    const email = await promptDialog({
      title: t('Quittung per Mail senden'),
      label: t('E-Mail-Adresse'),
      defaultValue: r.email,
      confirmLabel: t('Senden'),
      danger: false,
    })
    if (email === null) return
    await act(() => financeApi.sendCashReceipt(org.id, r.id, email), t('Die Mail ist unterwegs.'))
  }

  async function discard() {
    if (!r) return
    if (!(await confirmDialog({ title: t('Entwurf verwerfen?'), confirmLabel: t('Verwerfen') })))
      return
    try {
      await financeApi.deleteCashReceipt(org.id, r.id)
      navigate('/finanzen/quittungen')
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    }
  }

  const treasurerRole = receives
    ? t('Betrag erhalten (Kassierer)')
    : t('Betrag ausgezahlt (Kassierer)')
  const otherRole = receives
    ? t('Betrag gezahlt: {counterparty_name}', { counterparty_name: r.counterparty_name })
    : t('Betrag erhalten: {counterparty_name}', { counterparty_name: r.counterparty_name })

  return (
    <div className="card card-wide">
      <p className="muted small">
        <Link to="/finanzen/quittungen">{t('Alle Quittungen')}</Link>
      </p>
      <div className="card-head">
        <h2>{r.number ? t('Quittung {number}', { number: r.number }) : t('Quittung (Entwurf)')}</h2>
        <span className="muted small">{r.status_label}</span>
      </div>
      <p className="receipt-amount">{euro(r.amount)}</p>
      <p>
        {receives ? t('erhalten von ') : t('ausgezahlt an ')}
        <strong>{r.counterparty_name}</strong>
        <br />
        {t('für')} {r.purpose}
        {r.invoice_number && (
          <>
            {' '}
            {t('· Rechnung')} {r.invoice_number}
          </>
        )}
      </p>
      {r.receipt_date && (
        <p className="muted small">
          {t('Datum')} {formatDate(r.receipt_date)}
          {r.finalized_at && (
            <>
              {' '}
              {t('· abgeschlossen')} {formatDateTime(r.finalized_at)}
            </>
          )}
          {r.booking_number && (
            <>
              {' '}
              {t('· Buchung')} {r.booking_number}
            </>
          )}
        </p>
      )}
      {r.status === 'cancelled' && (
        <Alert kind="info">
          {t('Storniert am')} {r.cancelled_at ? formatDateTime(r.cancelled_at) : ''} (Gegenbuchung{' '}
          {r.cancel_number}): {r.cancel_reason}
        </Alert>
      )}

      <div className="receipt-signatures">
        <div className="receipt-signature">
          <span className="small">{treasurerRole}</span>
          <button
            type="button"
            className="receipt-signature-box"
            disabled={!draft || !canEdit || busy}
            onClick={() => setSigning('treasurer')}
            aria-label={
              r.treasurer_signature
                ? t('Kassierer neu unterschreiben')
                : t('Als Kassierer unterschreiben')
            }
          >
            {r.treasurer_signature ? (
              <SignatureImage shape={r.treasurer_signature} label={t('Unterschrift Kassierer')} />
            ) : (
              t('Antippen zum Unterschreiben')
            )}
          </button>
          {r.treasurer_name && <span className="muted small">{r.treasurer_name}</span>}
        </div>
        <div className="receipt-signature">
          <span className="small">{otherRole}</span>
          {r.no_signature_reason ? (
            <div className="receipt-signature-box">
              {t('ohne Unterschrift:')} {r.no_signature_reason}
            </div>
          ) : (
            <button
              type="button"
              className="receipt-signature-box"
              disabled={!draft || !canEdit || busy}
              onClick={() => setSigning('counterparty')}
              aria-label={t('{counterparty_name} unterschreiben lassen', {
                counterparty_name: r.counterparty_name,
              })}
            >
              {r.counterparty_signature ? (
                <SignatureImage
                  shape={r.counterparty_signature}
                  label={t('Unterschrift {counterparty_name}', {
                    counterparty_name: r.counterparty_name,
                  })}
                />
              ) : (
                t('Antippen: im Vollbild unterschreiben lassen')
              )}
            </button>
          )}
          {draft && canEdit && receives && !r.counterparty_signature && !r.no_signature_reason && (
            <button type="button" className="link-button small" onClick={decline} disabled={busy}>
              {t('Zahler unterschreibt nicht')}
            </button>
          )}
        </div>
      </div>

      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}

      {draft && canEdit && (
        <>
          {r.missing.length > 0 && (
            <p className="muted small">
              {t('Es fehlt noch:')} {r.missing.join(', ')}.
            </p>
          )}
          <Checkbox
            label={
              receives
                ? t('Ich bestätige, {x} erhalten zu haben.', { x: euro(r.amount) })
                : t('Ich bestätige, {x} ausgezahlt zu haben.', { x: euro(r.amount) })
            }
            checked={confirmed}
            onChange={setConfirmed}
          />
          {r.email && (
            <Checkbox
              label={t('PDF an {email} senden', { email: r.email })}
              checked={sendMail}
              onChange={setSendMail}
            />
          )}
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy || r.missing.length > 0 || !confirmed}
              onClick={finalize}
            >
              {t('Quittung abschließen')}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setEditing(true)}>
              {t('Angaben ändern')}
            </button>
            <a
              className="button button-ghost"
              href={financeApi.cashReceiptPdfUrl(org.id, r.id)}
              target="_blank"
              rel="noreferrer"
            >
              {t('Vorschau')}
            </a>
            <button type="button" className="button button-ghost" onClick={discard}>
              {t('Entwurf verwerfen')}
            </button>
          </div>
          <p className="muted small">
            {t('Ändern sich Betrag, Name, Zweck oder Richtung, müssen beide neu unterschreiben.')}
          </p>
        </>
      )}

      {!draft && (
        <div className="button-row">
          <a
            className="button button-primary"
            href={financeApi.cashReceiptPdfUrl(org.id, r.id)}
            target="_blank"
            rel="noreferrer"
          >
            {t('PDF öffnen')}
          </a>
          {canEdit && (
            <button type="button" className="button button-ghost" onClick={send} disabled={busy}>
              {t('Per Mail senden')}
            </button>
          )}
          {canEdit && r.status === 'final' && (
            <button type="button" className="button button-ghost" onClick={cancel} disabled={busy}>
              {t('Stornieren')}
            </button>
          )}
        </div>
      )}
      {r.sent_at && (
        <p className="muted small">
          {t('Zuletzt an {email} verschickt am {x}.', {
            email: r.email,
            x: formatDateTime(r.sent_at),
          })}
        </p>
      )}

      {signing && (
        <SignatureFullscreen
          title={signing === 'treasurer' ? treasurerRole : otherRole}
          text={
            signing === 'treasurer'
              ? receives
                ? t('{x} von {counterparty_name} erhalten. Zweck: {purpose}', {
                    x: euro(r.amount),
                    counterparty_name: r.counterparty_name,
                    purpose: r.purpose,
                  })
                : t('{x} an {counterparty_name} ausgezahlt. Zweck: {purpose}', {
                    x: euro(r.amount),
                    counterparty_name: r.counterparty_name,
                    purpose: r.purpose,
                  })
              : r.confirmation_text
          }
          busy={busy}
          error={signError}
          onCancel={() => {
            setSignError(null)
            setSigning(null)
          }}
          onConfirm={sign}
        />
      )}
    </div>
  )
}
