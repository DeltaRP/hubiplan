import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { newRequestKey } from '../../api/client.ts'
import { GENDERS, memberApi, todayIso } from '../../api/members.ts'
import type { Duplicate, Gender } from '../../api/members.ts'
import { orgApi, unitName } from '../../api/orgs.ts'
import { errorMessage, formatDate, useForm, useLoad } from '../../components/forms.ts'
import { useChangesGuard } from '../../components/leaveGuard.ts'
import { Alert, Field, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

type Step = 'person' | 'details'

export function AdmitPage() {
  const org = useActiveOrg()
  const terms = useTerms()
  const fed = !!terms.dv_has
  const navigate = useNavigate()
  const types = useLoad(() => memberApi.types(org.id), [org.id])
  const departments = useLoad(() => orgApi.departments(org.id), [org.id])
  const [step, setStep] = useState<Step>('person')
  const [duplicates, setDuplicates] = useState<Duplicate[]>([])
  const [linked, setLinked] = useState<Duplicate | null>(null)
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [transferSent, setTransferSent] = useState(false)

  // Ein Schlüssel je Aufnahme: erneutes Absenden legt die Person nicht doppelt an
  const [requestKey] = useState(newRequestKey)
  const form = useForm({
    last_name: '',
    first_name: '',
    birth_date: '',
    gender: '' as Gender,
    email: '',
    phone: '',
    street: '',
    postal_code: '',
    city: '',
    country: 'Deutschland',
    club_number: '',
    member_type: '',
    entry_date: todayIso(),
    department_ids: [] as number[],
  })
  const v = form.values
  const e = form.errors
  // Eingaben vor dem Absenden nicht unbemerkt verlieren (UX-Audit 31.10. W01)
  const [done, setDone] = useState(false)
  useChangesGuard(v, !done && !transferSent)

  async function checkPerson(ev: FormEvent) {
    ev.preventDefault()
    setChecking(true)
    setCheckError(null)
    try {
      const found = await memberApi.duplicates(org.id, v.last_name, v.first_name, v.birth_date)
      setDuplicates(found)
      setLinked(null)
      setStep('details')
    } catch (err) {
      setCheckError(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  async function save(ev: FormEvent) {
    ev.preventDefault()
    const payload: Record<string, unknown> = {
      ...v,
      member_type: Number(v.member_type),
      person: linked?.id ?? null,
    }
    if (linked) {
      delete payload.last_name
      delete payload.first_name
      delete payload.birth_date
    }
    const created = await form.submit(
      () => memberApi.admit(org.id, payload, requestKey),
      t('Aufgenommen.'),
    )
    if (created) {
      setDone(true)
      navigate(`/mitglieder/${(created as { id: number }).id}`)
    }
  }

  async function requestTransfer() {
    if (!linked) return
    const sent = await form.submit(
      () =>
        memberApi.createTransfer(org.id, {
          person: linked.id,
          member_type: Number(v.member_type),
          entry_date: v.entry_date,
          club_number: v.club_number,
          department_ids: v.department_ids,
          email: v.email,
          phone: v.phone,
          street: v.street,
          postal_code: v.postal_code,
          city: v.city,
          country: v.country,
        }),
      t('Wechselanfrage gestellt. Sobald {e_der_andere} zustimmt, wird die Aufnahme gespeichert.', {
        e_der_andere: terms.e_der_andere,
      }),
    )
    if (sent) setTransferSent(true)
  }

  const activeConflict =
    !!linked && !!e.member_type && e.member_type.includes('bereits aktives Mitglied')
  const activeTypes = types.data?.filter((tm) => !tm.is_archived) ?? []
  const selectedType = activeTypes.find((tm) => String(tm.id) === v.member_type)

  return (
    <section>
      <p>
        <Link to="/mitglieder">{t('← Mitglieder')}</Link>
      </p>
      <h1>{t('Mitglied aufnehmen')}</h1>

      {types.error && (
        <Alert kind="error">
          {t(
            'Die Mitgliedsarten konnten nicht geladen werden ({error}). Deine Eingaben bleiben erhalten.',
            { error: types.error },
          )}{' '}
          <button type="button" className="link-button" onClick={() => void types.reload()}>
            {t('Erneut laden')}
          </button>
        </Alert>
      )}
      {types.data && activeTypes.length === 0 && (
        <Alert kind="error">
          {t('Für die Aufnahme fehlt noch eine Mitgliedsart. Lege zuerst unter')}{' '}
          <Link to="/mitglieder/einrichtung/mitgliedsarten">
            {t('Mitglieder → Einrichtung → Mitgliedsarten')}
          </Link>{' '}
          {t('mindestens eine an.')}
        </Alert>
      )}

      {step === 'person' ? (
        <form className="card card-wide" onSubmit={checkPerson}>
          <h2>{t('1. Person')}</h2>
          <p className="muted small">
            {fed
              ? t(
                  'Zuerst prüfen wir, ob es die Person schon gibt – zum Beispiel als Mitglied {e_eines_anderen} {dv_im}.',
                  { e_eines_anderen: terms.e_eines_anderen, dv_im: terms.dv_im },
                )
              : t('Zuerst prüfen wir, ob es die Person schon gibt.')}
          </p>
          <div className="grid-4">
            <Field
              label={t('Name')}
              required
              value={v.last_name}
              onChange={(ev) => form.set('last_name', ev.target.value)}
            />
            <Field
              label={t('Vorname')}
              required
              value={v.first_name}
              onChange={(ev) => form.set('first_name', ev.target.value)}
            />
            <Field
              label={t('Geburtsdatum')}
              type="date"
              required
              value={v.birth_date}
              onChange={(ev) => form.set('birth_date', ev.target.value)}
            />
            <SelectField
              label={t('Geschlecht')}
              value={v.gender}
              onChange={(ev) => form.set('gender', ev.target.value as Gender)}
            >
              {GENDERS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </SelectField>
          </div>
          {checkError && <Alert kind="error">{checkError}</Alert>}
          <button type="submit" className="button button-primary" disabled={checking}>
            {t('Weiter')}
          </button>
        </form>
      ) : (
        <form className="stack" onSubmit={save}>
          {duplicates.length > 0 && (
            <div className="card card-wide">
              <h2>{t('Mögliche Treffer')}</h2>
              <p className="muted small">
                {fed
                  ? t(
                      'Ist eine dieser Personen gemeint? Dann wird sie verknüpft: Verbandsnummer und Eintritt in {dv_akk} bleiben erhalten.',
                      { dv_akk: terms.dv_akk },
                    )
                  : t('Ist eine dieser Personen gemeint? Dann wird sie verknüpft.')}
              </p>
              <ul className="duplicates">
                {duplicates.map((d) => (
                  <li key={d.id}>
                    <label className="checkbox">
                      <input
                        type="radio"
                        name="duplicate"
                        disabled={d.already_member_here}
                        checked={linked?.id === d.id}
                        onChange={() => setLinked(d)}
                      />
                      <span>
                        <strong>
                          {d.last_name}, {d.first_name}
                        </strong>{' '}
                        · {formatDate(d.birth_date)}
                        {d.member_number &&
                          t(' · Verbandsnr. {member_number}', { member_number: d.member_number })}
                        {d.clubs &&
                          d.clubs.length > 0 &&
                          t(' · Mitglied in: {x}', { x: d.clubs.join(', ') })}
                        {d.already_member_here &&
                          t(' · ist oder war schon Mitglied hier (Wiedereintritt in der Akte)')}
                      </span>
                    </label>
                  </li>
                ))}
                <li>
                  <label className="checkbox">
                    <input
                      type="radio"
                      name="duplicate"
                      checked={linked === null}
                      onChange={() => setLinked(null)}
                    />
                    <span>{t('Keine davon – neue Person anlegen')}</span>
                  </label>
                </li>
              </ul>
            </div>
          )}

          <div className="card card-wide">
            <h2>{t('2. Mitgliedschaft')}</h2>
            <p className="muted small">
              {v.last_name}, {v.first_name} · {formatDate(v.birth_date)}{' '}
              <button type="button" className="link-button" onClick={() => setStep('person')}>
                {t('ändern')}
              </button>
            </p>
            <div className="grid-3">
              <SelectField
                label={t('Mitgliedsart')}
                required
                value={v.member_type}
                error={e.member_type}
                onChange={(ev) => form.set('member_type', ev.target.value)}
              >
                <option value="">{t('– bitte wählen –')}</option>
                {activeTypes.map((tm) => (
                  <option key={tm.id} value={tm.id}>
                    {tm.name}
                  </option>
                ))}
              </SelectField>
              <Field
                label={t('Eintritt')}
                type="date"
                required
                value={v.entry_date}
                error={e.entry_date}
                onChange={(ev) => form.set('entry_date', ev.target.value)}
              />
              <Field
                label={t('Mitgliedsnummer {e_im} (optional)', { e_im: terms.e_im })}
                value={v.club_number}
                error={e.club_number}
                onChange={(ev) => form.set('club_number', ev.target.value)}
              />
            </div>
            {selectedType && (
              <p className="muted small">
                {selectedType.active ? 'aktiv' : t('nicht aktiv')}
                {fed &&
                  (selectedType.reported
                    ? t(' · wird an {dv_akk} gemeldet', { dv_akk: terms.dv_akk })
                    : t(' · wird nicht gemeldet'))}
              </p>
            )}
            {departments.data && departments.data.length > 0 && (
              <fieldset className="field">
                <span>{org.department_label_plural} (optional)</span>
                <div className="chips">
                  {departments.data
                    .filter((d) => d.is_active)
                    .map((d) => (
                      <label key={d.id} className="checkbox chip">
                        <input
                          type="checkbox"
                          checked={v.department_ids.includes(d.id)}
                          onChange={(ev) =>
                            form.set(
                              'department_ids',
                              ev.target.checked
                                ? [...v.department_ids, d.id]
                                : v.department_ids.filter((x) => x !== d.id),
                            )
                          }
                        />
                        <span>{unitName(d)}</span>
                      </label>
                    ))}
                </div>
                {e.department_ids && <small className="field-error">{e.department_ids}</small>}
              </fieldset>
            )}
          </div>

          <div className="card card-wide">
            <h2>{t('3. Kontakt und Anschrift')}</h2>
            <div className="grid-2">
              <Field
                label={t('E-Mail-Adresse (optional)')}
                type="email"
                hint={t(
                  'Ohne E-Mail erhält das Mitglied Schreiben per Brief. Ein Online-Zugang kann später eingerichtet werden.',
                )}
                value={v.email}
                error={e.email}
                onChange={(ev) => form.set('email', ev.target.value)}
              />
              <Field
                label={t('Telefon (optional)')}
                value={v.phone}
                error={e.phone}
                onChange={(ev) => form.set('phone', ev.target.value)}
              />
            </div>
            <Field
              label={t('Straße und Hausnummer')}
              required
              value={v.street}
              error={e.street}
              onChange={(ev) => form.set('street', ev.target.value)}
            />
            <div className="grid-3">
              <Field
                label="PLZ"
                required
                value={v.postal_code}
                error={e.postal_code}
                onChange={(ev) => form.set('postal_code', ev.target.value)}
              />
              <Field
                label={t('Ort')}
                required
                value={v.city}
                error={e.city}
                onChange={(ev) => form.set('city', ev.target.value)}
              />
              <Field
                label={t('Land')}
                value={v.country}
                error={e.country}
                onChange={(ev) => form.set('country', ev.target.value)}
              />
            </div>
          </div>

          {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
          {e.person && <Alert kind="error">{e.person}</Alert>}
          {activeConflict && !transferSent && (
            <div className="card card-wide">
              <p>
                {t('Ihr könnt {e_beim_anderen} eine', { e_beim_anderen: terms.e_beim_anderen })}{' '}
                <strong>{t('Wechselanfrage')}</strong>{' '}
                {t(
                  'stellen. Dort bestätigt man dann den Austritt oder den Wechsel zu einer nicht aktiven Art.',
                )}
              </p>
              <button
                type="button"
                className="button button-primary"
                onClick={() => void requestTransfer()}
              >
                {t('Wechselanfrage stellen')}
              </button>
            </div>
          )}
          {transferSent && (
            <Link to="/mitglieder/anfragen" className="button button-ghost">
              {t('Zu den Wechselanfragen')}
            </Link>
          )}
          <div className="button-row">
            <button type="submit" className="button button-primary" disabled={form.busy}>
              {t('Aufnehmen')}
            </button>
            <Link to="/mitglieder" className="button button-ghost">
              {t('Abbrechen')}
            </Link>
          </div>
        </form>
      )}
    </section>
  )
}
