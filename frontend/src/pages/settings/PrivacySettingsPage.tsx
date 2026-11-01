// Einstellungen › Datenschutz: beide Datenschutzhinweise an einer Stelle, in zwei Abschnitten.
// Für Mitglieder (Mitgliederverwaltung, hängt am Impressum der Einheit) und für Besucher der
// Webseite (Modul „Webseite“). Die Texte bleiben getrennt, je mit Entwurf und „Veröffentlichen“.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { imprintApi, privacyPath } from '../../api/imprint.ts'
import type { ImprintFields, ImprintState } from '../../api/imprint.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import type { Department } from '../../api/orgs.ts'
import { websiteApi } from '../../api/website.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { PrivacyPublish } from '../../components/PrivacyPublish.tsx'
import { Alert, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { PhotoSamplesCard } from '../competitions/PhotoSamples.tsx'
import { PrivacyCard } from '../website/WebsitePrivacy.tsx'
import { TextArea } from './TextArea.tsx'

// Gleicher Hinweis wie bei der Webseite (WebsitePrivacy.tsx), damit beide Abschnitte gleich lauten
const TEXT_HINT =
  'HUBIplan erzeugt einen Entwurf passend zu den Einstellungen (Module, Lastschrift, Meldung an übergeordnete Einheiten, Löschfrist); Angaben in eckigen Klammern bitte ergänzen. Erzeugen und Bearbeiten ändern nur den Entwurf (er speichert automatisch), öffentlich wird er erst mit „Veröffentlichen“. Ein Vorschlag, keine Rechtsberatung.'

type PrivacyFields = Pick<ImprintFields, 'privacy_mode' | 'privacy_text' | 'privacy_url'>

/** Datenschutzhinweise für Mitglieder (bzw. Datenschutzerklärung der Plattform). */
export function MemberPrivacyEditor({
  state,
  editable,
  save,
  publish,
}: {
  state: ImprintState
  editable: boolean
  save: (changes: Partial<ImprintFields>) => Promise<ImprintState>
  publish: () => Promise<ImprintState>
}) {
  const [publishError, setPublishError] = useState<string | null>(null)
  const [current, setCurrent] = useState(state)
  const form = useForm<PrivacyFields>({
    privacy_mode: state.imprint.privacy_mode,
    privacy_text: state.imprint.privacy_text,
    privacy_url: state.imprint.privacy_url,
  })
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) => save(changes), {
    enabled: editable,
    onSaved: (saved) => setCurrent(saved as ImprintState),
  })
  const isPlatform = state.organization.type === 'platform'
  const inherits = !isPlatform && current.imprint.mode === 'inherit' && !current.owner.is_self
  const key = isPlatform ? null : current.imprint.public_key

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      <h2>
        {isPlatform ? 'Datenschutzerklärung der Plattform' : 'Datenschutzhinweise für Mitglieder'}
      </h2>
      {!isPlatform && (
        <p className="muted small">
          Für Mitglieder von {state.organization.name}: Stammdaten, Beiträge, Lastschrift, Meldung
          an übergeordnete Einheiten, Löschfristen. Öffentlich unter{' '}
          <Link to={privacyPath(key)}>Datenschutzhinweise</Link>. {!inherits && TEXT_HINT}
        </p>
      )}
      {isPlatform && <p className="muted small">{TEXT_HINT}</p>}
      {editable && !inherits && <SaveStatus auto={auto} />}
      {inherits ? (
        <p className="muted">
          Es gelten die Datenschutzhinweise von {current.owner.name}, weil {state.organization.name}{' '}
          dessen Impressum übernimmt. Eigene Hinweise gibt es mit einem eigenen Impressum (
          <Link to="/einstellungen/impressum">Einstellungen › Impressum</Link>).
        </p>
      ) : (
        <fieldset disabled={!editable}>
          <SelectField
            label="Datenschutzhinweise"
            value={v.privacy_mode}
            error={errors.privacy_mode}
            onChange={(e) => set('privacy_mode', e.target.value as PrivacyFields['privacy_mode'])}
          >
            <option value="text">eigener Text</option>
            <option value="link">auf eigene Seite verlinken</option>
          </SelectField>
          {v.privacy_mode === 'link' ? (
            <Field
              label="Adresse der Datenschutzhinweise"
              type="url"
              placeholder="https://"
              value={v.privacy_url}
              error={errors.privacy_url}
              onChange={(e) => set('privacy_url', e.target.value)}
            />
          ) : (
            <>
              <TextArea
                label="Entwurf der Datenschutzhinweise"
                rows={14}
                value={v.privacy_text}
                error={errors.privacy_text}
                onChange={(val) => set('privacy_text', val)}
              />
              {editable && (
                <div className="button-row">
                  <button
                    type="button"
                    className="button"
                    onClick={async () => {
                      if (
                        v.privacy_text.trim() &&
                        !(await confirmDialog({
                          title: 'Datenschutzhinweise neu erzeugen?',
                          message:
                            'Der bisherige Text wird ersetzt. Eigene Ergänzungen bitte vorher sichern.',
                          confirmLabel: 'Neu erzeugen',
                        }))
                      )
                        return
                      set('privacy_text', current.template)
                    }}
                  >
                    {v.privacy_text.trim() ? 'Entwurf neu erzeugen' : 'Textentwurf erzeugen'}
                  </button>
                </div>
              )}
              <PrivacyPublish
                draft={v.privacy_text}
                publishedText={current.imprint.privacy_published_text}
                publishedAt={current.imprint.privacy_published_at}
                disabled={!editable}
                onFill={(next) => set('privacy_text', next)}
                onPublish={async () => {
                  setPublishError(null)
                  try {
                    if (!(await auto.flush())) {
                      setPublishError(
                        'Der Entwurf ist noch nicht gespeichert. Bitte zuerst speichern.',
                      )
                      return
                    }
                    setCurrent(await publish())
                  } catch (err) {
                    setPublishError(errorMessage(err))
                  }
                }}
              />
              {publishError && <Alert kind="error">{publishError}</Alert>}
            </>
          )}
        </fieldset>
      )}
    </form>
  )
}

