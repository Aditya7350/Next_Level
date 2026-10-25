const API = "/api/v1";
const state = {
  token: sessionStorage.getItem("fieldwork-token"),
  name: sessionStorage.getItem("fieldwork-name") || "",
  authMode: "login",
  interviewId: null,
  totalQuestions: 0,
  answered: 0,
  busy: false,
};

const byId = (id) => document.getElementById(id);
const authPanel = byId("auth-panel");
const setupPanel = byId("setup-panel");
const activePanel = byId("active-panel");
const reportSummary = byId("report-summary");
const toast = byId("toast");
let toastTimer;

function notify(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 5000);
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" && body ? body.detail : body;
    if (response.status === 401 && state.token) {
      clearDemoSession("Your demo session expired. If the API restarted, create your account again; otherwise sign in again.");
    }
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function sendFrame(id, blob) {
  const form = new FormData();
  form.append("file", blob, "frame.jpg");
  return request(`/interview/${id}/proctor/frame`, { method: "POST", body: form });
}

function sendProctorEvent(id, type) {
  return request(`/interview/${id}/proctor/event`, {
    method: "POST",
    body: JSON.stringify({ type }),
  });
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.dataset.originalLabel ||= button.textContent;
  button.innerHTML = busy ? `${label} <span aria-hidden="true">· · ·</span>` : button.dataset.originalLabel;
}

function updateSteps(active) {
  ["setup", "interview", "report"].forEach((step, index) => {
    const item = byId(`step-${step}`);
    item.classList.toggle("active", index === active);
    item.classList.toggle("done", index < active);
  });
  byId("room-progress").textContent = ["NOT STARTED", "IN PROGRESS", "COMPLETE"][active];
  byId("room-title").textContent = ["Your interview room", "Your interview room", "Your session report"][active];
}

function showSignedIn() {
  document.body.classList.remove("auth-mode");
  authPanel.hidden = true;
  setupPanel.hidden = false;
  activePanel.hidden = true;
  reportSummary.hidden = true;
  const button = byId("account-button");
  button.textContent = state.name || "Signed in";
  button.hidden = false;
}

function showAuth() {
  document.body.classList.add("auth-mode");
  authPanel.hidden = false;
  setupPanel.hidden = true;
  activePanel.hidden = true;
  reportSummary.hidden = true;
  byId("account-button").hidden = true;
  byId("conversation").hidden = true;
  byId("empty-room").hidden = false;
  byId("answer-input").value = "";
  updateSteps(0);
}

function clearDemoSession(message = "") {
  state.token = null;
  state.name = "";
  state.interviewId = null;
  sessionStorage.removeItem("fieldwork-token");
  sessionStorage.removeItem("fieldwork-name");
  showAuth();
  byId("auth-message").textContent = message;
}

async function restoreSession() {
  if (!state.token) {
    showAuth();
    return;
  }
  try {
    await request("/interview/history");
    showSignedIn();
  } catch (error) {
    if (state.token) {
      showAuth();
      byId("auth-message").textContent = error.status
        ? "Could not verify your session. Please try again."
        : "Could not reach the API to verify your session.";
    }
  }
}

async function checkHealth() {
  const dot = byId("health-dot");
  const label = byId("health-label");
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error("offline");
    dot.className = "status-dot online";
    label.textContent = "API connected";
  } catch {
    dot.className = "status-dot offline";
    label.textContent = "API unavailable";
  }
}

function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    const selected = tab.dataset.authMode === mode;
    tab.classList.toggle("selected", selected);
    tab.setAttribute("aria-selected", String(selected));
  });
  const registering = mode === "register";
  byId("auth-heading").innerHTML = registering ? "Create your<br>account." : "Welcome<br>back.";
  byId("auth-subtitle").textContent = registering
    ? "Set up your account to begin."
    : "Sign in to continue your practice.";
  byId("name-field").hidden = !registering;
  byId("name-input").required = registering;
  byId("password-input").autocomplete = registering ? "new-password" : "current-password";
  byId("auth-submit").innerHTML = `${registering ? "Create account" : "Sign in"} <span aria-hidden="true">↗</span>`;
  byId("auth-message").textContent = "";
  byId("auth-message").classList.remove("success");
}

document.querySelectorAll(".auth-tab").forEach((tab) => {
  tab.addEventListener("click", () => setAuthMode(tab.dataset.authMode));
});

