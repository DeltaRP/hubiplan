import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CalendarView } from '../components/calendar/CalendarView.tsx'
import {
  addDays,
  berlin,
  formatRange,
  monthGrid,
  monthStart,
  today,
} from '../components/calendar/time.ts'
import { occurrence } from './eventFixtures.ts'
import { fakeApi } from './fakeApi.ts'

const base = '/api/orgs/7/'
const day = (offset: number) => addDays(monthStart(today()), offset)

function listResponse(items: unknown[], canManage = true) {
  return {
    status: 200,
    body: {
      from: '',
      to: '',
      items,
      can_manage: canManage,
      categories: [{ id: 3, name: 'Versammlung', color: '#2f5f8f', is_active: true }],
    },
  }
}

function monthKey() {
  const grid = monthGrid(monthStart(today()))
  return `GET ${base}events/?from=${grid[0]}&to=${grid[grid.length - 1]}`
}

describe('Zeitrechnung', () => {
  it('rechnet in deutscher Zeit und zeigt Zeiträume lesbar', () => {
    expect(berlin('2026-03-29T00:30:00Z')).toEqual({ date: '2026-03-29', time: '01:30' })
    expect(berlin('2026-03-29T02:30:00Z')).toEqual({ date: '2026-03-29', time: '04:30' })
    expect(formatRange('2026-06-13T12:00:00Z', '2026-06-13T16:00:00Z', false)).toBe(
      'Sa 13.06.2026, 14:00 – 18:00 Uhr',
    )
    expect(formatRange('2026-08-28T22:00:00Z', '2026-08-31T22:00:00Z', true)).toBe(
      'Sa 29.08.2026 – Di 01.09.2026',
    )
    const grid = monthGrid('2026-06-01')
    expect(grid[0]).toBe('2026-06-01') // Montag
    expect(grid.length % 7).toBe(0)
  })
})

