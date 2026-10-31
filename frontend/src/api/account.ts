// Mein Konto: Name, Passwort und Anmelde-E-Mail.
import { api, request } from './client.ts'

export interface AccountData {
  email: string
  first_name: string
  last_name: string
  has_password: boolean
  pending_email: string | null
}

export const accountApi = {
  get: () => api.get<AccountData>('/api/me/account/'),
  updateName: (data: { first_name: string; last_name: string }) =>
    api.patch<AccountData>('/api/me/account/', data),
  changePassword: (data: { current_password?: string; new_password: string }) =>
    api.post<AccountData>('/api/me/password/', data),
  changeEmail: (data: { email: string; password?: string }) =>
    api.post<AccountData>('/api/me/email/', data),
  cancelEmail: () => api.del('/api/me/email/'),
}

export async function confirmEmail(
  token: string,
): Promise<{ ok: true; email: string } | { ok: false; message: string }> {
  const { status, body } = await request<{ email?: string; detail?: string }>(
    'POST',
    `/api/public/email-confirm/${token}/`,
  )
  if (status === 200 && body.email) return { ok: true, email: body.email }
  return { ok: false, message: body.detail ?? 'Der Link ist ungültig oder abgelaufen.' }
}
