import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { PERM } from './api/orgs.ts'
import { RequireAuth } from './auth/RequireAuth.tsx'
import { Layout } from './components/Layout.tsx'
import { PublicShell } from './components/ImprintFooter.tsx'
import { AccessibilityPage, ImprintPage, LicensePage, PrivacyPage } from './pages/ImprintPages.tsx'
import { useOrg } from './org/OrgContext.tsx'
import { LoginPage } from './pages/LoginPage.tsx'
import {
  VerbundConfirmPage,
  VerbundFinishPage,
  VerbundStartPage,
} from './pages/VerbundLoginPages.tsx'
import { AppPairNoticePage, NoAccessPage, NotFoundPage } from './pages/NoticePages.tsx'
import {
  EmailConfirmPage,
  LoginLinkRedeemPage,
  LoginLinkRequestPage,
} from './pages/LoginLinkPages.tsx'
import { PasswordRequestPage, PasswordResetPage } from './pages/PasswordPages.tsx'
import { PublicCardPage } from './pages/PublicCardPage.tsx'
import { PublicPhotoPage } from './pages/PublicPhotoPage.tsx'
import { PublicOptOutPage } from './pages/PublicOptOutPage.tsx'
import { PublicCircularConfirmPage } from './pages/PublicCircularConfirmPage.tsx'
import { lazyPage } from './lazyPages.ts'
import { NoLearningAids } from './learning/LearningContext.tsx'
import { LeaveGuard } from './components/leaveGuard.ts'

const ImprintSettingsPage = lazyPage(
  () => import('./pages/settings/ImprintSettingsPage.tsx'),
  'ImprintSettingsPage',
)
const PrivacySettingsPage = lazyPage(
  () => import('./pages/settings/PrivacySettingsPage.tsx'),
  'PrivacySettingsPage',
)
const PlatformImprintPage = lazyPage(
  () => import('./pages/settings/ImprintSettingsPage.tsx'),
  'PlatformImprintPage',
)
const HomePage = lazyPage(() => import('./pages/HomePage.tsx'), 'HomePage')
const DepartmentArea = lazyPage(
  () => import('./pages/department/DepartmentArea.tsx'),
  'DepartmentArea',
)
const PortalPage = lazyPage(() => import('./pages/portal/PortalPage.tsx'), 'PortalPage')
const OutboxPage = lazyPage(() => import('./pages/settings/OutboxPage.tsx'), 'OutboxPage')
const PeeringPage = lazyPage(() => import('./pages/settings/PeeringPage.tsx'), 'PeeringPage')
const CircularsPage = lazyPage(() => import('./pages/circulars/CircularsPage.tsx'), 'CircularsPage')
const MembersPage = lazyPage(() => import('./pages/MembersPage.tsx'), 'MembersPage')
const FinanzenPage = lazyPage(() => import('./pages/finanzen/FinanzenPage.tsx'), 'FinanzenPage')
const DocumentsPage = lazyPage(() => import('./pages/documents/DocumentsPage.tsx'), 'DocumentsPage')
const WebsitePage = lazyPage(() => import('./pages/website/WebsitePage.tsx'), 'WebsitePage')
const EventsPage = lazyPage(() => import('./pages/events/EventsPage.tsx'), 'EventsPage')
const CompetitionsPage = lazyPage(
  () => import('./pages/competitions/CompetitionsPage.tsx'),
  'CompetitionsPage',
)
const StandPage = lazyPage(() => import('./pages/competitions/StandPage.tsx'), 'StandPage')
const PlatformLayout = lazyPage(
  () => import('./pages/platform/PlatformPages.tsx'),
  'PlatformLayout',
)
const PlatformMailPage = lazyPage(
  () => import('./pages/platform/PlatformPages.tsx'),
  'PlatformMailPage',
)
const PlatformOrgsPage = lazyPage(
  () => import('./pages/platform/PlatformPages.tsx'),
  'PlatformOrgsPage',
)
const PlatformSettingsPage = lazyPage(
  () => import('./pages/platform/PlatformPages.tsx'),
  'PlatformSettingsPage',
)
const PlatformTransferPage = lazyPage(
  () => import('./pages/platform/PlatformPages.tsx'),
  'PlatformTransferPage',
)
const GlossaryPage = lazyPage(() => import('./learning/GlossaryPage.tsx'), 'GlossaryPage')
const AccountPage = lazyPage(() => import('./pages/settings/AccountPage.tsx'), 'AccountPage')
const AccountLoginPage = lazyPage(
  () => import('./pages/settings/AccountPage.tsx'),
  'AccountLoginPage',
)
const AccountAppPage = lazyPage(() => import('./pages/settings/AccountPage.tsx'), 'AccountAppPage')
const AccountTemplatesPage = lazyPage(
  () => import('./pages/settings/AccountPage.tsx'),
  'AccountTemplatesPage',
)
const LetterheadPage = lazyPage(() => import('./pages/LetterheadPage.tsx'), 'LetterheadPage')
const LetterheadSettingsPage = lazyPage(
  () => import('./pages/settings/LetterheadSettingsPage.tsx'),
  'LetterheadSettingsPage',
)
const AppearancePage = lazyPage(
  () => import('./pages/settings/AppearancePage.tsx'),
  'AppearancePage',
)
const AuditPage = lazyPage(() => import('./pages/settings/AuditPage.tsx'), 'AuditPage')
const UnitsArea = lazyPage(() => import('./pages/settings/UnitsPage.tsx'), 'UnitsArea')
const UnitsRedirect = lazyPage(() => import('./pages/settings/UnitsPage.tsx'), 'UnitsRedirect')
const DataTransferPage = lazyPage(
  () => import('./pages/settings/DataTransferPage.tsx'),
  'DataTransferPage',
)
const OrganizationPage = lazyPage(
  () => import('./pages/settings/OrganizationPage.tsx'),
  'OrganizationPage',
)
const RolesPage = lazyPage(() => import('./pages/settings/RolesPage.tsx'), 'RolesPage')
const SettingsLayout = lazyPage(
  () => import('./pages/settings/SettingsLayout.tsx'),
  'SettingsLayout',
)

