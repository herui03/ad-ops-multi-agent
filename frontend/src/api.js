// Thin client for the FastAPI backend. Same origin in production (FastAPI serves the built UI);
// Vite proxies /api and /ws to :8000 in development.

export const ROLES = {
  requester: { actor: 'alice', label: 'Requester (alice)' },
  approver: { actor: 'bob', label: 'Approver (bob)' },
  viewer: { actor: 'vera', label: 'Viewer (vera)' },
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.detail || `HTTP ${status}`);
    this.status = status;
    this.code = body?.error || 'http_error';
    this.body = body;
  }
}

async function request(path, { method = 'GET', body, role } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (role) {
    headers['X-Demo-Role'] = role;
    headers['X-Demo-Actor'] = ROLES[role].actor;
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new ApiError(0, { error: 'network_error', detail: 'Backend unreachable. Is the server running?' });
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text.slice(0, 200) }; }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  meta: () => request('/api/meta'),
  runs: () => request('/api/runs?limit=50'),
  run: (id) => request(`/api/runs/${encodeURIComponent(id)}`),
  createRun: (role, text, demoFault) =>
    request('/api/runs', { method: 'POST', role, body: demoFault ? { request: text, demo_fault: demoFault } : { request: text } }),
  decide: (role, runId, body) => request(`/api/runs/${encodeURIComponent(runId)}/decisions`, { method: 'POST', role, body }),
  cancel: (role, runId, key) => request(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST', role, body: { idempotency_key: key } }),
  recover: (role, runId) => request(`/api/runs/${encodeURIComponent(runId)}/recover`, { method: 'POST', role }),
  stats: () => request('/api/dashboard/stats'),
  sources: () => request('/api/sources'),
  source: (chunkId) => request(`/api/source?chunk_id=${encodeURIComponent(chunkId)}`),
};

export function newKey(prefix) {
  const rand = (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${rand}`;
}

export function runSocketUrl(runId) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}/ws/runs/${encodeURIComponent(runId)}`;
}
