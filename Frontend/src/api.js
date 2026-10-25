// API client for the FastAPI backend. Base URL: VITE_API_URL, default "/api/v1" (proxied by Vite in dev).
const BASE = (import.meta.env.VITE_API_URL || "/api/v1").replace(/\/$/, "");

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
  getReport: (id) => request(`/interview/${id}/report`),

  // Proctoring (needs app/api/v1/proctoring.py on the backend)
  sendFrame(id, blob) {
    const form = new FormData();
    form.append("file", blob, "frame.jpg");
    return request(`/interview/${id}/proctor/frame`, { method: "POST", form });
  },
  sendProctorEvent: (id, type) => request(`/interview/${id}/proctor/event`, { method: "POST", json: { type } }),
};