/** Seite nur zeigen, wenn eine Organisation aktiv ist (und ggf. ein Recht vorliegt). */
function RequireOrg({ permission, children }: { permission?: string; children: ReactNode }) {
  const { active, can } = useOrg()
  if (!active) return <NoAccessPage reason="workspace" />
  if (permission && !can(permission)) return <NoAccessPage reason="right" />
  return <>{children}</>
}

function RequireDept({ children }: { children: ReactNode }) {
  const { activeDept } = useOrg()
  if (!activeDept) return <NoAccessPage reason="workspace" />
  return <>{children}</>
}

const LEGACY_KASSE: Record<string, string> = {
  '': '/finanzen',
  buchungen: '/finanzen/kassenbuch',
  konten: '/finanzen/einstellungen/konten',
  kategorien: '/finanzen/einstellungen/kategorien',
  abschluss: '/finanzen/abschluss/jahresabschluss',
}

const LEGACY_BEITRAEGE: Record<string, string> = {
  '': '/finanzen/rechnungen',
  laeufe: '/finanzen/rechnungen/beitragslaeufe',
  mahnungen: '/finanzen/rechnungen/mahnungen',
  dachverband: '/finanzen/rechnungen/dachverband',
  lastschrift: '/finanzen/lastschrift',
  regeln: '/finanzen/einstellungen',
}

/** Leitet alte Lesezeichen (/kasse/…, /beitraege/…) samt Filtern auf Finanzen um. */
function LegacyRedirect({ map }: { map: Record<string, string> }) {
  const rest = useParams()['*'] ?? ''
  const { search } = useLocation()
  const target = map[rest.replace(/\/$/, '')] ?? '/finanzen'
  return <Navigate to={`${target}${search}`} replace />
}

