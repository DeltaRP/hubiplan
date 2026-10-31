// Android-App: Geräte verbinden (QR-Code) und angemeldete Geräte verwalten.
import { api } from './client.ts'

export interface AppDevice {
  id: number
  name: string
  platform: 'android' | 'ios' | 'other'
  app_version: string
  push: string
  created_at: string
  last_seen_at: string
  current: boolean
  // Verwaltung in der App freigeschaltet bis (Vorstandszugang), sonst null
  admin_until?: string | null
}

export interface PairingCode {
  id: number
  url: string
  expires_at: string
}

export interface PairingStatus {
  used: boolean
  device: string | null
  expires_at: string
}

export const devicesApi = {
  list: () => api.get<AppDevice[]>('/api/app/v1/devices/'),
  remove: (id: number) => api.del(`/api/app/v1/devices/${id}/`),
  lockAdmin: (id: number) => api.del(`/api/app/v1/devices/${id}/admin/`),
  pairingCode: () => api.post<PairingCode>('/api/app/v1/pairing/'),
  pairingStatus: (id: number) => api.get<PairingStatus>(`/api/app/v1/pairing/${id}/`),
  hasPortal: () =>
    api.get<{ portal: unknown[] }>('/api/me/contexts/').then((c) => c.portal.length > 0),
}