byId("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = byId("auth-submit");
  const message = byId("auth-message");
  const registering = state.authMode === "register";
  const payload = {
    email: byId("email-input").value.trim(),
    password: byId("password-input").value,
  };
  if (registering) payload.name = byId("name-input").value.trim();
  setBusy(button, true, registering ? "Creating account" : "Signing in");
  message.textContent = "";
  try {
    const result = await request(`/auth/${registering ? "register" : "login"}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (registering) {
      byId("password-input").value = "";
      setAuthMode("login");
      button.dataset.originalLabel = button.textContent;
      message.classList.add("success");
      message.textContent = "Account created. Sign in with your email and password.";
      setBusy(button, false);
      return;
    }
    state.token = result.access_token;
    state.name = result.user.name;
    sessionStorage.setItem("fieldwork-token", state.token);
    sessionStorage.setItem("fieldwork-name", state.name);
    setBusy(button, false);
    showSignedIn();
  } catch (error) {
    message.textContent = error.message;
    setBusy(button, false);
  }
});

byId("resume-input").addEventListener("change", (event) => {
  const file = event.target.files[0];
  byId("file-name").textContent = file ? file.name : "PDF, DOCX, TXT or MD · 8 MB max";
});

byId("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = byId("start-button");
  const message = byId("setup-message");
  const role = byId("role-input").value.trim();
  const description = byId("jd-input").value.trim();
  const file = byId("resume-input").files[0];
  if (description && description.length < 30) {
    message.textContent = "Add at least 30 characters to analyze the job description, or leave it blank.";
    return;
  }
  if (file && file.size > 8 * 1024 * 1024) {
    message.textContent = "That file is larger than the 8 MB upload limit.";
    return;
  }
  setBusy(button, true, "Preparing your session");
  message.textContent = "";
  try {
    let resumeId = null;
    let jdId = null;
    if (file) {
      const formData = new FormData();
      formData.append("file", file);
      const resume = await request("/resume/upload", { method: "POST", body: formData });
      resumeId = resume.id;
    }
    if (description) {
      const jd = await request("/jd/analyze", {
        method: "POST",
        body: JSON.stringify({ title: role || "Practice interview", description }),
      });
      jdId = jd.id;
    }
    const interview = await request("/interview/create", {
      method: "POST",
      body: JSON.stringify({
        interview_type: role || "technical",
        difficulty: byId("difficulty-input").value,
        question_count: Number(byId("count-input").value),
        resume_id: resumeId,
        jd_id: jdId,
      }),
    });
    state.interviewId = interview.id;
    state.totalQuestions = interview.question_count;
    state.answered = 0;
    const started = await request(`/interview/${state.interviewId}/start`, { method: "POST" });
    byId("empty-room").hidden = true;
    byId("conversation").hidden = false;
    byId("answer-area").hidden = false;
    byId("feedback-panel").hidden = true;
    byId("report-panel").hidden = true;
    byId("answer-input").disabled = false;
    byId("answer-submit").hidden = false;
    byId("answer-input").value = "";
    renderQuestion(started.question);
    showSignedIn();
    setupPanel.hidden = true;
    activePanel.hidden = false;
    byId("active-role").textContent = role || "Practice interview";
    updateActiveProgress();
    updateSteps(1);
    byId("answer-input").focus();
  } catch (error) {
    message.textContent = error.message;
    setBusy(button, false);
  }
});

function renderQuestion(question) {
  if (!question) return;
  const questionNumber = state.answered + 1;
  byId("question-label").textContent = `QUESTION ${String(questionNumber).padStart(2, "0")}`;
  byId("question-meta").textContent = `${question.topic} · ${question.difficulty}`;
  byId("question-text").textContent = question.question;
  byId("room-progress").textContent = `${String(questionNumber).padStart(2, "0")} / ${String(state.totalQuestions).padStart(2, "0")}`;
  byId("char-count").textContent = "0 / 12,000";
  updateActiveProgress();
}

function updateActiveProgress() {
  const current = Math.min(state.answered + 1, state.totalQuestions);
  byId("active-count").textContent = `QUESTION ${String(current).padStart(2, "0")} OF ${String(state.totalQuestions).padStart(2, "0")}`;
  byId("active-progress").style.width = `${Math.round((state.answered / state.totalQuestions) * 100)}%`;
}

byId("answer-input").addEventListener("input", (event) => {
  byId("char-count").textContent = `${event.target.value.length.toLocaleString()} / 12,000`;
});

byId("answer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || !state.interviewId) return;
  const answer = byId("answer-input").value.trim();
  if (!answer) {
    byId("answer-input").focus();
    return;
  }
  state.busy = true;
  const button = byId("answer-submit");
  setBusy(button, true, "Sending answer");
  try {
    const result = await request(`/interview/${state.interviewId}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    });
    state.answered += 1;
    const echo = document.createElement("blockquote");
    echo.className = "response-echo";
    echo.textContent = answer;
    byId("question-block").append(echo);
    const evaluation = result.evaluation;
    const feedback = byId("feedback-panel");
    feedback.replaceChildren();
    const scoreLine = document.createElement("strong");
    scoreLine.textContent = `Demo score ${evaluation.score} / 5`;
    const detailLine = document.createElement("span");
    detailLine.textContent = ` — ${evaluation.feedback}`;
    feedback.append(scoreLine, detailLine);
    feedback.hidden = false;
    byId("answer-input").value = "";
    byId("answer-input").disabled = true;
    byId("answer-submit").hidden = true;
    setBusy(button, false);

    if (result.report) {
      renderReport(result.report);
    } else {
      const next = document.createElement("button");
      next.type = "button";
      next.className = "primary-button full-button next-question";
      next.innerHTML = 'Continue to next question <span aria-hidden="true">↗</span>';
      next.addEventListener("click", () => {
        next.remove();
        byId("feedback-panel").hidden = true;
        const oldEchoes = document.querySelectorAll(".response-echo");
        oldEchoes.forEach((item) => item.remove());
        renderQuestion(result.next_question);
        byId("answer-input").disabled = false;
        byId("answer-submit").hidden = false;
        byId("answer-input").focus();
      });
      feedback.append(next);
    }
  } catch (error) {
    notify(error.message);
    setBusy(button, false);
  } finally {
    state.busy = false;
  }
});

