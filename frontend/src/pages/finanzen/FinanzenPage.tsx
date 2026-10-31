// Finanzen: Kasse und Beiträge/Rechnungen unter einem Menüpunkt.
// Unterpunkte stehen in der Seitenleiste (siehe access.ts), innerhalb eines
// Unterpunkts führen Reiter weiter.
import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Tabs } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { DebitsPage, MandatesPage } from '../billing/DebitsPage.tsx'
import { DunningsPage } from '../billing/DunningsPage.tsx'
import { InvoicesPage } from '../billing/InvoicesPage.tsx'
import { ReceivedPage } from '../billing/ReceivedPage.tsx'
import { BillingSettingsPage, DunningLevelsPage, FeeRulesPage } from '../billing/RulesPage.tsx'
import { RunsPage } from '../billing/RunsPage.tsx'
import { BankStatementsPage } from '../finance/BankStatementsPage.tsx'
import { BookingsPage } from '../finance/BookingsPage.tsx'
import { CashCountsPage } from '../finance/CashCountsPage.tsx'
import { CashReceiptsArea } from '../finance/CashReceiptsPage.tsx'
import { ReservesPage } from '../finance/ReservesPage.tsx'
import { ClosingsPage } from '../finance/ClosingsPage.tsx'
import { DonationsArea } from '../finance/DonationsPage.tsx'
import { ProjectsArea } from '../finance/ProjectsPage.tsx'
import { AccountsPage, CategoriesPage } from '../finance/MasterDataPages.tsx'
import { financeAccess, invoiceTabs, settingsTabs } from './access.ts'
import type { FinanceAccess, NavItem } from './access.ts'
import { FinanceDevelopment } from './DevelopmentPage.tsx'
import { EvaluationPage, FinanceOverview } from './OverviewPages.tsx'

function Section({
  title,
  readOnly,
  tabs,
  children,
}: {
  title: string
  readOnly?: boolean
  tabs?: NavItem[]
  children: ReactNode
}) {
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="muted small eyebrow">Finanzen</p>
          <h1>{title}</h1>
        </div>
        {readOnly && <span className="muted small push-right">nur lesen</span>}
      </div>
      {tabs && tabs.length > 1 && <Tabs items={tabs} />}
      {children}
    </section>
  )
}

const home = <Navigate to="/finanzen" replace />

