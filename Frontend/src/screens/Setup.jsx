import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useDevices } from "../devices.js";
import {
  BRAND_NAME, DEFAULT_ADAPTIVE, DEFAULT_DIFFICULTY, INTERVIEW_QUESTION_COUNT, PROCTORING_CONSENT_TEXT,
  PROCTORING_ENABLED, PROCTORING_PRIVACY_NOTE, REQUIRE_FULLSCREEN, TRANSCRIPT_NOTICE,
} from "../config.js";
import { enterFullscreen } from "../fullscreen.js";
import { speechInputSupported } from "../speech.js";

const MAX_RESUME_BYTES = 8 * 1024 * 1024;
const RESUME_TYPES = /\.(pdf|docx|txt|md)$/i;

function Status({ ok, pending, children }) {
  const tone = pending ? "pending" : ok ? "ok" : "bad";
  return (
    <li className={`check ${tone}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </li>
  );
}

function DeviceCheck() {
  const { stream, camera, mic, level } = useDevices({ audio: true });
  const videoRef = useRef(null);

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream && camera === "ok" ? stream : null;
  }, [stream, camera]);

  return (
    <section className="card">
      <h2>Check your camera and microphone</h2>
      <div className="preview">
        {camera === "ok" ? (
          <video ref={videoRef} autoPlay muted playsInline aria-label="Your camera preview" />
        ) : (
          <div className="preview-empty">
            <span>{camera === "pending" ? "Waiting for camera permission…" : "Camera not available"}</span>
          </div>
        )}
      </div>
      <div className="meter" aria-hidden="true">
        <div className="meter-fill" style={{ width: `${Math.round(level * 100)}%` }} />
      </div>
      <ul className="checks">
        <Status pending={camera === "pending"} ok={camera === "ok"}>
          {camera === "ok" ? "Camera is working" : camera === "pending" ? "Checking camera…" : "Camera blocked. Allow it in your browser, or continue without it."}
        </Status>
        <Status pending={mic === "pending"} ok={mic === "ok"}>
          {mic === "ok" ? "Microphone is working. Say something to see the bar move." : mic === "pending" ? "Checking microphone…" : "Microphone blocked. You can type your answers instead."}
        </Status>
        <Status ok={speechInputSupported}>
          {speechInputSupported ? "Voice answers are supported in this browser" : "Voice answers aren't supported here. Use Chrome or Edge, or type your answers."}
        </Status>
      </ul>
      <p className="muted small">
        {PROCTORING_ENABLED ? PROCTORING_PRIVACY_NOTE : "Your video stays on your device. Nothing is recorded."}
      </p>
    </section>
  );
}

function Progress({ stage }) {
  const steps = [
    { key: "read", label: "Reading your resume" },
    { key: "plan", label: "Preparing your interview questions" },
  ];
  const at = steps.findIndex((s) => s.key === stage);
  return (
    <ol className="prep-steps" aria-live="polite">
      {steps.map((s, i) => (
        <li key={s.key} className={i < at ? "done" : i === at ? "now" : ""}>
          <span className="prep-mark" aria-hidden="true">{i < at ? "✓" : ""}</span>
          {s.label}
        </li>
      ))}
    </ol>
  );
}

export default function Setup({ user, onReady, onLogout }) {
  // upload -> preparing -> check
  const [step, setStep] = useState("upload");
  const [stage, setStage] = useState("read");
  const [resume, setResume] = useState(null);
  const [created, setCreated] = useState(null);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const resumeIdRef = useRef(null); // keeps the upload if only the next step failed
  const lastFile = useRef(null);
  const [dragging, setDragging] = useState(false);

  function pick(file) {
    setError("");
    if (!file) return;
    if (!RESUME_TYPES.test(file.name)) return setError("Please choose a PDF, DOCX, TXT or MD file.");
    if (file.size > MAX_RESUME_BYTES) return setError("That file is over 8 MB. Please choose a smaller one.");
    setResume(file);
  }

  async function prepare(e) {
    e.preventDefault();
    if (!resume) return setError("Upload your resume to continue.");
    setError("");
    setStep("preparing");
    try {
      if (!resumeIdRef.current || lastFile.current !== resume) {
        setStage("read");
        resumeIdRef.current = (await api.uploadResume(resume)).id;
        lastFile.current = resume;
      }
      setStage("plan");
      const interview = await api.createInterview({
        interview_type: "technical",
        resume_id: resumeIdRef.current,
        jd_id: null,
        difficulty: DEFAULT_DIFFICULTY,
        question_count: INTERVIEW_QUESTION_COUNT,
        adaptive: DEFAULT_ADAPTIVE,
      });
      setCreated(interview);
      setStep("check");
    } catch (err) {
      setError(err.message);
      setStep("upload");
    }
  }

  async function begin() {
    setStarting(true);
    if (REQUIRE_FULLSCREEN) await enterFullscreen(); // must run inside this click
    onReady({ ...created, role_title: "Interview" });
  }

  const firstName = String(user?.name || "").trim().split(/\s+/)[0];

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">AI</span>
          <span className="brand-name">{BRAND_NAME}</span>
        </div>
        <div className="topbar-right">
          <span className="muted">{user?.name}</span>
          <button className="btn ghost" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <main className={`setup single ${step === "check" ? "wide" : ""}`}>
        <ol className="flow" aria-label="Progress">
          <li className={step === "upload" ? "now" : "done"}>1 · Resume</li>
          <li className={step === "preparing" ? "now" : step === "check" ? "done" : ""}>2 · Preparing</li>
          <li className={step === "check" ? "now" : ""}>3 · Check and start</li>
        </ol>

        {step === "upload" && (
          <form className="card" onSubmit={prepare}>
            <h1>{firstName ? `Welcome, ${firstName}` : "Welcome"}</h1>
            <p className="muted">Upload your resume or CV. Aria will read it and interview you on your own experience.</p>

            <label
              className={`dropzone ${dragging ? "drag" : ""} ${resume ? "has-file" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}
            >
              <input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => pick(e.target.files?.[0])} />
              {resume ? (
                <>
                  <strong>{resume.name}</strong>
                  <span className="muted small">{(resume.size / 1024).toFixed(0)} KB · click to choose a different file</span>
                </>
              ) : (
                <>
                  <strong>Choose your resume, or drop it here</strong>
                  <span className="muted small">PDF, DOCX, TXT or MD, up to 8 MB</span>
                </>
              )}
            </label>

            {error && <p className="error" role="alert">{error}</p>}
            <button className="btn primary wide" disabled={!resume}>Continue</button>
            <p className="muted small">About {INTERVIEW_QUESTION_COUNT} questions, spoken aloud, around 30 to 40 minutes.</p>
          </form>
        )}

        {step === "preparing" && (
          <section className="card">
            <h1>Getting your interview ready</h1>
            <p className="muted">This takes a few seconds. Please keep this page open.</p>
            <Progress stage={stage} />
          </section>
        )}

        {step === "check" && (
          <div className="check-step">
            <DeviceCheck />
            <section className="card">
              <h2>Ready when you are</h2>
              <p className="muted small">
                {REQUIRE_FULLSCREEN
                  ? "The interview opens full screen. Find a quiet place, look at the camera, and answer out loud. Aria will say hello first."
                  : "Find a quiet place, look at the camera, and answer out loud. Aria will say hello first."}
              </p>
              <p className="muted small">{TRANSCRIPT_NOTICE}</p>
              {PROCTORING_ENABLED && (
                <label className="check-row consent">
                  <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                  <span>{PROCTORING_CONSENT_TEXT}</span>
                </label>
              )}
              <button className="btn primary wide" onClick={begin} disabled={starting || (PROCTORING_ENABLED && !consent)}>
                {starting ? "Starting…" : "Start interview"}
              </button>
              <button className="link" onClick={() => { setStep("upload"); setCreated(null); }}>Use a different resume</button>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}