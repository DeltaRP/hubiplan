// Einstellungen → Datenübernahme (Export und Import). Vereine des Dachverbands: ClubsPage.tsx
import { PERM, orgApi } from '../../api/orgs.ts'
import { ExportSection, ImportSection } from '../../components/DataTransfer.tsx'
import { useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { useOrg } from '../../org/OrgContext.tsx'
import { t } from '../../i18n/index.ts'

export function DataTransferPage() {
  const { active, can } = useOrg()
  const isClub = active?.type === 'club'
  const departments = useLoad(
    () => (active && isClub ? orgApi.departments(active.id) : Promise.resolve([])),
    [active?.id],
  )
  if (!active) return null
  const base = { org: active.id }
  const canImport = isClub && can(PERM.orgEdit)
  return (
    <>
      {can(PERM.dataExport) ? (
        <ExportSection base={base} departments={isClub ? (departments.data ?? []) : undefined} />
      ) : (
        <Alert kind="info">{t('Für den vollständigen Export fehlt dir die Berechtigung.')}</Alert>
      )}
      {canImport && (
        <ImportSection base={base} target="club" onImported={() => void departments.reload()} />
      )}
    </>
  )
}
