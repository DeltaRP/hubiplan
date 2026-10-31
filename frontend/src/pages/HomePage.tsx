import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.tsx'
import { useOrg } from '../org/OrgContext.tsx'
import { calendarBase } from '../api/events.ts'
import { UpcomingTile } from '../components/calendar/UpcomingTile.tsx'
import { BirthdayTile, JubileeTile } from './members/JubileesPage.tsx'
import { OpenTasksTile } from '../components/OpenTasksTile.tsx'
import { imprintApi } from '../api/imprint.ts'
import { PERM } from '../api/orgs.ts'
import type { OrgSummary } from '../api/orgs.ts'
import { useLoad } from '../components/forms.ts'
import { ImprintMissing } from './settings/ImprintSettingsPage.tsx'
import { HomeLetterheadNotices } from './LetterheadPage.tsx'

/** Vorstand: Hinweis, wenn im Impressum Pflichtangaben fehlen. */
function ImprintHint({ org }: { org: OrgSummary }) {
  const show =
    (org.type === 'club' || org.type === 'federation') && org.permissions.includes(PERM.orgEdit)
  const { data } = useLoad(
    () => (show ? imprintApi.get(org.id) : Promise.resolve(null)),
    [org.id, show],
  )
  return data ? <ImprintMissing missing={data.missing} /> : null
}
import { PortalTasks } from './portal/PortalPage.tsx'

/** Rechte, mit denen es offene Aufgaben geben kann (Entscheidungen) */
const TASK_PERMS = [PERM.membersEdit, PERM.photosManage, PERM.eventsManage]

function showsOpenTasks(org: OrgSummary): boolean {
  if (org.type !== 'club' && org.type !== 'federation') return false
  return TASK_PERMS.some((p) => org.permissions.includes(p))
}

export function HomePage() {
  const { user } = useAuth()
  const { active, activeDept, activePortal } = useOrg()

  if (!active && activeDept) {
    return (
      <section>
        <h1 className="sr-only">{activeDept.name}</h1>
        <HomeLetterheadNotices />
        <div className="tiles">
          <div className="card tile">
            <h2>{activeDept.label}</h2>
            <p>
              <Link to="/abteilung">Mitglieder der {activeDept.label} ansehen</Link>
            </p>
            <p>
              <Link to="/briefvorlage">Briefvorlage erstellen</Link>
            </p>
          </div>
          {activeDept.events_enabled && <UpcomingTile base={calendarBase.dept(activeDept.id)} />}
        </div>
      </section>
    )
  }

  if (!active && activePortal) {
    return (
      <section>
        <h1>Hallo {activePortal.first_name}</h1>
        <PortalTasks entry={activePortal} />
        {activePortal.events_enabled && (
          <div className="tiles">
            <UpcomingTile base={calendarBase.portal(activePortal.id)} />
          </div>
        )}
      </section>
    )
  }

  if (!active) {
    return (
      <section>
        <h1>Willkommen</h1>
        <div className="card">
          <p>Deinem Konto ({user?.email}) ist noch keine Organisation zugeordnet.</p>
          <p className="muted small">
            Bitte wende dich an deinen Vorstand. Dein Konto und die Zwei-Faktor-Anmeldung kannst du
            unter <Link to="/mein-konto/anmeldung">Mein Konto › Anmeldung &amp; Sicherheit</Link>{' '}
            verwalten.
          </p>
        </div>
      </section>
    )
  }

  // Name und Dachverband stehen schon im Kopf; die Überschrift ist nur für Screenreader.
  return (
    <section>
      <h1 className="sr-only">{active.name}</h1>
      <ImprintHint org={active} />
      <HomeLetterheadNotices />
      <div className="tiles">
        {showsOpenTasks(active) && <OpenTasksTile org={active} />}
        {(active.type === 'club' || active.type === 'federation') &&
          active.modules.includes('events') && <UpcomingTile base={calendarBase.org(active.id)} />}
        {active.type === 'club' &&
        active.modules.includes('members') &&
        active.permissions.includes('members.view') ? (
          <>
            <JubileeTile />
            <BirthdayTile />
          </>
        ) : (
          !active.modules.includes('events') && (
            <div className="card tile">
              <h2>Übersicht</h2>
              <p className="muted">Hier erscheinen Kacheln der Module.</p>
            </div>
          )
        )}
      </div>
    </section>
  )
}
