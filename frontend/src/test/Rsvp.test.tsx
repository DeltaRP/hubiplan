import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CalendarView } from '../components/calendar/CalendarView.tsx'
import { addDays, addMonths, monthGrid, monthStart, today } from '../components/calendar/time.ts'
import { fakeApi } from './fakeApi.ts'
import { occurrence } from './eventFixtures.ts'

const day = (offset: number) => addDays(monthStart(today()), offset)

function monthKey(base: string) {
  const grid = monthGrid(monthStart(today()))
  return `GET ${base}events/?from=${grid[0]}&to=${grid[grid.length - 1]}`
}

// Listenansicht: zwölf Monate ab dem aktuellen Monat
function listKey(base: string) {
  const month = monthStart(today())
  return `GET ${base}events/?from=${month}&to=${addDays(addMonths(month, 12), -1)}`
}

function list(base: string, items: unknown[], extra: Record<string, unknown> = {}) {
  const answer = () => ({
    status: 200,
    body: { from: '', to: '', items, can_manage: false, categories: [], ...extra },
  })
  return { [monthKey(base)]: answer, [listKey(base)]: answer }
}

function detail(rsvp: Record<string, unknown>, over: Record<string, unknown> = {}) {
  return {
    ...occurrence({ rsvp_enabled: true }),
    id: 1,
    title: 'Königsschießen',
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
      enabled: true,
      deadline: `${day(8)}T23:59:00+01:00`,
      capacity: null,
      guests_allowed: true,
      max_guests: 10,
      ...rsvp,
    },
    ...over,
  }
}

describe('Zu- und Absagen', () => {
  it('Mitglied sagt mit Begleitung zu', async () => {
    const base = '/api/portal/4/'
    const user = userEvent.setup()
    const mine = { status: 'yes', guests: 2, note: '', source: 'member', updated_at: '' }
    const calls = fakeApi({
      ...list(base, [
        occurrence({
          title: 'Königsschießen',
          can_edit: false,
          rsvp_enabled: true,
          my_response: null,
        }),
      ]),
      [`GET ${base}events/1/`]: () => ({
        status: 200,
        body: detail({ mine: null, can_respond: true, reason: '' }, { can_edit: false }),
      }),
      [`PUT ${base}events/1/response/`]: () => ({
        status: 200,
        body: detail({ mine, can_respond: true, reason: '' }, { can_edit: false }),
      }),
    })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    await user.click(await screen.findByRole('button', { name: 'Liste' }))
    expect(await screen.findByText('Rückmeldung offen')).toBeInTheDocument()
    await user.click(screen.getByText('Königsschießen'))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/Anmeldeschluss/)).toBeInTheDocument()
    const guests = within(dialog).getByLabelText('Begleitpersonen')
    await user.clear(guests)
    await user.type(guests, '2')
    await user.click(within(dialog).getByRole('button', { name: 'Zusagen' }))
    const put = calls.find((c) => c.key === `PUT ${base}events/1/response/`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({ status: 'yes', guests: 2, note: '' })
    expect(
      await within(dialog).findByText('mit 2 Begleitpersonen', { exact: false }),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Rückmeldung zurücknehmen' }),
    ).toBeInTheDocument()
  })

  it('Vorstand sieht die Liste und trägt eine Zusage ein', async () => {
    const base = '/api/orgs/7/'
    const user = userEvent.setup()
    let entered = false
    const responses = () => ({
      status: 200,
      body: {
        event_id: 1,
        scope: 'all',
        summary: {
          yes: entered ? 2 : 1,
          no: 0,
          guests: 1,
          persons: entered ? 3 : 2,
          open: entered ? 0 : 1,
        },
        capacity: 50,
        items: [
          {
            membership_id: 11,
            name: 'Muster, Erika',
            club_number: '1',
            departments: 'Jägerzug',
            status: 'yes',
            guests: 1,
            note: 'mit Partner',
            source: 'member',
            updated_at: '',
          },
        ],
        open: entered ? [] : [{ membership_id: 12, name: 'Ohnemail, Otto', departments: '' }],
      },
    })
    const calls = fakeApi({
      ...list(base, [occurrence({ title: 'Königsschießen', rsvp_enabled: true })], {
        can_manage: true,
      }),
      [`GET ${base}events/1/`]: () => ({
        status: 200,
        body: detail({
          can_view_list: true,
          can_enter: true,
          summary: { yes: 1, no: 0, guests: 1, persons: 2 },
        }),
      }),
      [`GET ${base}events/1/responses/`]: responses,
      [`PUT ${base}events/1/responses/`]: () => {
        entered = true
        return { status: 200, body: {} }
      },
    })
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    await user.click(await screen.findByText('Königsschießen'))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Muster, Erika')).toBeInTheDocument()
    expect(
      within(dialog).getByText(/1 Zusagen \+ 1 Begleitpersonen = 2 Personen/),
    ).toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: 'Excel' })).toHaveAttribute(
      'href',
      `${base}events/1/responses/export/?type=xlsx`,
    )
    await user.click(within(dialog).getByText(/Noch keine Rückmeldung/))
    await user.click(
      within(dialog).getByRole('button', { name: 'Zusage für Ohnemail, Otto eintragen' }),
    )
    const put = calls.find((c) => c.key === `PUT ${base}events/1/responses/`)
    expect(JSON.parse(String(put?.init?.body))).toMatchObject({ membership_id: 12, status: 'yes' })
    expect(await within(dialog).findByText(/2 Zusagen/)).toBeInTheDocument()
  })

  it('Formular schaltet Zu- und Absagen und die Einladung ein', async () => {
    const base = '/api/orgs/7/'
    const user = userEvent.setup()
    const calls = fakeApi({
      ...list(base, [], { can_manage: true, rsvp_allowed: true }),
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
    await user.click(within(dialog).getByLabelText('Mitglieder können zu- oder absagen'))
    await user.type(within(dialog).getByLabelText('Höchstzahl Personen (optional)'), '80')
    await user.click(within(dialog).getByLabelText('Begleitpersonen erlaubt'))
    await user.click(within(dialog).getByLabelText('Erinnerung per E-Mail'))
    await user.click(within(dialog).getByLabelText(/Einladung per E-Mail/))
    await user.click(within(dialog).getByRole('button', { name: 'Termin anlegen' }))
    const post = calls.find((c) => c.key === `POST ${base}events/`)
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({
      rsvp_enabled: true,
      rsvp_capacity: 80,
      rsvp_guests: true,
      remind_days: 2,
      notify: true,
    })
  })

  it('ohne Recht auf Rückmeldungen (Dachverband) keine Felder', async () => {
    const base = '/api/orgs/1/'
    const user = userEvent.setup()
    fakeApi(list(base, [], { can_manage: true, rsvp_allowed: false }))
    render(
      <MemoryRouter>
        <CalendarView base={base} />
      </MemoryRouter>,
    )
    await user.click(await screen.findByRole('button', { name: 'Neuer Termin' }))
    const dialog = await screen.findByRole('dialog', { name: 'Neuer Termin' })
    expect(within(dialog).queryByText('Zu- und Absagen')).not.toBeInTheDocument()
  })
})