describe('Kalender', () => {
  it('zeigt Termine im Monat und öffnet die Details', async () => {
    fakeApi({
      [monthKey()]: () =>
        listResponse([
          occurrence(),
          occurrence({
            key: '2-x',
            event_id: 2,
            title: 'Schützenfest',
            all_day: true,
            visibility: 'public',
            owner: 'BSV',
            level: 'federation',
            can_edit: false,
            starts_at: `${day(12)}T00:00:00+01:00`,
            ends_at: `${day(14)}T00:00:00+01:00`,
          }),
        ]),
      [`GET ${base}events/1/`]: () => ({
        status: 200,
        body: {
          ...occurrence(),
          id: 1,
          description: 'Mit Neuwahlen.',
          visibility_label: 'Mitglieder',
          repeat: 'none',
          repeat_label: 'einmalig',
          repeat_interval: 1,
          repeat_until: null,
          cancel_note: '',
          attachments: [
            {
              id: 5,
              name: 'Einladung.pdf',
              size: 2048,
              content_type: 'application/pdf',
              url: '/x',
            },
          ],
          exceptions: [],
          rsvp: {
            enabled: false,
            deadline: null,
            capacity: null,
            guests_allowed: false,
            max_guests: 10,
          },
        },
      }),
    })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Jahreshauptversammlung')).toBeInTheDocument()
    // mehrtägig: an drei Tagen
    expect(screen.getAllByText('Schützenfest')).toHaveLength(3)
    await userEvent.setup().click(screen.getByText('Jahreshauptversammlung'))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Mit Neuwahlen.')).toBeInTheDocument()
    expect(within(dialog).getByText('Einladung.pdf')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Bearbeiten' })).toBeInTheDocument()
  })

  it('öffnet einen Termin über den Direktlink', async () => {
    fakeApi({
      [monthKey()]: () => listResponse([occurrence()]),
      [`GET ${base}events/1/`]: () => ({
        status: 200,
        body: {
          ...occurrence(),
          id: 1,
          description: 'Mit Neuwahlen.',
          visibility_label: 'Mitglieder',
          repeat: 'none',
          repeat_label: 'einmalig',
          repeat_interval: 1,
          repeat_until: null,
          cancel_note: '',
          attachments: [],
          exceptions: [],
          rsvp: {
            enabled: false,
            deadline: null,
            capacity: null,
            guests_allowed: false,
            max_guests: 10,
          },
        },
      }),
    })
    render(
      <MemoryRouter initialEntries={[`/termine?termin=1&datum=${today()}`]}>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Mit Neuwahlen.')).toBeInTheDocument()
  })

  it('legt für einen Termin eine Veranstaltungsabrechnung an', async () => {
    const detail = {
      ...occurrence(),
      id: 1,
      description: '',
      visibility_label: 'Mitglieder',
      repeat: 'none',
      repeat_label: 'einmalig',
      repeat_interval: 1,
      repeat_until: null,
      cancel_note: '',
      attachments: [],
      exceptions: [],
      rsvp: {
        enabled: false,
        deadline: null,
        capacity: null,
        guests_allowed: false,
        max_guests: 10,
      },
      project: null,
      can_link_project: true,
    }
    const calls = fakeApi({
      [monthKey()]: () => listResponse([occurrence()]),
      [`GET ${base}events/1/`]: () => ({ status: 200, body: detail }),
      [`POST ${base}events/1/project/`]: () => ({
        status: 200,
        body: { ...detail, project: { id: 4, name: 'Jahreshauptversammlung' } },
      }),
    })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByText('Jahreshauptversammlung'))
    const dialog = await screen.findByRole('dialog')
    await user.click(
      await within(dialog).findByRole('button', { name: 'Abrechnung für diesen Termin anlegen' }),
    )
    expect(
      await within(dialog).findByRole('link', { name: 'Jahreshauptversammlung' }),
    ).toHaveAttribute('href', '/finanzen/veranstaltungen/4')
    const post = calls.find((c) => c.key === `POST ${base}events/1/project/`)!
    expect(JSON.parse(String(post.init?.body))).toEqual({ create: true })
  })

  it('legt einen Termin an', async () => {
    const user = userEvent.setup()
    const calls = fakeApi({
      [monthKey()]: () => listResponse([]),
      [`POST ${base}events/`]: () => ({ status: 201, body: { id: 9 } }),
    })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    await user.click(await screen.findByRole('button', { name: 'Neuer Termin' }))
    const dialog = await screen.findByRole('dialog', { name: 'Neuer Termin' })
    await user.type(within(dialog).getByLabelText('Titel'), 'Königsschießen')
    await user.selectOptions(within(dialog).getByLabelText(/Wer sieht den Termin/), 'public')
    await user.click(within(dialog).getByRole('button', { name: 'Termin anlegen' }))
    const post = calls.find((c) => c.key === `POST ${base}events/`)
    const body = JSON.parse(String(post?.init?.body))
    expect(body.title).toBe('Königsschießen')
    expect(body.visibility).toBe('public')
    expect(body.starts_at).toMatch(/T19:00:00$/)
    expect(body.repeat).toBe('none')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('verwirft einen angefangenen Termin nicht per Esc und hält den Fokus im Dialog', async () => {
    const user = userEvent.setup()
    fakeApi({ [monthKey()]: () => listResponse([]) })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    const opener = await screen.findByRole('button', { name: 'Neuer Termin' })
    await user.click(opener)
    const dialog = await screen.findByRole('dialog', { name: 'Neuer Termin' })
    // Ohne Eingaben schließt Esc sofort, der Fokus kehrt zum Auslöser zurück
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    const again = await screen.findByRole('dialog', { name: 'Neuer Termin' })
    expect(again).not.toBe(dialog)
    await user.type(within(again).getByLabelText('Titel'), 'Königsschießen')
    await user.keyboard('{Escape}')
    const ask = await screen.findByRole('alertdialog', { name: 'Entwurf verwerfen?' })
    await user.click(within(ask).getByRole('button', { name: 'Weiter bearbeiten' }))
    expect(within(again).getByLabelText('Titel')).toHaveValue('Königsschießen')

    // Tab läuft im Dialog im Kreis
    within(again).getByRole('button', { name: 'Abbrechen' }).focus()
    await user.tab()
    expect(again.contains(document.activeElement)).toBe(true)
  })

  it('nur lesen: kein Anlegen, kein Bearbeiten', async () => {
    fakeApi({
      [monthKey()]: () => listResponse([occurrence({ can_edit: false })], false),
    })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Jahreshauptversammlung')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Neuer Termin' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Jahresprogramm/ })).toHaveAttribute(
      'href',
      `${base}events/program/?year=${today().slice(0, 4)}`,
    )
  })
})
