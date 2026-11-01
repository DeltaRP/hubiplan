// Mitglieder: Liste, Entwicklung, Jubiläen, Anfragen, Import und Einrichtung.
// Unterpunkte stehen in der Seitenleiste (siehe members/access.ts), innerhalb
// eines Unterpunkts führen Reiter weiter.
import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { PERM } from '../api/orgs.ts'
import { Tabs } from '../components/ui.tsx'
import { useActiveOrg } from '../org/OrgContext.tsx'
import { FieldsPage } from './settings/FieldsPage.tsx'
import { MemberTypesPage } from './settings/MemberTypesPage.tsx'
import { ownMembers, requestTabs, setupTabs } from './members/access.ts'
import type { NavItem } from './members/access.ts'
import { AdmitPage } from './members/AdmitPage.tsx'
import { HonoraryTitlesPage } from './members/HonoraryTitlesPage.tsx'
import { MemberFilePage } from './members/MemberFilePage.tsx'
import { MemberListPage } from './members/MemberListPage.tsx'
import { MemberPortalSettings, MemberDurationSettings } from './members/SetupPages.tsx'
import { TransfersPage } from './members/TransfersPage.tsx'
import { JubileesPage } from './members/JubileesPage.tsx'
import { ImportPage } from './members/ImportPage.tsx'
import { FederationMembersPage } from './members/FederationMembersPage.tsx'
import { ChangeRequestsPage } from './members/ChangeRequestsPage.tsx'
import { ChroniclePage } from './members/ChroniclePage.tsx'
import { OfficesPage } from './members/OfficesPage.tsx'
import { MembersDevelopmentPage } from './members/DevelopmentPage.tsx'
import { MovedCirculars } from './circulars/CircularsPage.tsx'
import { t } from '../i18n/index.ts'

export function MembersSection({
  title,
  tabs,
  actions,
  children,
}: {
  title: string
  tabs?: NavItem[]
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="muted small eyebrow">{t('Mitglieder')}</p>
          <h1>{title}</h1>
        </div>
        {actions}
      </div>
      {tabs && tabs.length > 1 && <Tabs items={tabs} />}
      {children}
    </section>
  )
}

/** Alte Adressen (/mitglieder/wechsel, /mitglieder/aenderungen) samt Filtern weiterleiten. */
function Moved({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={`${to}${search}`} replace />
}

export function MembersPage() {
  const org = useActiveOrg()
  if (org.type !== 'club' && org.type !== 'federation') return <Navigate to="/" replace />
  return (
    <Routes>
      <Route path="rundschreiben/*" element={<MovedCirculars />} />
      <Route path="einrichtung/*" element={<SetupArea />} />
      {ownMembers(org) && (
        <Route path="verbund/*" element={<FederationMembersPage prefix="/mitglieder/verbund" />} />
      )}
      <Route
        path="*"
        element={
          org.type === 'federation' && !ownMembers(org) ? (
            <FederationMembersPage />
          ) : (
            <ClubMembers />
          )
        }
      />
    </Routes>
  )
}

function ClubMembers() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const list = <Navigate to="/mitglieder" replace />
  return (
    <Routes>
      <Route index element={<MemberListPage />} />
      <Route path="neu" element={canEdit ? <AdmitPage /> : list} />
      <Route
        path="anfragen"
        element={
          <MembersSection title={t('Wechselanfragen')} tabs={requestTabs()}>
            <TransfersPage />
          </MembersSection>
        }
      />
      <Route
        path="anfragen/aenderungen"
        element={
          <MembersSection title={t('Änderungsmeldungen')} tabs={requestTabs()}>
            <ChangeRequestsPage />
          </MembersSection>
        }
      />
      <Route path="wechsel" element={<Moved to="/mitglieder/anfragen" />} />
      <Route path="aenderungen" element={<Moved to="/mitglieder/anfragen/aenderungen" />} />
      <Route
        path="jubilaeen"
        element={
          <MembersSection title={t('Jubiläen')}>
            <JubileesPage />
          </MembersSection>
        }
      />
      <Route path="entwicklung" element={<MembersDevelopmentPage />} />
      <Route path="wuerdentraeger/*" element={<ChroniclePage />} />
      <Route path="aemter/*" element={<OfficesPage />} />
      <Route path="chronik" element={<Moved to="/mitglieder/wuerdentraeger" />} />
      <Route path="chronik/wuerden" element={<Moved to="/mitglieder/wuerdentraeger/wuerden" />} />
      <Route path="chronik/import" element={<Moved to="/mitglieder/wuerdentraeger/import" />} />
      <Route
        path="import"
        element={
          canEdit ? (
            <MembersSection title={t('Altdaten importieren')}>
              <ImportPage />
            </MembersSection>
          ) : (
            list
          )
        }
      />
      <Route path=":id" element={<MemberFilePage />} />
    </Routes>
  )
}

function SetupArea() {
  const org = useActiveOrg()
  const tabs = setupTabs(org)
  const club = org.type === 'club'
  const types = club || ownMembers(org)
  const page = (title: string, body: ReactNode) => (
    <MembersSection title={title} tabs={tabs}>
      {body}
    </MembersSection>
  )
  return (
    <Routes>
      <Route index element={<Navigate to={tabs[0].to} replace />} />
      {types && (
        <Route path="mitgliedsarten" element={page(t('Einrichtung'), <MemberTypesPage />)} />
      )}
      <Route path="ehrungen" element={page(t('Einrichtung'), <HonoraryTitlesPage />)} />
      {/* frühere Adresse (Lesezeichen) */}
      <Route
        path="ehrentitel"
        element={<Navigate to="/mitglieder/einrichtung/ehrungen" replace />}
      />
      <Route path="zusatzfelder" element={page(t('Einrichtung'), <FieldsPage />)} />
      <Route path="jubilaeen" element={page(t('Einrichtung'), <MemberDurationSettings />)} />
      {club && (
        <Route
          path="mitgliederbereich"
          element={page(t('Einrichtung'), <MemberPortalSettings />)}
        />
      )}
      <Route path="*" element={<Navigate to={tabs[0].to} replace />} />
    </Routes>
  )
}
