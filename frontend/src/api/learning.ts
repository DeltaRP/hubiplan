// Lernhilfen am eigenen Konto: Schalter und ausgeblendete „Warum?“-Erklärungen.
import { api } from './client.ts'

export interface LearningData {
  learning_aids: boolean
  learning_hidden: string[]
}

export const learningApi = {
  get: () => api.get<LearningData>('/api/me/learning/'),
  update: (data: { learning_aids?: boolean; learning_hidden?: [] }) =>
    api.patch<LearningData>('/api/me/learning/', data),
  hide: (key: string) =>
    api.post<{ ok: boolean; learning_hidden: string[] }>(
      `/api/me/learning/${encodeURIComponent(key)}/hide/`,
      {},
    ),
  show: (key: string) =>
    api.post<{ ok: boolean; learning_hidden: string[] }>(
      `/api/me/learning/${encodeURIComponent(key)}/show/`,
      {},
    ),
}
