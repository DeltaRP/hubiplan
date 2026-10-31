// Zustellung eines Rundschreibens: App statt Mail, App und Mail oder nur Mail.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DeliveryField } from '../components/circulars/DeliveryField.tsx'

function Harness({
  onChange,
}: {
  onChange: (c: { via_app: boolean; also_mail: boolean }) => void
}) {
  const [v, setV] = useState({ via_app: true, also_mail: false })
  return (
    <DeliveryField
      viaApp={v.via_app}
      alsoMail={v.also_mail}
      onChange={(c) => {
        setV(c)
        onChange(c)
      }}
    />
  )
}

describe('Zustellung', () => {
  it('bildet die drei Wege auf via_app und also_mail ab', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    const select = screen.getByLabelText('Zustellung')
    expect(select).toHaveValue('app')
    await user.selectOptions(select, 'both')
    expect(onChange).toHaveBeenLastCalledWith({ via_app: true, also_mail: true })
    expect(screen.getByText(/zusätzlich per E-Mail, alle anderen/)).toBeInTheDocument()
    await user.selectOptions(select, 'mail')
    expect(onChange).toHaveBeenLastCalledWith({ via_app: false, also_mail: false })
  })
})
