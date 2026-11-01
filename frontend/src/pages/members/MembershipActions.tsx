import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { FormEvent } from 'react'
import { saveBlob } from '../../api/client.ts'
import { memberApi, todayIso } from '../../api/members.ts'
import type { MemberDetail } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'
import { formatDate, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { Term } from '../../learning/Aids.tsx'

type Action = 'type' | 'exit' | 'reentry' | null

/** Abläufe der Mitgliedschaft: Art wechseln, Austritt, Wiedereintritt. */
export function MembershipActions({
  org,
  member,
  onChanged,
}: {
  org: OrgSummary
  member: MemberDetail
  onChanged: (m: MemberDetail) => void
}) {
  const [action, setAction] = useState<Action>(null)
  const types = useLoad(() => memberApi.types(org.id), [org.id])
  const available = types.data?.filter((tm) => !tm.is_archived) ?? []
  const ready = !types.error && available.length > 0
  const canSetup = org.permissions.includes(PERM.orgEdit)
  const done = (m: MemberDetail) => {
    setAction(null)
    onChanged(m)
  }

  return (
    <div className="card card-wide">
      <h2>Abläufe</h2>
      {member.status === 'former' && (
        <p className="muted small">
          Ehemaliges Mitglied (Archiv).{' '}
          {member.purged ? (
            <>
              Die Daten wurden nach Ablauf der <Term k="deletion_period_term">Löschfrist</Term> auf
              das Minimum reduziert.
            </>
          ) : (
            member.purge_due && (
              <>
                Nach Ablauf der <Term k="deletion_period_term">Löschfrist</Term> werden die Daten am{' '}
                {formatDate(member.purge_due)} gelöscht.
              </>
            )
          )}
        </p>
      )}
      {action === null && (
        <div className="button-row">
          {member.status === 'active' ? (
            <>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setAction('type')}
              >
                Mitgliedsart wechseln
              </button>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setAction('exit')}
              >
                Austritt erfassen
              </button>
            </>
          ) : (
            <button
              type="button"
              className="button button-primary"
              onClick={() => setAction('reentry')}
            >
              Wiedereintritt
            </button>
          )}
        </div>
      )}
      {(action === 'type' || action === 'reentry') && !ready && (
        // Laden, Fehler und „keine Mitgliedsart“ unterscheidbar (UI-Audit NMF-04/NAF-03)
        <div className="subcard stack-sm">
          {types.error ? (
            <LoadError
              message={`Die Mitgliedsarten konnten nicht geladen werden. ${types.error}`}
              onRetry={() => void types.reload()}
            />
          ) : !types.data ? (
            <p className="muted">Mitgliedsarten werden geladen …</p>
          ) : (
            <Alert kind="info">
              Es ist keine Mitgliedsart verfügbar.{' '}
              {canSetup ? (
                <Link to="/mitglieder/einrichtung/mitgliedsarten">Mitgliedsarten einrichten</Link>
              ) : (
                'Bitte wende dich an den Vorstand, der die Mitgliederverwaltung einrichtet.'
              )}
            </Alert>
          )}
          <div className="button-row">
            <button type="button" className="button" onClick={() => setAction(null)}>
              Abbrechen
            </button>
          </div>
        </div>
      )}
      {action === 'type' && ready && (
        <ChangeType
          org={org}
          member={member}
          types={available}
          onDone={done}
          onCancel={() => setAction(null)}
        />
      )}
      {action === 'exit' && (
        <Exit org={org} member={member} onDone={done} onCancel={() => setAction(null)} />
      )}
      {action === 'reentry' && ready && (
        <Reentry
          org={org}
          member={member}
          types={available}
          onDone={done}
          onCancel={() => setAction(null)}
        />
      )}
      {action === null && <Privacy org={org} member={member} onChanged={onChanged} />}
    </div>
  )
}