function addReportTags(container, items, emptyText) {
  if (!items.length) {
    const empty = document.createElement("span");
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  items.forEach((item) => {
    const tag = document.createElement("span");
    tag.textContent = item;
    container.append(tag);
  });
}

function renderReport(report) {
  const panel = byId("report-panel");
  panel.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "report-heading";
  const title = document.createElement("span");
  title.textContent = "OVERALL DEMO SCORE";
  const score = document.createElement("strong");
  score.textContent = `${report.score} / 5`;
  heading.append(title, score);
  panel.append(heading);
  [ ["Signals covered", report.strengths, "No concepts matched"], ["Areas to explore", report.improvement_areas, "No open concepts"] ].forEach(([label, items, empty]) => {
    const title = document.createElement("h3");
    title.textContent = label;
    const tags = document.createElement("div");
    tags.className = "report-tags";
    addReportTags(tags, items, empty);
    panel.append(title, tags);
  });
  const caveat = document.createElement("p");
  caveat.className = "report-caveat";
  caveat.textContent = "This score reflects simple keyword overlap in a local demo. It is not an assessment of candidate quality.";
  panel.append(caveat);
  byId("answer-area").hidden = true;
  byId("feedback-panel").hidden = true;
  panel.hidden = false;
  activePanel.hidden = true;
  reportSummary.hidden = false;
  setupPanel.hidden = true;
  updateSteps(2);
  byId("room-kicker").textContent = "SESSION COMPLETE";
  byId("room-progress").textContent = "COMPLETE";
  byId("room-title").textContent = "Your session report";
}

function resetSession() {
  state.interviewId = null;
  state.totalQuestions = 0;
  state.answered = 0;
  document.querySelectorAll(".response-echo").forEach((item) => item.remove());
  byId("conversation").hidden = true;
  byId("empty-room").hidden = false;
  byId("room-kicker").textContent = "LIVE SESSION";
  byId("answer-area").hidden = false;
  byId("feedback-panel").hidden = true;
  byId("report-panel").hidden = true;
  byId("answer-input").disabled = false;
  byId("answer-submit").hidden = false;
  byId("setup-message").textContent = "";
  setBusy(byId("start-button"), false);
  activePanel.hidden = true;
  setupPanel.hidden = false;
  reportSummary.hidden = true;
  updateSteps(0);
}

byId("new-session-button").addEventListener("click", resetSession);
byId("signout-button").addEventListener("click", signOut);
byId("signout-button-active").addEventListener("click", signOut);
byId("signout-button-report").addEventListener("click", signOut);
byId("account-button").addEventListener("click", signOut);

function signOut() {
  clearDemoSession();
  byId("auth-form").reset();
  byId("setup-form").reset();
  setAuthMode("login");
  showAuth();
}

checkHealth();
restoreSession();
