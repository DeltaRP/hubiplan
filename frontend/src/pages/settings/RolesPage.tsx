import { useState } from 'react'
import { todayIso } from '../../api/members.ts'
import type { FormEvent } from 'react'
import { orgApi } from '../../api/orgs.ts'
import type { Assignment, Role } from '../../api/orgs.ts'
import { Alert, Checkbox, Field, SelectField, LoadError } from '../../components/ui.tsx'
import { errorMessage, formatDate, useForm, useLoad } from '../../components/forms.ts'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import type { MemberRow, PickedMember } from '../../api/members.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { useAuth } from '../../auth/AuthContext.tsx'
import { RoleForm, RoleTable } from '../../components/RoleEditor.tsx'
import { ALL_ROLE_FIELDS } from '../../components/roles.ts'

const INVITATION_DAYS = 7

export function RolesPage() {
  const org = useActiveOrg()
  const { refresh } = useOrg()
  const roles = useLoad(() => orgApi.roles(org.id), [org.id])
  const catalog = useLoad(() => orgApi.catalog(org.type, org.id), [org.type, org.id])
  const assignments = useLoad(() => orgApi.assignments(org.id), [org.id])
  const [editing, setEditing] = useState<Role | 'new' | null>(null)

  const error = roles.error ?? catalog.error ?? assignments.error
  if (error)
    return (
      <LoadError
        message={error}
        onRetry={() => void Promise.all([roles.reload(), catalog.reload(), assignments.reload()])}
      />
    )
  if (!roles.data || !catalog.data || !assignments.data) return <p className="muted">Lädt …</p>

  const catalogData = catalog.data
  const reloadAll = async () => {
    await Promise.all([roles.reload(), assignments.reload()])
  }

  return (
    <div className="stack">
      <div className="card card-wide">
        <div className="card-head">
          <h2>Rollen</h2>
          {editing === null && (
            <button
              type="button"
              className="button button-ghost push-right"
              onClick={() => setEditing('new')}
            >
              Neue Rolle
            </button>
          )}
        </div>
        <p className="muted small">
          Eine Rolle bündelt Berechtigungen, zum Beispiel „Kassierer“. Name und Rechte legt ihr
          selbst fest.
        </p>
        {editing !== null && (
          <RoleForm
            // Je Objekt ein eigenes Formular: Werte und Autospeichern wechseln nie das Ziel
            key={editing === 'new' ? 'new' : editing.id}
            role={editing === 'new' ? null : { ...editing, holders: editing.assignment_count }}
            catalog={catalog.data}
            fields={ALL_ROLE_FIELDS}
            hasWebsite={org.modules.includes('website')}
            onSave={(data) =>
              editing === 'new'
                ? orgApi.createRole(org.id, data)
                : orgApi.updateRole(org.id, editing.id, data)
            }
            onDelete={editing === 'new' ? undefined : () => orgApi.deleteRole(org.id, editing.id)}
            confirmDelete={
              editing === 'new' ? undefined : () => confirmAssignedRoleRemoval(editing)
            }
            onDone={async () => {
              setEditing(null)
              await reloadAll()
              await refresh()
            }}
            onCancel={() => setEditing(null)}
          />
        )}
        <RoleTable
          roles={roles.data.map((r) => ({ ...r, holders: r.assignment_count }))}
          catalog={catalogData}
          onEdit={(r) => setEditing(roles.data!.find((x) => x.id === r.id) ?? null)}
          onReorder={(ids) => orgApi.reorderRoles(org.id, ids).then(() => roles.reload())}
          website={org.modules.includes('website')}
        />
      </div>

      <UsersCard
        orgId={org.id}
        isClub={org.type === 'club' && org.modules.includes('members')}
        roles={roles.data}
        assignments={assignments.data}
        onChange={reloadAll}
      />
    </div>
  )
}

function confirmAssignedRoleRemoval(role: Role): Promise<boolean> {
  const count = role.assignment_count
  const message =
    count > 0
      ? `${count === 1 ? 'Ein Benutzer hat' : `${count} Benutzer haben`} diese Rolle noch. ` +
        `${count === 1 ? 'Die Zuordnung wird' : `Alle ${count} Zuordnungen werden`} beendet, ` +
        'die Rechte der Rolle entfallen sofort. Auch frühere Zuordnungen dieser Rolle ' +
        'verschwinden aus der Historie.'
      : undefined
  return confirmDialog({ title: `Rolle „${role.name}“ löschen?`, message, confirmLabel: 'Löschen' })
}

