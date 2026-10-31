// Barrierefreiheit 30.10.2026 (Bericht audit/barrierefreiheit-3010.md): H-01 bis H-13, X-01.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { addTableRoles } from '../components/tableSemantics.ts'
import { Field, SelectField } from '../components/ui.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { contrastRatio, readableOn } from '../theme/contrast.ts'
import { applyTheme, PAGE_BG } from '../theme/theme.ts'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

async function axeViolations() {
  // Kontrast prüft axe in jsdom nicht (keine Darstellung); dafür gibt es die Farbtests unten
  const result = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)
}

describe('H-01 Fokusfarbe bei hellen Vereinsfarben', () => {
  it.each(['#ffd700', '#e0a526', '#7fb3d5', '#4caf50', '#00a0e0', '#1f6f5c'])(
    '%s: Fokusrahmen mit mindestens 3 : 1, Links mit 4,5 : 1',
    (primary) => {
      const root = document.createElement('div')
      applyTheme(
        { primary, on_primary: readableOn(primary), accent: '#e0a526', on_accent: '#1d2421' },
        root,
      )
      const focus = root.style.getPropertyValue('--color-focus')
      const link = root.style.getPropertyValue('--color-link')
      for (const bg of ['#ffffff', PAGE_BG]) {
        expect(contrastRatio(focus, bg)).toBeGreaterThanOrEqual(3)
        expect(contrastRatio(link, bg)).toBeGreaterThanOrEqual(4.5)
      }
    },
  )

  it('ohne Theme fällt die Fokusfarbe auf den Standard zurück', () => {
    const root = document.createElement('div')
    root.style.setProperty('--color-focus', '#123456')
    applyTheme(null, root)
    expect(root.style.getPropertyValue('--color-focus')).toBe('')
  })
})

describe('H-02 Hinweise und Fehler am Feld', () => {
  it('verbindet Fehler per aria-describedby, der Feldname bleibt kurz', () => {
    render(
      <>
        <Field label="Eintrittsdatum" error="Bitte ein Datum eingeben." />
        <SelectField label="Mitgliedsart" hint="steuert den Beitrag">
          <option>aktiv</option>
        </SelectField>
      </>,
    )
    const input = screen.getByRole('textbox', { name: 'Eintrittsdatum' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Bitte ein Datum eingeben.')
    const select = screen.getByRole('combobox', { name: 'Mitgliedsart' })
    expect(select).toHaveAccessibleDescription('steuert den Beitrag')
    expect(select).toHaveAttribute('aria-invalid', 'false')
  })

  it('übernimmt eine eigene ID und eine zusätzliche Beschreibung', () => {
    render(
      <>
        <p id="extra">Format TT.MM.JJJJ</p>
        <Field label="Datum" id="datum" aria-describedby="extra" hint="optional" />
      </>,
    )
    const input = screen.getByLabelText('Datum')
    expect(input.id).toBe('datum')
    expect(input).toHaveAccessibleDescription('Format TT.MM.JJJJ optional')
  })
})

describe('H-05 Tabellenrollen', () => {
  it('setzt Rollen ausdrücklich, damit sie auf dem Handy erhalten bleiben', () => {
    const { container } = render(
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Zug</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Anna</th>
            <td>Adler</td>
          </tr>
        </tbody>
      </table>,
    )
    const table = container.querySelector('table')!
    addTableRoles(table)
    expect(table).toHaveAttribute('role', 'table')
    expect(container.querySelector('thead')).toHaveAttribute('role', 'rowgroup')
    expect(container.querySelectorAll('[role="row"]')).toHaveLength(2)
    expect(container.querySelectorAll('[role="columnheader"]')).toHaveLength(2)
    expect(container.querySelector('tbody th')).toHaveAttribute('role', 'rowheader')
    expect(container.querySelector('td')).toHaveAttribute('role', 'cell')
  })
})

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('H-03 Seitenwechsel', () => {
  it('setzt den Fokus nach dem Wechsel auf die Überschrift der neuen Seite', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp('/einstellungen/xyz')
    const user = userEvent.setup()
    await screen.findByRole('heading', { level: 1 })
    const glossar = screen.getByRole('link', { name: /Hilfe & Glossar/ })
    await user.click(glossar)
    await waitFor(() => expect(document.activeElement?.tagName).toBe('H1'))
    expect(document.activeElement).toHaveAttribute('tabindex', '-1')
  })
})

describe('X-01 keine Verstöße laut axe', () => {
  it('Anmeldeseite', async () => {
    fakeApi({ [SESSION]: () => ({ status: 401, body: { status: 401, data: { flows: [] } } }) })
    renderApp('/anmelden')
    await screen.findByRole('heading', { level: 1 })
    expect(await axeViolations()).toEqual([])
  })

  it('Erklärung zur Barrierefreiheit (X-02)', async () => {
    fakeApi({ [SESSION]: () => ({ status: 401, body: { status: 401, data: { flows: [] } } }) })
    renderApp('/barrierefreiheit')
    expect(await screen.findByRole('heading', { level: 1, name: 'Barrierefreiheit' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Barrierefreiheit' })).toHaveAttribute(
      'href',
      '/barrierefreiheit',
    )
    expect(await axeViolations()).toEqual([])
  })

  it('Seite nicht gefunden mit Navigation', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp('/einstellungen/xyz')
    await screen.findByRole('heading', { level: 1 })
    expect(await axeViolations()).toEqual([])
  })

  it('Glossar', async () => {
    fakeApi({
      [SESSION]: loggedIn,
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp('/glossar')
    await screen.findByRole('heading', { level: 1 })
    expect(await axeViolations()).toEqual([])
  })
})
