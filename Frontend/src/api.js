// VITE_API_URL may be a Render service URL or a full API URL ending in /api/v1.
const configuredBase = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const API_PREFIX = "/api/v1";
const BASE = configuredBase
  ? configuredBase.endsWith(API_PREFIX)
    ? configuredBase
    : `${configuredBase}${API_PREFIX}`
  : API_PREFIX;

const store = {
  get(k) {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* storage unavailable: session lasts until reload */
    }
  },
  del(k) {
    try {
      localStorage.removeItem(k);
    } catch {
      /* ignore */
    }
  },
};

let memoryToken = null;

export const session = {
  token: () => memoryToken || store.get("token"),
  user() {
    try {
      return JSON.parse(store.get("user") || "null");
    } catch {
      return null;
    }
  },
  save(token, user) {
    memoryToken = token;
    store.set("token", token);
    store.set("user", JSON.stringify(user));
  },
  clear() {
    memoryToken = null;
    store.del("token");
    store.del("user");
  },
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

function detailText(data) {
  const d = data && data.detail;
  if (!d) return "";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => e.msg).filter(Boolean).join(". ");
  return "";
}

async function request(path, { method = "GET", json, form } = {}) {
  const headers = {};
  const token = session.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form; // the browser sets the multipart boundary
  }

  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body });
  } catch {
    throw new ApiError("Can't reach the server. Is the backend running?", 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized();
    throw new ApiError(detailText(data) || `Request failed (${res.status})`, res.status);
  }
  return data;
}

export const api = {
  register: (name, email, password) => request("/auth/register", { method: "POST", json: { name, email, password } }),
  login: (email, password) => request("/auth/login", { method: "POST", json: { email, password } }),
  adminLogin: (email, password) => request("/auth/admin/login", { method: "POST", json: { email, password } }),

  submitIntro: (id, answer, greeting) =>
    request(`/interview/${id}/intro`, { method: "POST", json: { answer, greeting } }),
  uploadResume(file) {
    const form = new FormData();
    form.append("file", file);
    return request("/resume/upload", { method: "POST", form });
  },
  analyzeJd: (title, description) => request("/jd/analyze", { method: "POST", json: { title, description } }),

  createInterview: (payload) => request("/interview/create", { method: "POST", json: payload }),
  startInterview: (id) => request(`/interview/${id}/start`, { method: "POST" }),
  getQuestion: (id) => request(`/interview/${id}/question`),
  submitAnswer: (id, answer) => request(`/interview/${id}/answer`, { method: "POST", json: { answer } }),
  finishInterview: (id) => request(`/interview/${id}/finish`, { method: "POST" }),
  getReport: (id) => request(`/interview/${id}/report`),

  // Proctoring (needs app/api/v1/proctoring.py on the backend)
  setProctorBaseline(id, blob) {
    const form = new FormData();
    form.append("file", blob, "baseline.jpg");
    return request(`/interview/${id}/proctor/baseline`, { method: "POST", form });
  },
  sendFrame(id, blob) {
    const form = new FormData();
    form.append("file", blob, "frame.jpg");
    return request(`/interview/${id}/proctor/frame`, { method: "POST", form });
  },
  sendProctorEvent: (id, type) => request(`/interview/${id}/proctor/event`, { method: "POST", json: { type } }),

  // Admin Dashboard endpoints
  getAdminStats: () => request("/admin/stats"),
  listCandidates: (q = "") => request(`/admin/candidates?q=${encodeURIComponent(q)}`),
  getCandidateDossier: (userId) => request(`/admin/candidate/${userId}`),
};