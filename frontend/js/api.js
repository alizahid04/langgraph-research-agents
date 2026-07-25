/** Thin client for the Research & Decision Intelligence Platform API. */
const API = (function () {
  const BASE = '/api';

  async function request(path, options = {}) {
    const resp = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      throw new Error(`API error ${resp.status}: ${text}`);
    }
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('application/json')) return resp.json();
    return resp.text();
  }

  return {
    health: () => request('/health'),
    stats: () => request('/workflows/stats'),
    listWorkflows: () => request('/workflows'),
    getWorkflow: (id) => request(`/workflows/${id}`),
    createWorkflow: (objective) =>
      request('/workflows', { method: 'POST', body: JSON.stringify({ objective }) }),
    submitClarification: (id, answer) =>
      request(`/workflows/${id}/clarify`, { method: 'POST', body: JSON.stringify({ answer }) }),
    reportDownloadUrl: (id) => `${BASE}/workflows/${id}/report/download`,
  };
})();