export function FinanzenPage() {
  const org = useActiveOrg()
  const a = financeAccess(org)
  if (!a.finance && !a.billing) return <Navigate to="/" replace />
  return (
    <Routes>
      <Route
        index
        element={
          <Section title="Übersicht">
            <FinanceOverview access={a} />
          </Section>
        }
      />
      <Route
        path="entwicklung"
        element={
          a.finance ? (
            <Section title="Entwicklung">
              <FinanceDevelopment canEdit={a.financeEdit} />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="rechnungen/*"
        element={a.billing || a.received ? <InvoicesArea access={a} /> : home}
      />
      <Route path="lastschrift/*" element={a.sepa ? <DebitsArea access={a} /> : home} />
      <Route
        path="kassenbuch"
        element={
          a.finance ? (
            <Section title="Kassenbuch" readOnly={!a.financeEdit}>
              <BookingsPage />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="kontoauszuege"
        element={
          a.finance ? (
            <Section title="Kontoauszüge" readOnly={!a.financeEdit}>
              <BankStatementsPage canEdit={a.financeEdit} />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="quittungen/*"
        element={
          a.finance ? (
            <Section title="Quittungen" readOnly={!a.financeEdit}>
              <CashReceiptsArea canEdit={a.financeEdit} />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="kassenzaehlung"
        element={
          a.cashCounts ? (
            <Section title="Kassenzählung" readOnly={!a.financeEdit}>
              <CashCountsPage canEdit={a.financeEdit} />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="ruecklagen"
        element={
          a.reserves ? (
            <Section title="Rücklagen" readOnly={!a.financeEdit}>
              <ReservesPage canEdit={a.financeEdit} />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="zuwendungen/*"
        element={
          a.donations ? (
            <Section
              title="Zuwendungsbestätigungen"
              readOnly={!a.financeEdit}
              tabs={[
                { to: '/finanzen/zuwendungen', label: 'Zuwendungen' },
                { to: '/finanzen/zuwendungen/bestaetigungen', label: 'Bestätigungen' },
                { to: '/finanzen/zuwendungen/einstellungen', label: 'Einstellungen' },
              ]}
            >
              <DonationsArea canEdit={a.financeEdit} />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route
        path="veranstaltungen/*"
        element={
          a.finance ? (
            <Section
              title="Veranstaltungen"
              readOnly={!a.financeEdit}
              tabs={[
                { to: '/finanzen/veranstaltungen', label: 'Veranstaltungen' },
                { to: '/finanzen/veranstaltungen/reihen', label: 'Reihen' },
              ]}
            >
              <ProjectsArea />
            </Section>
          ) : (
            home
          )
        }
      />
      <Route path="abschluss/*" element={a.finance ? <ClosingArea access={a} /> : home} />
      <Route path="einstellungen/*" element={<SettingsArea access={a} />} />
      <Route path="*" element={home} />
    </Routes>
  )
}

function InvoicesArea({ access: a }: { access: FinanceAccess }) {
  const tabs = invoiceTabs(a)
  return (
    <Section title="Rechnungen" readOnly={a.billing && !a.billingEdit} tabs={tabs}>
      <Routes>
        <Route
          index
          element={a.billing ? <InvoicesPage /> : <Navigate to={tabs[0].to} replace />}
        />
        {a.feeRuns && <Route path="beitragslaeufe" element={<RunsPage />} />}
        {a.billing && <Route path="mahnungen" element={<DunningsPage />} />}
        {a.received && <Route path="dachverband" element={<ReceivedPage />} />}
        <Route path="*" element={<Navigate to={tabs[0].to} replace />} />
      </Routes>
    </Section>
  )
}

function DebitsArea({ access: a }: { access: FinanceAccess }) {
  return (
    <Section
      title="Lastschriften"
      readOnly={!a.billingEdit}
      tabs={[
        { to: '/finanzen/lastschrift', label: 'Lastschriftläufe' },
        { to: '/finanzen/lastschrift/mandate', label: 'SEPA-Mandate' },
      ]}
    >
      <Routes>
        <Route index element={<DebitsPage />} />
        <Route path="mandate" element={<MandatesPage />} />
        <Route path="*" element={<Navigate to="/finanzen/lastschrift" replace />} />
      </Routes>
    </Section>
  )
}

function ClosingArea({ access: a }: { access: FinanceAccess }) {
  return (
    <Section
      title="Abschluss & Berichte"
      readOnly={!a.financeEdit}
      tabs={[
        { to: '/finanzen/abschluss', label: 'Auswertung' },
        { to: '/finanzen/abschluss/jahresabschluss', label: 'Jahresabschluss' },
      ]}
    >
      <Routes>
        <Route index element={<EvaluationPage />} />
        <Route path="jahresabschluss" element={<ClosingsPage />} />
        <Route path="*" element={<Navigate to="/finanzen/abschluss" replace />} />
      </Routes>
    </Section>
  )
}

function SettingsArea({ access: a }: { access: FinanceAccess }) {
  const tabs = settingsTabs(a)
  const first = <Navigate to={tabs[0].to} replace />
  const readOnly = !a.billingEdit && !a.financeEdit
  return (
    <Section title="Einrichtung" readOnly={readOnly} tabs={tabs}>
      <Routes>
        <Route index element={first} />
        {a.feeRuns && <Route path="beitraege" element={<FeeRulesPage />} />}
        {a.billing && <Route path="mahnstufen" element={<DunningLevelsPage />} />}
        {a.billing && <Route path="rechnung" element={<BillingSettingsPage />} />}
        {a.finance && <Route path="konten" element={<AccountsPage />} />}
        {a.finance && <Route path="kategorien" element={<CategoriesPage />} />}
        <Route path="*" element={first} />
      </Routes>
    </Section>
  )
}
