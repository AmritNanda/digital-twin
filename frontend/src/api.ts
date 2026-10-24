import type { CaseRecord, User } from './types';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...options });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : message;
    } catch { /* Keep HTTP status. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const api = {
  me: () => request<User>('/auth/me'),
  login: (email: string, password: string) => request<User>('/auth/login', json({ email, password })),
  logout: () => request('/auth/logout', { method: 'POST' }),
  createCase: () => request<CaseRecord>('/cases', { method: 'POST' }),
  case: (id: string) => request<CaseRecord>(`/cases/${id}`),
  upload: async (id: string, file: File) => {
    const body = new FormData(); body.append('file', file);
    return request(`/cases/${id}/documents`, { method: 'POST', body });
  },
  removeDocument: (id: string, docId: string) => request(`/cases/${id}/documents/${docId}`, { method: 'DELETE' }),
  correctSource: (id: string, entity_id: string, field: string, value: string, reason: string) =>
    request<CaseRecord>(`/cases/${id}/source/corrections`, json({ entity_id, field, value, reason })),
  start: (id: string, question: string) => request<CaseRecord>(`/cases/${id}/start`, json({ question })),
  approve: (id: string, values: Record<string, number>) => request<CaseRecord>(`/cases/${id}/approve`, json({ approved: true, values })),
  message: (id: string, content: string, run_id?: string) => request<{ type: string; content: string; overrides?: Record<string, number>; base_run_id?: string }>(`/cases/${id}/messages`, json({ content, run_id })),
  scenario: (id: string, base_run_id: string, overrides: Record<string, number>) => request(`/cases/${id}/runs`, json({ base_run_id, overrides })),
};
