import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RoleTable } from '../components/RoleEditor.tsx'
import { permissionAreas } from '../components/roles.ts'

const catalog = [
  {
    id: 'members',
    label: 'Mitglieder',
    permissions: [
      { code: 'members.view', label: 'Mitglieder lesen' },
      { code: 'members.edit', label: 'Mitglieder bearbeiten' },
    ],
  },
  {
    id: 'events',
    label: 'Termine',
    permissions: [{ code: 'events.manage', label: 'Termine verwalten' }],
  },
  { id: 'finance', label: 'Kasse', permissions: [{ code: 'finance.view', label: 'Kasse lesen' }] },
]

describe('Rechte in der Rollenliste', () => {
  it('fasst Rechte nach Bereichen zusammen', () => {
    expect(permissionAreas(['members.view', 'events.manage'], catalog)).toEqual([
      { label: 'Mitglieder', full: false, permissions: ['Mitglieder lesen'] },
      { label: 'Termine', full: true, permissions: ['Termine verwalten'] },
    ])
  })

  it('zeigt Bereiche als Kennzeichen, Einzelrechte aufklappbar', () => {
    render(
      <RoleTable
        roles={[
          {
            id: 1,
            name: 'Schriftführer',
            permissions: ['members.view', 'events.manage'],
            holders: 1,
          },
        ]}
        catalog={catalog}
      />,
    )
    const areas = screen.getByRole('list', { name: 'Bereiche' })
    expect(
      within(areas)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['Mitglieder (teilweise)', 'Termine'])
    expect(screen.getByText('Einzelne Rechte')).toBeInTheDocument()
    expect(screen.queryByText('Kasse')).not.toBeInTheDocument()
  })
})
