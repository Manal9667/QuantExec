// Thin fetch wrapper over the FastAPI backend (see backend/main.py).
// Every function here returns real backend data - the frontend never
// invents values (spec section 40, Rule 8).
//
// In dev (`npm run dev`), requests to /api are proxied to localhost:8000
// by vite.config.js. In the static Docker build there is no dev-server
// proxy, so VITE_API_BASE_URL is baked in at build time to point straight
// at the backend container's published port (see frontend/Dockerfile);
// the backend's permissive CORS config allows this.
const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore parse failure, fall back to statusText */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  listStrategies: () => request("/strategies"),
  listExperiments: () => request("/experiments"),
  getExperiment: (id) => request(`/experiments/${id}`),
  getFills: (id) => request(`/experiments/${id}/fills`),
  getMetrics: (id) => request(`/experiments/${id}/metrics`),
  createExperiment: (payload) =>
    request("/experiments", { method: "POST", body: JSON.stringify(payload) }),
};