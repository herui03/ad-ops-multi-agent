// Backend base URL. Set VITE_API_URL in frontend/.env for a deployed backend;
// defaults to the local FastAPI dev server.
const BACKEND = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_BASE = `${BACKEND}/api`;
const WS_BASE = import.meta.env.VITE_WS_URL || BACKEND;

export async function sendMessage(sessionId, message) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  return res.json();
}

export async function getHistory(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/history`);
  return res.json();
}

export async function getApprovals(sessionId) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/approvals`);
  return res.json();
}

export async function submitApproval(approvalId, decision, feedback = '') {
  const res = await fetch(`${API_BASE}/approvals/${approvalId}/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approval_id: approvalId, decision, feedback }),
  });
  return res.json();
}

export async function getDashboardStats() {
  const res = await fetch(`${API_BASE}/dashboard/stats`);
  return res.json();
}

export function createWebSocket(sessionId, onMessage) {
  const wsScheme = WS_BASE.startsWith('https') ? 'wss' : 'ws';
  const wsUrl = `${wsScheme}://${WS_BASE.replace(/^https?:\/\//, '')}/ws/${sessionId}`;
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onerror = (err) => console.error('WebSocket error:', err);
  return ws;
}