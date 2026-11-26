import { useState } from "react";
import { api } from "../api.js";
import { BRAND_NAME } from "../config.js";
import Orb from "../Orb.jsx";

function Brand() {
  return (
    <a className="brand" href="#/">
      <span className="logo" aria-hidden="true">AI</span>
      <span className="brand-name">{BRAND_NAME}</span>
    </a>
  );
}

// mode: "login" | "register" | "admin-login". App remounts this component when the mode changes.
export default function Auth({ mode, onDone }) {
  const isAdmin = mode === "admin-login";
  const register = mode === "register";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = isAdmin
        ? await api.adminLogin(email.trim(), password)
        : register
        ? await api.register(name.trim(), email.trim(), password)
        : await api.login(email.trim(), password);
      onDone(res.access_token, res.user);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-split">
      <aside className="auth-aside">
        <Brand />
        <div className="auth-aside-body">
          <Orb />
          <h2>
            {isAdmin
              ? "Recruiter & Admin Intelligence Portal"
              : register
              ? "Your interviewer is ready when you are."
              : "Welcome back."}
          </h2>
        </div>
        <p className="muted small">
          {isAdmin
            ? "Inspect verified resumes, candidate skills, and AI evaluation transcripts."
            : "Aria asks, listens and follows up."}
        </p>
      </aside>

      <main className="auth-main">
        <form className="auth-form" onSubmit={submit}>
          <div className="auth-mobile-brand">
            <Brand />
          </div>
          <h1>
            {isAdmin
              ? "Recruiter Portal Sign In"
              : register
              ? "Create your account"
              : "Sign in"}
          </h1>
          <p className="muted">
            {isAdmin
              ? "Enter your administrator credentials to access candidate dossiers."
              : register
              ? "Add your details to start an interview."
              : "Enter your details to start or review an interview."}
          </p>

          {register && !isAdmin && (
            <label className="field">
              <span>Full name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={120}
                autoComplete="name"
                autoFocus
              />
            </label>
          )}
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              autoFocus={!register}
            />
          </label>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="pw">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={register ? 8 : 1}
                maxLength={128}
                autoComplete={register ? "new-password" : "current-password"}
              />
              <button
                type="button"
                className="pw-toggle"
                aria-pressed={showPassword}
                onClick={() => setShowPassword((v) => !v)}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            {register && <small className="muted">Use at least 8 characters.</small>}
          </div>

          {error && <p className="error" role="alert">{error}</p>}

          <button className="btn primary wide" disabled={busy}>
            {busy
              ? (isAdmin ? "Authenticating…" : register ? "Creating account…" : "Signing in…")
              : (isAdmin ? "Access Admin Dashboard" : register ? "Create account" : "Sign in")}
          </button>

          {isAdmin ? (
            <p className="auth-switch muted">
              Looking to take an interview?{" "}
              <a className="text-link" href="#/login">
                Candidate Sign In
              </a>
            </p>
          ) : (
            <>
              <p className="auth-switch muted">
                {register ? "Already have an account? " : "New here? "}
                <a className="text-link" href={register ? "#/login" : "#/register"}>
                  {register ? "Sign in" : "Create an account"}
                </a>
              </p>
              <p className="auth-switch muted small" style={{ marginTop: "4px" }}>
                Hiring manager or admin?{" "}
                <a className="text-link" href="#/admin-login">
                  Recruiter Portal
                </a>
              </p>
            </>
          )}
          <a className="auth-back muted" href="#/">Back to home</a>
        </form>
      </main>
    </div>
  );
}
