// Mitgliederbereich nach Aufgaben: Ausweis, Rechnungen, Rundschreiben, eigene Daten.
import { PortalCirculars } from './PortalCirculars.tsx'
import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { FIELD_LABELS, portalApi } from '../../api/portal.ts'
import type { ChangeRequest, PortalDetail, PortalEntry } from '../../api/portal.ts'
import {
  formatDate,
  formatDateTime,
  formatMemberDate,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { Alert, Field, SelectField } from '../../components/ui.tsx'
import { confirmDiscard, useChangesGuard } from '../../components/leaveGuard.ts'
import { GENDERS } from '../../api/members.ts'
import { OwnCardPanel } from '../../components/CardPanel.tsx'
import { useOrg } from '../../org/OrgContext.tsx'
import { PortalInvoices, PortalMandate } from '../billing/MyInvoices.tsx'
import { PortalEntries } from './PortalEntries.tsx'
import { PortalResults } from './PortalResults.tsx'
import { useTerms } from '../../org/terms.ts'
import { NotFoundPage } from '../NoticePages.tsx'
import { t } from '../../i18n/index.ts'

const FIELDS = [
  'last_name',
  'first_name',
  'birth_date',
  'gender',
  'email',
  'phone',
  'street',
  'postal_code',
  'city',
  'country',
] as const
type FieldKey = (typeof FIELDS)[number]

/** Zweck der eigenen Angaben für Browser und Hilfsmittel (WCAG 1.3.5). */
const AUTOCOMPLETE: Record<FieldKey, string> = {
  last_name: 'family-name',
  first_name: 'given-name',
  birth_date: 'bday',
  gender: 'sex',
  email: 'email',
  phone: 'tel',
  street: 'street-address',
  postal_code: 'postal-code',
  city: 'address-level2',
  country: 'country-name',
}

function currentValues(d: PortalDetail): Record<FieldKey, string> {
  return {
    last_name: d.last_name,
    first_name: d.first_name,
    birth_date: d.birth_date,
    gender: d.gender ?? '',
    email: d.contact?.email ?? '',
    phone: d.contact?.phone ?? '',
    street: d.contact?.street ?? '',
    postal_code: d.contact?.postal_code ?? '',
    city: d.contact?.city ?? '',
    country: d.contact?.country ?? '',
  }
}

export function PortalPage() {
  const { activePortal } = useOrg()
  if (!activePortal) return <Alert kind="info">{t('Kein Mitgliederbereich ausgewählt.')}</Alert>
  return (
    <Routes>
      <Route index element={<PortalOverview key={activePortal.id} entry={activePortal} />} />
      <Route
        path="ausweis"
        element={
          <PortalSection title={t('Mein Ausweis')}>
            <OwnCardPanel
              key={activePortal.id}
              accessId={activePortal.id}
              empty={
                <Alert kind="info">
                  {t(
                    'Für dich gibt es zurzeit keinen Mitgliedsausweis, zum Beispiel weil deine Mitgliedschaft beendet ist.',
                  )}
                </Alert>
              }
            />
          </PortalSection>
        }
      />
      <Route
        path="rechnungen"
        element={
          <PortalSection title={t('Rechnungen und Zahlung')}>
            <PortalInvoices
              key={activePortal.id}
              accessId={activePortal.id}
              empty={<p className="muted">{t('Für dich liegen keine Rechnungen vor.')}</p>}
            />
            <PortalMandate key={`m${activePortal.id}`} accessId={activePortal.id} />
          </PortalSection>
        }
      />
      <Route
        path="rundschreiben"
        element={
          <PortalSection title={t('Rundschreiben')}>
            <PortalCirculars key={activePortal.id} accessId={activePortal.id} />
          </PortalSection>
        }
      />
      <Route
        path="gemeldet"
        element={
          <PortalSection title={t('Wofür bin ich gemeldet?')}>
            <PortalEntries key={activePortal.id} accessId={activePortal.id} />
          </PortalSection>
        }
      />
      <Route
        path="ergebnisse"
        element={
          <PortalSection title="Meine Ergebnisse">
            <PortalResults key={activePortal.id} accessId={activePortal.id} />
          </PortalSection>
        }
      />
      <Route path="daten" element={<PortalData key={activePortal.id} entry={activePortal} />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

function PortalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <p className="small">
        <Link to="/mein-bereich">{t('← Mein Bereich')}</Link>
      </p>
      <h1>{title}</h1>
      <div className="stack">{children}</div>
    </section>
  )
}

/** Aufgaben im Mitgliederbereich als Kacheln (Startseite und Übersicht). */
export function PortalTasks({ entry }: { entry: PortalEntry }) {
  const tasks: { to: string; title: string; text: string }[] = [
    {
      to: '/mein-bereich/ausweis',
      title: t('Ausweis zeigen'),
      text: t('QR-Code vorzeigen oder als PDF speichern'),
    },
    ...(entry.events_enabled
      ? [
          {
            to: '/termine',
            title: t('Meine Termine'),
            text: t('Termine ansehen, zu- oder absagen'),
          },
        ]
      : []),
    ...(entry.entries_enabled
      ? [
          {
            to: '/mein-bereich/gemeldet',
            title: t('Gemeldet'),
            text: t('Wettbewerbe, für die der Verein dich gemeldet hat'),
          },
        ]
      : []),
    ...(entry.competitions_enabled
      ? [
          {
            to: '/mein-bereich/ergebnisse',
            title: 'Meine Ergebnisse',
            text: 'Plätze, Werte und Titel aus Wettbewerben',
          },
        ]
      : []),
    {
      to: '/mein-bereich/rechnungen',
      title: t('Rechnungen'),
      text: t('Beiträge, offene Beträge und Lastschrift'),
    },
    {
      to: '/mein-bereich/rundschreiben',
      title: t('Rundschreiben'),
      text: t('Empfangene Schreiben lesen'),
    },
    {
      to: '/mein-bereich/daten',
      title: t('Meine Daten'),
      text: t('Anschrift und Kontakt ansehen, Änderungen melden'),
    },
  ]
  return (
    <ul className="task-tiles">
      {tasks.map((tmx) => (
        <li key={tmx.to}>
          <Link to={tmx.to} className="task-tile">
            <strong>{tmx.title}</strong>
            <span className="muted small">{tmx.text}</span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function PortalOverview({ entry }: { entry: PortalEntry }) {
  const { data, error } = useLoad(() => portalApi.portal(entry.id), [entry.id])
  const pending = data?.change_requests.find((c) => c.status === 'pending')
  return (
    <section>
      <h1>{t('Mein Bereich')}</h1>
      <p className="muted">
        {entry.club_display_name ?? entry.club_name}
        {data?.status === 'former' && t(' · ehemaliges Mitglied')}
      </p>
      <PortalTasks entry={entry} />
      {pending && (
        <Alert kind="info">
          {t('Deine Änderungsmeldung vom {x} wird noch geprüft.', {
            x: formatDateTime(pending.created_at),
          })}{' '}
          <Link to="/mein-bereich/daten">{t('Ansehen')}</Link>
        </Alert>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {data && <ClubContact club={data.club} />}
    </section>
  )
}

function PortalData({ entry }: { entry: PortalEntry }) {
  const tm = useTerms()
  const { data, error, reload } = useLoad(() => portalApi.portal(entry.id), [entry.id])
  const [editing, setEditing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>

  const values = currentValues(data)
  const pending = data.change_requests.find((c) => c.status === 'pending')

  return (
    <PortalSection title={t('Meine Daten')}>
      <div className="card card-wide">
        <div className="card-head">
          <h2>
            {data.first_name} {data.last_name}
          </h2>
          {!editing && (
            <button
              type="button"
              className="button button-ghost push-right"
              onClick={() => setEditing(true)}
            >
              {t('Daten ändern')}
            </button>
          )}
        </div>
        <p className="muted small">
          {data.club.name}
          {data.status === 'former' && t(' · ehemaliges Mitglied')}
          {' · '}
          {data.member_type ?? t('ohne Mitgliedsart')}
          {data.entry_date &&
            t(' · Mitglied seit {x}', {
              x: formatMemberDate(data.entry_date, entry.date_precision),
            })}
          {data.club_number &&
            t(' · Mitgliedsnummer {club_number}', { club_number: data.club_number })}
          {data.departments.length > 0 && t(' · {x}', { x: data.departments.join(', ') })}
        </p>
        {editing ? (
          <ChangeForm
            accessId={entry.id}
            initial={values}
            needsApproval={data.contact_changes_need_approval}
            hasPending={!!pending}
            onDone={async (text) => {
              setEditing(false)
              setNotice(text)
              await reload()
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <dl className="facts">
            {FIELDS.map((key) => (
              <div key={key}>
                <dt>{FIELD_LABELS[key]}</dt>
                <dd>{key === 'birth_date' ? formatDate(values[key]) : values[key] || '–'}</dd>
              </div>
            ))}
          </dl>
        )}
        {notice && !editing && <Alert kind="success">{notice}</Alert>}
        {pending && !editing && (
          <Alert kind="info">
            {t('Deine Änderungsmeldung vom {x} wartet auf {e_akk}.', {
              x: formatDateTime(pending.created_at),
              e_akk: tm.e_akk,
            })}
          </Alert>
        )}
      </div>

      {data.change_requests.length > 0 && (
        <div className="card card-wide">
          <h2>{t('Meine Änderungsmeldungen')}</h2>
          <ul className="audit-list">
            {data.change_requests.map((c) => (
              <ChangeRequestItem key={c.id} request={c} />
            ))}
          </ul>
        </div>
      )}
    </PortalSection>
  )
}

function ClubContact({ club }: { club: PortalDetail['club'] }) {
  const tm = useTerms()
  return (
    <div className="card card-wide">
      <h2>
        {t('Kontakt')} {tm.e_zum}
      </h2>
      <p>
        {club.name}
        <br />
        {club.street && (
          <>
            {club.street}
            <br />
          </>
        )}
        {club.postal_code} {club.city}
      </p>
      {club.email && (
        <p>
          <a href={`mailto:${club.email}`}>{club.email}</a>
        </p>
      )}
      {club.phone && <p>{club.phone}</p>}
      {club.website && (
        <p>
          <a href={club.website} target="_blank" rel="noreferrer">
            {club.website}
          </a>
        </p>
      )}
    </div>
  )
}

const DIRECT: FieldKey[] = ['email', 'phone', 'street', 'postal_code', 'city', 'country']

function ChangeForm({
  accessId,
  initial,
  needsApproval,
  hasPending,
  onDone,
  onCancel,
}: {
  accessId: number
  initial: Record<FieldKey, string>
  needsApproval: boolean
  hasPending: boolean
  onDone: (text: string) => void
  onCancel: () => void
}) {
  const tm = useTerms()
  const form = useForm({ ...initial, message: '' })
  const { values: v, errors, set } = form
  // Noch nicht gesendete Änderungen nicht unbemerkt verlieren (UX-Audit 31.10. W01)
  const [sent, setSent] = useState(false)
  const { dirty } = useChangesGuard(v, !sent)

  async function send(e: FormEvent) {
    e.preventDefault()
    const changed: Record<string, string> = {}
    for (const key of FIELDS) if (v[key] !== initial[key]) changed[key] = v[key]
    if (Object.keys(changed).length === 0) {
      form.setMessage({ kind: 'error', text: t('Du hast nichts geändert.') })
      return
    }
    const result = (await form.submit(() =>
      portalApi.requestChange(accessId, { ...changed, message: v.message }),
    )) as Awaited<ReturnType<typeof portalApi.requestChange>> | undefined
    if (!result) return
    setSent(true)
    const applied = Object.keys(result.applied).length > 0
    onDone(
      applied && result.request
        ? t('Kontaktdaten gespeichert. Die übrigen Änderungen bestätigt {e_nom}.', {
            e_nom: tm.e_nom,
          })
        : applied
          ? t('Gespeichert.')
          : t('Meldung gesendet. {e_Nom} prüft und übernimmt sie.', { e_Nom: tm.e_Nom }),
    )
  }

  return (
    <form onSubmit={send}>
      <p className="muted small">
        {t('Ändere die Angaben, die nicht mehr stimmen.')}{' '}
        {needsApproval
          ? t('{e_Nom} prüft alle Änderungen und übernimmt sie.', { e_Nom: tm.e_Nom })
          : t(
              'Kontaktdaten (E-Mail, Telefon, Anschrift) gelten sofort. Änderungen an Name, Geburtsdatum oder Geschlecht prüft {e_nom}.',
              { e_nom: tm.e_nom },
            )}
      </p>
      {hasPending && (
        <Alert kind="info">
          {t('Es wartet noch eine frühere Meldung auf {e_akk}.', { e_akk: tm.e_akk })}{' '}
          {needsApproval
            ? t('Bis dahin sind die Felder gesperrt.')
            : t(
                'Bis dahin sind Name, Geburtsdatum und Geschlecht gesperrt; Kontaktdaten kannst du weiter ändern.',
              )}
        </Alert>
      )}
      <div className="grid-3">
        {FIELDS.map((key) =>
          key === 'gender' ? (
            <SelectField
              key={key}
              label={FIELD_LABELS[key]}
              value={v[key]}
              error={errors[key]}
              disabled={hasPending && (needsApproval || !DIRECT.includes(key))}
              hint={!needsApproval && !DIRECT.includes(key) ? t('mit Bestätigung') : undefined}
              autoComplete={AUTOCOMPLETE[key]}
              onChange={(e) => set(key, e.target.value)}
            >
              {GENDERS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </SelectField>
          ) : (
            <Field
              key={key}
              label={FIELD_LABELS[key]}
              type={
                key === 'birth_date'
                  ? 'date'
                  : key === 'email'
                    ? 'email'
                    : key === 'phone'
                      ? 'tel'
                      : 'text'
              }
              autoComplete={AUTOCOMPLETE[key]}
              value={v[key]}
              error={errors[key]}
              disabled={hasPending && (needsApproval || !DIRECT.includes(key))}
              hint={!needsApproval && !DIRECT.includes(key) ? t('mit Bestätigung') : undefined}
              onChange={(e) => set(key, e.target.value)}
            />
          ),
        )}
      </div>
      <Field
        label={t('Nachricht an {e_akk} (optional)', { e_akk: tm.e_akk })}
        value={v.message}
        maxLength={500}
        onChange={(e) => set('message', e.target.value)}
      />
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={form.busy}>
          {needsApproval ? t('Änderung zur Prüfung senden') : t('Speichern')}
        </button>
        <button
          type="button"
          className="button button-ghost"
          onClick={() => void confirmDiscard(dirty).then((ok) => ok && onCancel())}
        >
          {t('Abbrechen')}
        </button>
      </div>
    </form>
  )
}

export function ChangeRequestItem({ request: c }: { request: ChangeRequest }) {
  const tm = useTerms()
  return (
    <li>
      <strong>{c.status_label}</strong>{' '}
      <span className="muted small">gemeldet {formatDateTime(c.created_at)}</span>
      <ChangeTable request={c} />
      {c.response && (
        <p className="small">
          {t('Antwort {e_gen}:', { e_gen: tm.e_gen })} {c.response}
        </p>
      )}
    </li>
  )
}

export function ChangeTable({ request: c }: { request: ChangeRequest }) {
  const show = (key: string, value: string | null | undefined) =>
    key === 'birth_date' ? formatDate(value ?? null) : value || '–'
  return (
    <table className="table change-table">
      <tbody>
        {Object.entries(c.data).map(([key, value]) => (
          <tr key={key}>
            <td>{FIELD_LABELS[key] ?? key}</td>
            <td>
              <span className="change-old">{show(key, c.previous[key])}</span> →{' '}
              <strong>{show(key, value)}</strong>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
