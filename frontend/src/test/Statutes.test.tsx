import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { StatutePanel } from '../components/StatutePanel.tsx'
import { fakeApi } from './fakeApi.ts'

const base = '/api/orgs/7/statutes/'
const version = (id: number, validFrom: string, current: boolean) => ({
  id,
  valid_from: validFrom,
  note: current ? 'Änderung § 4' : 'Neufassung',
  name: `Satzung-${validFrom}.pdf`,
  size: 2048,
  uploaded_at: '2026-10-24T10:00:00Z',
  uploaded_by: 'Hanna Hubertus',
  is_current: current,
  url: `${base}${id}/`,
})

const data = (isPublic: boolean, canManage = true) => ({
  versions: [version(2, '2019-11-08', true), version(1, '1998-04-20', false)],
  publication: {
    is_public: isPublic,
    pdf_url: isPublic ? 'https://example.test/api/public/statutes/abc/' : null,
    info_url: isPublic ? 'https://example.test/api/public/statutes/abc/info/' : null,
  },
  can_manage: canManage,
})

describe('Satzung', () => {
  it('zeigt Fassungen, die aktuelle zuerst, und schaltet den öffentlichen Link ein', async () => {
    const calls = fakeApi({
      [`GET ${base}`]: () => ({ status: 200, body: data(false) }),
      [`PUT ${base}publication/`]: () => ({ status: 200, body: data(true).publication }),
    })
    render(<StatutePanel orgId={7} />)
    expect(await screen.findByText('Fassung vom 08.11.2019')).toBeInTheDocument()
    expect(screen.getByText('Fassung vom 20.04.1998')).toBeInTheDocument()
    expect(screen.getAllByText(/aktuell/)).toHaveLength(1)
    expect(screen.queryByText('Link kopieren')).not.toBeInTheDocument()

    await userEvent.setup().click(screen.getByLabelText(/öffentlich abrufbar/))
    expect(await screen.findByText('https://example.test/api/public/statutes/abc/')).toBeVisible()
    const put = calls.find((c) => c.key === `PUT ${base}publication/`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({ is_public: true })
  })

  it('Abteilung und nur lesen: kein Upload, Abfrage mit Abteilung', async () => {
    fakeApi({
      [`GET ${base}?department=5`]: () => ({ status: 200, body: data(false, false) }),
    })
    render(<StatutePanel orgId={7} departmentId={5} />)
    expect(await screen.findByText('Fassung vom 08.11.2019')).toBeInTheDocument()
    expect(screen.queryByText('Neue Fassung hochladen')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Löschen' })).not.toBeInTheDocument()
    expect(screen.getByLabelText(/öffentlich abrufbar/)).toBeDisabled()
  })

  it('Beitragsordnung: eigene Abfrage, eigener Text, Art beim Freischalten', async () => {
    const calls = fakeApi({
      [`GET ${base}?department=5&kind=fee_rules`]: () => ({
        status: 200,
        body: { ...data(false), versions: [] },
      }),
      [`PUT ${base}publication/`]: () => ({ status: 200, body: data(true).publication }),
    })
    render(<StatutePanel orgId={7} departmentId={5} kind="fee_rules" />)
    expect(
      await screen.findByText('Keine Beitragsordnung hinterlegt (optional).'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Beitragsordnung' })).toBeInTheDocument()
    expect(screen.getByLabelText('Beitragsordnung als PDF')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByLabelText(/Beitragsordnung öffentlich abrufbar/))
    expect(await screen.findByText('https://example.test/api/public/statutes/abc/')).toBeVisible()
    const put = calls.find((c) => c.key === `PUT ${base}publication/`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({
      is_public: true,
      kind: 'fee_rules',
      department: 5,
    })
  })

  it('Gründungsurkunde: eigene Abfrage, eigene Texte, Art beim Freischalten', async () => {
    const calls = fakeApi({
      [`GET ${base}?kind=founding_deed`]: () => ({
        status: 200,
        body: { ...data(false), versions: [] },
      }),
      [`PUT ${base}publication/`]: () => ({ status: 200, body: data(true).publication }),
    })
    render(<StatutePanel orgId={7} kind="founding_deed" />)
    expect(
      await screen.findByText('Keine Gründungsurkunde hinterlegt (optional).'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Gründungsurkunde' })).toBeInTheDocument()
    expect(screen.getByLabelText('Gründungsurkunde als PDF')).toBeInTheDocument()
    expect(screen.getByLabelText(/ausgestellt am/)).toBeInTheDocument()

    await userEvent.setup().click(screen.getByLabelText(/Gründungsurkunde öffentlich abrufbar/))
    expect(await screen.findByText('https://example.test/api/public/statutes/abc/')).toBeVisible()
    const put = calls.find((c) => c.key === `PUT ${base}publication/`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({ is_public: true, kind: 'founding_deed' })
  })
})