/** Abschnitt „für Mitglieder“: die Einheit selbst oder eine ihrer Untereinheiten. */
function MemberSection() {
  const org = useActiveOrg()
  const { can } = useOrg()
  const editable = can(PERM.orgEdit)
  const [unitId, setUnitId] = useState<number | null>(null)
  const units = useLoad(
    () => (org.type === 'club' ? orgApi.departments(org.id) : Promise.resolve([] as Department[])),
    [org.id],
  )
  const state = useLoad(
    () => (unitId ? imprintApi.unit(org.id, unitId) : imprintApi.get(org.id)),
    [org.id, unitId],
  )
  const list = units.data ?? []

  return (
    <>
      {units.error && (
        <LoadError
          message={`Die ${org.department_label_plural} konnten nicht geladen werden; ihre Hinweise sind deshalb gerade nicht wählbar. ${units.error}`}
          onRetry={() => void units.reload()}
        />
      )}
      {list.length > 0 && (
        <div className="card card-wide">
          <SelectField
            label="Datenschutzhinweise für Mitglieder von"
            value={unitId ?? ''}
            hint={`${org.department_label_plural} übernehmen standardmäßig die Hinweise von ${org.name}.`}
            onChange={(e) => setUnitId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">{org.name}</option>
            {list.map((d) => (
              <option key={d.id} value={d.id}>
                {unitName(d)}
              </option>
            ))}
          </SelectField>
        </div>
      )}
      {state.error && <Alert kind="error">{state.error}</Alert>}
      {!state.data && !state.error && <p className="muted">Lädt …</p>}
      {state.data && state.data.organization.id === (unitId ?? org.id) && (
        <MemberPrivacyEditor
          key={state.data.organization.id}
          state={state.data}
          editable={editable}
          save={(changes) =>
            unitId
              ? imprintApi.updateUnit(org.id, unitId, changes)
              : imprintApi.update(org.id, changes)
          }
          publish={() => imprintApi.publishPrivacy(org.id, unitId)}
        />
      )}
    </>
  )
}

/** Abschnitt „für Besucher der Webseite“, nur mit Modul „Webseite“. */
function WebsiteSection() {
  const org = useActiveOrg()
  const { data, error, reload, setData } = useLoad(() => websiteApi.get(org.id), [org.id])
  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>
  if (!data.website) {
    return (
      <div className="card card-wide">
        <h2>Datenschutzhinweise der Webseite</h2>
        <p className="muted">
          Noch keine Webseite eingerichtet. Die Hinweise für Besucher erscheinen hier, sobald die
          Webseite unter <Link to="/webseite">Webseite</Link> eingerichtet ist.
        </p>
      </div>
    )
  }
  return <PrivacyCard data={data} website={data.website} onChange={setData} />
}

export function PrivacySettingsPage() {
  const org = useActiveOrg()
  const { can } = useOrg()
  // Mitglieder-Hinweise pflegt bei Untereinheiten die Einheit darüber (wie das Impressum)
  const members = org.type !== 'unit'
  const website = org.modules.includes('website') && can(PERM.websiteManage)
  // Spiegelausschnitte aus der Fotoerkennung: Einwilligung des Vereins
  const photos = org.modules.includes('competitions') && can(PERM.competitionsManage)
  return (
    <>
      <p className="muted small">
        Zwei getrennte Texte für zwei Personengruppen: Mitglieder erfahren, wie die
        Mitgliederverwaltung mit ihren Daten umgeht; Besucher der Webseite, was beim Besuch der
        Webseite verarbeitet wird.
      </p>
      {members && <MemberSection />}
      {website && <WebsiteSection />}
      {photos && <PhotoSamplesCard org={org.id} />}
      {!members && !website && (
        <Alert kind="info">
          Die Datenschutzhinweise für Mitglieder pflegt die übergeordnete Einheit.
        </Alert>
      )}
    </>
  )
}