function UsersCard({
  orgId,
  isClub,
  roles,
  assignments,
  onChange,
}: {
  orgId: number
  isClub: boolean
  roles: Role[]
  assignments: Assignment[]
  onChange: () => Promise<void>
}) {
  const { refresh } = useOrg()
  const [today] = useState(todayIso)
  const form = useForm({ email: '', role: roles[0]?.id ?? 0, valid_from: today, valid_until: '' })
  const [created, setCreated] = useState<{ email: string; invited: boolean } | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [member, setMember] = useState<MemberRow | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    setCreated(null)
    const result = (await form.submit(
      () =>
        orgApi.createAssignment(orgId, {
          email: form.values.email,
          role: Number(form.values.role),
          valid_from: form.values.valid_from,
          valid_until: form.values.valid_until || null,
          member: member?.id ?? null,
        }),
      'Rolle zugeordnet.',
    )) as Assignment | undefined
    if (result) {
      if (result.new_account) setCreated({ email: result.user_email, invited: !!result.invited })
      form.setValues((v) => ({ ...v, email: '' }))
      setMember(null)
      await onChange()
      await refresh()
    }
  }

  async function end(a: Assignment) {
    setError(null)
    try {
      await orgApi.updateAssignment(orgId, a.id, { valid_until: today })
      await onChange()
      await refresh()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const visible = showAll ? assignments : assignments.filter((a) => a.is_active)
  const groups = groupByUser(visible)

  return (
    <div className="card card-wide">
      <h2>Benutzer</h2>
      <p className="muted small">
        Ein Benutzerkonto ist der Login einer Person. Es kann Rollen in mehreren Organisationen
        haben. Zuordnungen haben einen Zeitraum – so bleibt die Historie erhalten.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Benutzer</th>
            <th>Rolle</th>
            <th>Zeitraum</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {groups.flatMap((group) =>
            group.map((a, i) => (
              <AssignmentRow
                key={a.id}
                orgId={orgId}
                isClub={isClub}
                assignment={a}
                span={i === 0 ? group.length : 0}
                continued={i < group.length - 1}
                today={today}
                onEnd={() => void end(a)}
                onChange={async () => {
                  await onChange()
                  await refresh()
                }}
              />
            )),
          )}
        </tbody>
      </table>
      <Checkbox label="Auch frühere Zuordnungen zeigen" checked={showAll} onChange={setShowAll} />
      {error && <Alert kind="error">{error}</Alert>}

      <form className="subcard" onSubmit={add}>
        <h3>Rolle zuordnen</h3>
        <div className="grid-2">
          <Field
            label="E-Mail-Adresse"
            type="email"
            required
            value={form.values.email}
            error={form.errors.email}
            hint="Gibt es noch kein Konto, wird eines angelegt."
            onChange={(e) => form.set('email', e.target.value)}
          />
          <SelectField
            label="Rolle"
            value={form.values.role}
            error={form.errors.role}
            onChange={(e) => form.set('role', Number(e.target.value))}
          >
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </SelectField>
          <Field
            label="von"
            type="date"
            required
            value={form.values.valid_from}
            error={form.errors.valid_from}
            onChange={(e) => form.set('valid_from', e.target.value)}
          />
          <Field
            label="bis (optional)"
            type="date"
            value={form.values.valid_until}
            error={form.errors.valid_until}
            onChange={(e) => form.set('valid_until', e.target.value)}
          />
        </div>
        {isClub && (
          <MemberPicker
            orgId={orgId}
            value={member}
            label="Mitgliedsakte der Person (optional, für die Rollen-Historie)"
            onChange={(m) => {
              setMember(m)
              if (m && m.email && !form.values.email) form.set('email', m.email)
            }}
          />
        )}
        {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
        {created && (
          <Alert kind={created.invited ? 'info' : 'error'}>
            {created.invited
              ? `Neues Konto für ${created.email} angelegt. Die Einladung mit einem Link zum ` +
                `Festlegen des Passworts ist per E-Mail unterwegs (gilt ${INVITATION_DAYS} Tage).`
              : `Neues Konto für ${created.email} angelegt, aber die Einladung konnte nicht ` +
                'verschickt werden. Die Person kann auf der Anmeldeseite „Passwort vergessen“ ' +
                'wählen und so ihr Passwort festlegen.'}
          </Alert>
        )}
        <button type="submit" className="button button-primary" disabled={form.busy}>
          Zuordnen
        </button>
      </form>
    </div>
  )
}

/** Zuordnungen je Benutzerkonto, in der Reihenfolge des ersten Auftretens; aktive zuerst. */
function groupByUser(assignments: Assignment[]): Assignment[][] {
  const groups = new Map<string, Assignment[]>()
  for (const a of assignments) {
    const list = groups.get(a.user_email)
    if (list) list.push(a)
    else groups.set(a.user_email, [a])
  }
  return [...groups.values()].map((list) =>
    [...list].sort((x, y) => Number(y.is_active) - Number(x.is_active)),
  )
}

/** Zeile einer Rollenzuordnung; Zeitraum lässt sich ändern, eine Fehleingabe löschen.
 *  Hat ein Konto mehrere Rollen, steht der Benutzer nur in der ersten Zeile (``span``). */
function AssignmentRow({
  orgId,
  isClub,
  assignment: a,
  span,
  continued,
  today,
  onEnd,
  onChange,
}: {
  orgId: number
  isClub: boolean
  assignment: Assignment
  /** Zeilen des Benutzers ab dieser (erste Zeile), 0 = Folgezeile ohne Benutzerspalte */
  span: number
  continued: boolean
  today: string
  onEnd: () => void
  onChange: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [from, setFrom] = useState(a.valid_from)
  const [until, setUntil] = useState(a.valid_until ?? '')
  const [member, setMember] = useState<PickedMember | null>(a.member_record ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const who = a.person_name ?? a.user_name ?? a.user_email
  const { user } = useAuth()

  async function resetMfa() {
    const ok = await confirmDialog({
      title: `Zwei-Faktor-Anmeldung von ${who} zurücksetzen?`,
      message:
        'Nur, wenn die Person ihr Handy und ihre Wiederherstellungscodes verloren hat und du ' +
        'dich vergewissert hast, dass sie es wirklich ist (persönlich oder per Telefon). Sie ' +
        'bekommt eine Mail, ihre App-Geräte werden abgemeldet, und bis sie den zweiten Faktor ' +
        'neu einrichtet, ruhen ihre heiklen Rechte.',
      confirmLabel: 'Zurücksetzen',
    })
    if (ok) await run(() => orgApi.resetMfa(orgId, a.id))
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setEditing(false)
      await onChange()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: 'Zuordnung löschen?',
      message:
        `${who} verliert die Rolle „${a.role_name}“, und die Zuordnung verschwindet aus der ` +
        'Historie. Für ein normales Ende der Amtszeit lieber „bis“ setzen.',
      confirmLabel: 'Löschen',
    })
    if (ok) await run(() => orgApi.deleteAssignment(orgId, a.id))
  }

  return (
    <tr
      className={
        [a.is_active ? '' : 'inactive', continued ? 'row-continued' : ''].join(' ').trim() ||
        undefined
      }
    >
      {span > 0 && (
        <td rowSpan={span > 1 ? span : undefined}>
          {(a.person_name || a.user_name) && <div>{a.person_name ?? a.user_name}</div>}
          <div className="small muted">{a.user_email}</div>
          {isClub && !a.member_record && <div className="small muted">ohne Mitgliedsakte</div>}
          {span > 1 && <div className="small muted">{span} Rollen, es gelten alle Rechte</div>}
        </td>
      )}
      <td>
        {a.role_name}
        {isClub && editing && (
          <MemberPicker orgId={orgId} value={member} label="Mitgliedsakte" onChange={setMember} />
        )}
        {isClub && editing && (
          <div className="small muted">Gilt für alle Rollen dieses Kontos hier.</div>
        )}
      </td>
      <td className="small">
        {editing ? (
          <div className="assignment-dates">
            <label>
              von
              <input
                type="date"
                className="inline-edit"
                required
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label>
              bis
              <input
                type="date"
                className="inline-edit"
                value={until}
                onChange={(e) => setUntil(e.target.value)}
              />
            </label>
            {error && <Alert kind="error">{error}</Alert>}
          </div>
        ) : (
          <>
            {formatDate(a.valid_from)} – {a.valid_until ? formatDate(a.valid_until) : 'heute'}
          </>
        )}
      </td>
      <td className="actions">
        {editing ? (
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy || !from}
              onClick={() =>
                void run(() =>
                  orgApi.updateAssignment(orgId, a.id, {
                    valid_from: from,
                    valid_until: until || null,
                    // Nur bei Änderung mitschicken: gilt für alle Rollen dieses Kontos
                    ...(isClub && (member?.id ?? null) !== (a.member_record?.id ?? null)
                      ? { member: member?.id ?? null }
                      : {}),
                  }),
                )
              }
            >
              Speichern
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => {
                setFrom(a.valid_from)
                setUntil(a.valid_until ?? '')
                setMember(a.member_record ?? null)
                setError(null)
                setEditing(false)
              }}
            >
              Abbrechen
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={() => void remove()}
            >
              Löschen
            </button>
          </div>
        ) : (
          <div className="button-row">
            <button
              type="button"
              className="link-button"
              onClick={() => {
                // Andere Zeilen desselben Kontos können die Akte inzwischen geändert haben
                setMember(a.member_record ?? null)
                setEditing(true)
              }}
            >
              Bearbeiten
            </button>
            {a.is_active && !a.valid_until && a.valid_from <= today && (
              <button type="button" className="link-button" onClick={onEnd}>
                Beenden
              </button>
            )}
            {span > 0 && a.is_active && a.has_mfa && a.user_email !== user?.email && (
              <button type="button" className="link-button" onClick={() => void resetMfa()}>
                2FA zurücksetzen
              </button>
            )}
          </div>
        )}
      </td>
    </tr>
  )
}