export default function App() {
  return (
    <>
      <LeaveGuard />
      <Routes>
        <Route element={<PublicShell />}>
          <Route path="/anmelden" element={<LoginPage />} />
          <Route path="/anmelden/link" element={<LoginLinkRequestPage />} />
          <Route path="/anmelden/link/:token" element={<LoginLinkRedeemPage />} />
          <Route path="/konto/email/:token" element={<EmailConfirmPage />} />
          <Route path="/passwort-vergessen" element={<PasswordRequestPage />} />
          <Route path="/foto/:token" element={<PublicPhotoPage />} />
          <Route path="/app/verbinden" element={<AppPairNoticePage />} />
          <Route path="/verbund/start" element={<VerbundStartPage />} />
          <Route path="/verbund/angemeldet" element={<VerbundFinishPage />} />
          <Route
            path="/verbund/anmelden"
            element={
              <RequireAuth>
                <VerbundConfirmPage />
              </RequireAuth>
            }
          />
          <Route path="/rundschreiben/abmelden/:token" element={<PublicOptOutPage />} />
          <Route path="/rundschreiben/bestaetigen/:token" element={<PublicCircularConfirmPage />} />
          <Route path="/ausweis/:token" element={<PublicCardPage />} />
          <Route path="/passwort-zuruecksetzen/:key" element={<PasswordResetPage />} />
          <Route path="/impressum" element={<ImprintPage />} />
          <Route path="/impressum/:key" element={<ImprintPage />} />
          <Route path="/datenschutz" element={<PrivacyPage />} />
          <Route path="/datenschutz/:key" element={<PrivacyPage />} />
          <Route path="/lizenz" element={<LicensePage />} />
          <Route path="/barrierefreiheit" element={<AccessibilityPage />} />
        </Route>
        {/* Standmodus: Vollbild ohne Menü (Tablet, Handy am Schießstand) */}
        <Route
          path="/stand/:org/:id"
          element={
            <RequireAuth>
              <StandPage />
            </RequireAuth>
          }
        />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<HomePage />} />
          <Route
            path="mitglieder/*"
            element={
              <RequireOrg permission={PERM.membersView}>
                <MembersPage />
              </RequireOrg>
            }
          />
          <Route
            path="finanzen/*"
            element={
              <RequireOrg>
                <FinanzenPage />
              </RequireOrg>
            }
          />
          {/* alte Adressen von Kasse und Beiträge */}
          <Route path="kasse/*" element={<LegacyRedirect map={LEGACY_KASSE} />} />
          <Route path="beitraege/*" element={<LegacyRedirect map={LEGACY_BEITRAEGE} />} />
          <Route
            path="abteilung/*"
            element={
              <RequireDept>
                <DepartmentArea />
              </RequireDept>
            }
          />
          <Route path="rundschreiben/*" element={<CircularsPage />} />
          <Route path="termine/*" element={<EventsPage />} />
          <Route
            path="wettbewerbe/*"
            element={
              <RequireOrg>
                <CompetitionsPage />
              </RequireOrg>
            }
          />
          <Route path="dokumente/*" element={<DocumentsPage />} />
          {/* Rückkehr von Meta: außerhalb von /webseite/, das Caddy an die Vereinswebseite gibt */}
          <Route path="social-rueckkehr" element={<SocialReturn />} />
          <Route
            path="webseite/*"
            element={
              <RequireOrg>
                <WebsitePage />
              </RequireOrg>
            }
          />
          <Route
            path="mein-bereich/*"
            element={
              <NoLearningAids>
                <PortalPage />
              </NoLearningAids>
            }
          />
          <Route path="mein-konto" element={<AccountPage />} />
          <Route path="mein-konto/anmeldung" element={<AccountLoginPage />} />
          <Route path="mein-konto/app" element={<AccountAppPage />} />
          <Route path="mein-konto/briefvorlage" element={<AccountTemplatesPage />} />
          <Route path="briefvorlage" element={<LetterheadPage />} />
          <Route path="glossar" element={<GlossaryPage />} />
          <Route
            path="untereinheiten"
            element={
              <RequireOrg>
                <UnitsArea />
              </RequireOrg>
            }
          />
          {/* alte Adresse von „Mein Konto“ */}
          <Route path="einstellungen/konto" element={<Navigate to="/mein-konto" replace />} />
          <Route path="einstellungen" element={<SettingsLayout />}>
            <Route
              path="organisation"
              element={
                <RequireOrg>
                  <OrganizationPage />
                </RequireOrg>
              }
            />
            <Route
              path="impressum"
              element={
                <RequireOrg>
                  <ImprintSettingsPage />
                </RequireOrg>
              }
            />
            <Route
              path="datenschutz"
              element={
                <RequireOrg>
                  <PrivacySettingsPage />
                </RequireOrg>
              }
            />
            <Route
              path="briefbogen"
              element={
                <RequireOrg>
                  <LetterheadSettingsPage />
                </RequireOrg>
              }
            />
            {/* Untereinheiten stehen jetzt im Hauptmenü; frühere Adressen */}
            <Route path="untereinheiten" element={<UnitsRedirect />} />
            <Route path="abteilungen" element={<UnitsRedirect />} />
            <Route path="vereine" element={<UnitsRedirect />} />
            {/* Mitgliedsarten und Zusatzfelder stehen unter Mitglieder › Einrichtung */}
            <Route
              path="zusatzfelder"
              element={<Navigate to="/mitglieder/einrichtung/zusatzfelder" replace />}
            />
            <Route
              path="mitgliedsarten"
              element={<Navigate to="/mitglieder/einrichtung/mitgliedsarten" replace />}
            />
            <Route
              path="rollen"
              element={
                <RequireOrg permission={PERM.rolesManage}>
                  <RolesPage />
                </RequireOrg>
              }
            />
            <Route
              path="erscheinungsbild"
              element={
                <RequireOrg>
                  <AppearancePage />
                </RequireOrg>
              }
            />
            <Route
              path="protokoll"
              element={
                <RequireOrg permission={PERM.auditView}>
                  <AuditPage />
                </RequireOrg>
              }
            />
            <Route
              path="postausgang"
              element={
                <RequireOrg permission={PERM.auditView}>
                  <OutboxPage />
                </RequireOrg>
              }
            />
            <Route
              path="verbund"
              element={
                <RequireOrg permission={PERM.peeringManage}>
                  <PeeringPage />
                </RequireOrg>
              }
            />
            <Route
              path="datenuebernahme"
              element={
                <RequireOrg>
                  <DataTransferPage />
                </RequireOrg>
              }
            />
          </Route>
          <Route
            path="plattform"
            element={
              <RequireOrg permission={PERM.platformManage}>
                <PlatformLayout />
              </RequireOrg>
            }
          >
            <Route path="organisationen" element={<PlatformOrgsPage />} />
            <Route path="einstellungen" element={<PlatformSettingsPage />} />
            <Route path="impressum" element={<PlatformImprintPage />} />
            <Route path="postfach" element={<PlatformMailPage />} />
            <Route path="datenuebernahme" element={<PlatformTransferPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

/** Rückkehr nach dem Verbinden mit Meta: weiter zur Seite „Social Media“. */
function SocialReturn() {
  const { search } = useLocation()
  return <Navigate to={`/webseite/beitraege${search}`} replace />
}