/** Auskunft (Art. 15) und Löschen auf Verlangen (Art. 17) für dieses Mitglied. */
function Privacy({
  org,
  member,
  onChanged,
}: {
  org: OrgSummary
  member: MemberDetail
  onChanged: (m: MemberDetail) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canExport = org.permissions.includes(PERM.dataExport)
  const canErase =
    org.permissions.includes(PERM.membersEdit) &&
    member.status === 'former' &&
    !member.purged &&
    member.purge_due !== null &&
    member.periods.every((p) => !p.exit_date || p.exit_date <= todayIso())
  if (!canExport && !canErase) return null
  const name = `${member.first_name} ${member.last_name}`

  async function disclose() {
    setBusy(true)
    setError('')
    try {
      const blob = await memberApi.disclosure(org.id, member.id)
      saveBlob(blob, `auskunft-${member.last_name}-${member.first_name}.zip`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function erase() {
    if (
      !(await confirmDialog({
        title: `Daten von ${name} jetzt löschen?`,
        message:
          'Wie nach Ablauf der Löschfrist bleiben nur Name, Geburtsjahr und Mitgliedszeiten. ' +
          'Rechnungen und Buchungen bleiben wegen der Aufbewahrungspflicht. Das lässt sich ' +
          'nicht rückgängig machen und gilt auch nach dem Einspielen eines älteren Backups.',
        confirmLabel: 'Endgültig löschen',
      }))
    )
      return
    setBusy(true)
    setError('')
    try {
      onChanged(await memberApi.erase(org.id, member.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="subcard stack-sm">
      <h3>Datenschutz</h3>
      <p className="muted small">
        Auskunft: ein ZIP nur mit den Daten dieser Person (Akte, Rechnungen, versandte Mails, Zugang
        und Geräte, Verbund-Meldungen).
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        {canExport && (
          <button type="button" className="button button-ghost" disabled={busy} onClick={disclose}>
            Auskunft für dieses Mitglied (ZIP)
          </button>
        )}
        {canErase && (
          <button type="button" className="button button-danger" disabled={busy} onClick={erase}>
            Daten auf Verlangen löschen
          </button>
        )}
      </div>
    </div>
  )
}

interface TypeOption {
  id: number
  name: string
  active: boolean
}

function ChangeType({
  org,
  member,
  types,
  onDone,
  onCancel,
}: {
  org: OrgSummary
  member: MemberDetail
  types: TypeOption[]
  onDone: (m: MemberDetail) => void
  onCancel: () => void
}) {
  const form = useForm({ member_type: '', valid_from: todayIso() })
  async function save(e: FormEvent) {
    e.preventDefault()
    const result = await form.submit(() =>
      memberApi.changeType(
        org.id,
        member.id,
        Number(form.values.member_type),
        form.values.valid_from,
      ),
    )
    if (result) onDone(result as MemberDetail)
  }
  return (
    <form className="subcard" onSubmit={save}>
      <h3>Mitgliedsart wechseln</h3>
      <p className="muted small">
        Die bisherige Art ({member.current_type?.member_type_name ?? '–'}) endet am Vortag, die
        Mitgliedschaft läuft weiter.
      </p>
      <div className="grid-2">
        <SelectField
          label="Neue Mitgliedsart"
          required
          value={form.values.member_type}
          error={form.errors.member_type}
          onChange={(e) => form.set('member_type', e.target.value)}
        >
          <option value="">– bitte wählen –</option>
          {types
            .filter((tm) => tm.id !== member.current_type?.member_type)
            .map((tm) => (
              <option key={tm.id} value={tm.id}>
                {tm.name}
                {tm.active ? ' (aktiv)' : ''}
              </option>
            ))}
        </SelectField>
        <Field
          label="ab"
          type="date"
          required
          value={form.values.valid_from}
          error={form.errors.valid_from}
          onChange={(e) => form.set('valid_from', e.target.value)}
        />
      </div>
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <Buttons busy={form.busy} label="Wechseln" onCancel={onCancel} />
    </form>
  )
}

function Exit({
  org,
  member,
  onDone,
  onCancel,
}: {
  org: OrgSummary
  member: MemberDetail
  onDone: (m: MemberDetail) => void
  onCancel: () => void
}) {
  const form = useForm({ exit_date: todayIso(), exit_reason: 'exit', note: '' })
  async function save(e: FormEvent) {
    e.preventDefault()
    if (
      !(await confirmDialog({
        title: `Austritt von ${member.first_name} ${member.last_name} erfassen?`,
        confirmLabel: 'Austritt erfassen',
      }))
    )
      return
    const result = await form.submit(() => memberApi.exit(org.id, member.id, form.values))
    if (result) onDone(result as MemberDetail)
  }
  return (
    <form className="subcard" onSubmit={save}>
      <h3>Austritt erfassen</h3>
      <p className="muted small">
        Der Zeitraum wird geschlossen, die Person kommt ins Archiv. Mitgliedsart,{' '}
        {org.department_label_plural} und Rollen enden mit dem Austritt.
      </p>
      <div className="grid-2">
        <Field
          label="Austrittsdatum"
          type="date"
          required
          value={form.values.exit_date}
          error={form.errors.exit_date}
          onChange={(e) => form.set('exit_date', e.target.value)}
        />
        <SelectField
          label="Grund"
          value={form.values.exit_reason}
          error={form.errors.exit_reason}
          onChange={(e) => form.set('exit_reason', e.target.value)}
        >
          {member.exit_reasons.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </SelectField>
      </div>
      <Field
        label="Bemerkung (optional)"
        value={form.values.note}
        error={form.errors.note}
        onChange={(e) => form.set('note', e.target.value)}
      />
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <Buttons busy={form.busy} label="Austritt speichern" onCancel={onCancel} />
    </form>
  )
}

function Reentry({
  org,
  member,
  types,
  onDone,
  onCancel,
}: {
  org: OrgSummary
  member: MemberDetail
  types: TypeOption[]
  onDone: (m: MemberDetail) => void
  onCancel: () => void
}) {
  const needsContact = member.contact === null
  const form = useForm({
    entry_date: todayIso(),
    member_type: '',
    email: '',
    phone: '',
    street: '',
    postal_code: '',
    city: '',
  })
  const v = form.values
  const e = form.errors
  async function save(ev: FormEvent) {
    ev.preventDefault()
    const payload: Record<string, unknown> = {
      entry_date: v.entry_date,
      member_type: Number(v.member_type),
    }
    if (needsContact)
      Object.assign(payload, {
        email: v.email,
        phone: v.phone,
        street: v.street,
        postal_code: v.postal_code,
        city: v.city,
      })
    const result = await form.submit(() => memberApi.reentry(org.id, member.id, payload))
    if (result) onDone(result as MemberDetail)
  }
  return (
    <form className="subcard" onSubmit={save}>
      <h3>Wiedereintritt</h3>
      <p className="muted small">
        Es entsteht ein neuer Zeitraum. Frühere Zeiträume und die Verbandsnummer bleiben erhalten.
      </p>
      <div className="grid-2">
        <Field
          label="Eintritt"
          type="date"
          required
          value={v.entry_date}
          error={e.entry_date}
          onChange={(ev) => form.set('entry_date', ev.target.value)}
        />
        <SelectField
          label="Mitgliedsart"
          required
          value={v.member_type}
          error={e.member_type}
          onChange={(ev) => form.set('member_type', ev.target.value)}
        >
          <option value="">– bitte wählen –</option>
          {types.map((tm) => (
            <option key={tm.id} value={tm.id}>
              {tm.name}
            </option>
          ))}
        </SelectField>
      </div>
      {needsContact && (
        <>
          <p className="muted small">Die Kontaktdaten wurden gelöscht – bitte neu erfassen.</p>
          <div className="grid-2">
            <Field
              label="E-Mail-Adresse (optional)"
              type="email"
              value={v.email}
              error={e.email}
              onChange={(ev) => form.set('email', ev.target.value)}
            />
            <Field
              label="Telefon"
              value={v.phone}
              onChange={(ev) => form.set('phone', ev.target.value)}
            />
          </div>
          <Field
            label="Straße und Hausnummer"
            required
            value={v.street}
            error={e.street}
            onChange={(ev) => form.set('street', ev.target.value)}
          />
          <div className="grid-2">
            <Field
              label="PLZ"
              required
              value={v.postal_code}
              error={e.postal_code}
              onChange={(ev) => form.set('postal_code', ev.target.value)}
            />
            <Field
              label="Ort"
              required
              value={v.city}
              error={e.city}
              onChange={(ev) => form.set('city', ev.target.value)}
            />
          </div>
        </>
      )}
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <Buttons busy={form.busy} label="Wiedereintritt speichern" onCancel={onCancel} />
    </form>
  )
}

function Buttons({
  busy,
  label,
  onCancel,
}: {
  busy: boolean
  label: string
  onCancel: () => void
}) {
  return (
    <div className="button-row">
      <button type="submit" className="button button-primary" disabled={busy}>
        {label}
      </button>
      <button type="button" className="button button-ghost" onClick={onCancel}>
        Abbrechen
      </button>
    </div>
  )
}
