import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useDevices } from "../devices.js";
import { useListener, speak, speechInputSupported, speechOutputSupported } from "../speech.js";
import { PROCTORING_ENABLED, REQUIRE_FULLSCREEN, SHOW_FEEDBACK, SHOW_QUESTION_TEXT } from "../config.js";
import { enterFullscreen, exitFullscreen, fullscreenSupported, isFullscreen } from "../fullscreen.js";
import { useProctoring } from "../proctor.js";

const BARS = [16, 30, 48, 26, 62, 84, 50, 34, 70, 96, 58, 38, 74, 52, 30, 64, 42, 22, 34, 18];

function formatTime(total) {
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

// A short spoken or typed phrase asking Aria to say the question again ("can you please repeat the question").
// The length cap keeps a real answer that happens to contain the word "repeat" from being treated as a command.
const REPEAT_WORDS = /\b(repeat|say (that|it) again|ask (that|it|the question) again|come again|pardon|once more|what was the question)\b/i;
function isRepeatRequest(text) {
  const t = String(text).trim();
  return t.split(/\s+/).length <= 9 && REPEAT_WORDS.test(t);
}

function Icon({ children }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

// videoRef (optional) lets the parent read frames from the preview for the camera checks.
function CameraTile({ enabled, videoRef: outerRef }) {
  const { stream, camera } = useDevices({ audio: false });
  const ownRef = useRef(null);
  const videoRef = outerRef || ownRef;

  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream && camera === "ok" ? stream : null;
    if (stream) stream.getVideoTracks().forEach((t) => (t.enabled = enabled));
  }, [stream, camera, enabled]);

  const showVideo = camera === "ok" && enabled;
  return (
    <div className="self-tile">
      {showVideo ? (
        <video ref={videoRef} autoPlay muted playsInline aria-label="Your camera preview" />
      ) : (
        <div className="self-empty">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" />
          </svg>
          <span>{camera === "denied" ? "Camera unavailable" : "Camera off"}</span>
        </div>
      )}
      <span className="self-name">You</span>
    </div>
  );
}

function greetingFor(user, interview) {
  const first = String(user?.name || "").trim().split(/\s+/)[0];
  const role = interview.role_title && interview.role_title !== "Practice interview" ? interview.role_title : "";
  const hi = first ? `Hi ${first}, welcome.` : "Hi, welcome.";
  const about = role ? ` I'll be interviewing you for the ${role} role today.` : " I'll be your interviewer today.";
  return `${hi} I'm Aria.${about} Relax, this is just a conversation. To begin, could you tell me a little about yourself and your background?`;
}

export default function Room({ interview, user, onFinish, onExit }) {
  const total = interview.question_count;
  const [question, setQuestion] = useState(null);
  const [index, setIndex] = useState(1);
  const [phase, setPhase] = useState("loading"); // loading | speaking | ready | thinking
  const [draft, setDraft] = useState("");
  const [transcript, setTranscript] = useState([]);
  const [error, setError] = useState("");
  const [micOn, setMicOn] = useState(true);
  const [voiceOn, setVoiceOn] = useState(true);
  const [camOn, setCamOn] = useState(true);
  const [seconds, setSeconds] = useState(0);
  const [fullscreen, setFullscreen] = useState(isFullscreen());
  const [stage, setStage] = useState("intro"); // intro (greeting + "tell me about yourself") | questions

  const cancelSpeech = useRef(() => {});
  const startedRef = useRef(false);
  const micRef = useRef(true);
  const voiceRef = useRef(true);
  micRef.current = micOn;
  voiceRef.current = voiceOn;
  const transcriptEnd = useRef(null);
  const firstQuestion = useRef(null); // promise of the first real question, fetched while the greeting plays

  // Camera checks start once the first question has arrived (the interview must be "in progress" on the server).
  const cameraRef = useRef(null);
  const proctor = useProctoring({ interviewId: interview.id, videoRef: cameraRef, active: phase !== "loading" });

  const listener = useListener({
    onFinal: (text) => {
      if (isRepeatRequest(text)) repeatQuestion();
      else setDraft((d) => (d ? `${d} ${text}` : text));
    },
  });
  const { start: startListening, stop: stopListening } = listener;

  const beginAnswer = useCallback(() => {
    setPhase("ready");
    if (micRef.current && speechInputSupported) startListening();
  }, [startListening]);

  const ask = useCallback(
    (q) => {
      const text = [q.lead_in, q.question].filter(Boolean).join(" ");
      setQuestion(q);
      setDraft("");
      setTranscript((t) => [...t, { who: "aria", text }]);
      if (voiceRef.current) {
        setPhase("speaking");
        cancelSpeech.current = speak(text, { onEnd: beginAnswer });
      } else {
        beginAnswer();
      }
    },
    [beginAnswer]
  );

  // Start the interview once. The server is told to start straight away (camera checks need that), but the
  // candidate first hears a greeting and an introduction question; the first real question is held back.
  useEffect(() => {
    if (startedRef.current) return undefined;
    startedRef.current = true;
    firstQuestion.current = api.startInterview(interview.id).then((res) => {
      if (!res.question) throw new Error("The interview has no questions.");
      return res.question;
    });
    firstQuestion.current.catch((err) => setError(err.message));
    ask({ question: greetingFor(user, interview) });
    return () => cancelSpeech.current();
  }, [interview, user, ask]);

  // Track full screen so a candidate who pressed Esc is asked to go back; leave it when the interview ends.
  useEffect(() => {
    const onChange = () => setFullscreen(isFullscreen());
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: "nearest" });
  }, [transcript, phase]);

  async function submit() {
    const answer = draft.trim();
    if (!answer || phase === "thinking") return;
    if (isRepeatRequest(answer)) {
      // Typed "repeat the question": answer it, don't send it to be scored.
      setDraft("");
      repeatQuestion();
      return;
    }
    stopListening();
    cancelSpeech.current();
    setPhase("thinking");
    setError("");
    setTranscript((t) => [...t, { who: "you", text: answer }]);
    if (stage === "intro") {
      // The introduction is a warm-up: it is not scored and does not use up one of the questions.
      // It is sent only so the saved conversation is complete; a failure here never blocks the interview.
      api.submitIntro(interview.id, answer, transcript.find((t) => t.who === "aria")?.text || "").catch(() => {});
      try {
        const first = await firstQuestion.current;
        setStage("questions");
        ask({ ...first, lead_in: ["Thanks, that's helpful.", first.lead_in || "Let's get started."].join(" ") });
      } catch (err) {
        setError(err.message);
        beginAnswer();
      }
      return;
    }
    try {
      const res = await api.submitAnswer(interview.id, answer);
      if (SHOW_FEEDBACK && res.evaluation?.feedback) {
        setTranscript((t) => [...t, { who: "feedback", text: res.evaluation.feedback, score: res.evaluation.score }]);
      }
      if (res.status === "completed") {
        const report = res.report || (await api.getReport(interview.id));
        exitFullscreen();
        onFinish(report);
        return;
      }
      if (!res.next_question) throw new Error("The server did not send the next question.");
      setIndex((i) => i + 1);
      ask(res.next_question);
    } catch (err) {
      setError(err.message);
      setTranscript((t) => t.filter((item, i) => !(i === t.length - 1 && item.who === "you")));
      beginAnswer();
    }
  }

  function repeatQuestion() {
    if (!question || phase === "thinking" || phase === "loading") return;
    stopListening();
    cancelSpeech.current();
    const text = [question.lead_in, question.question].filter(Boolean).join(" ");
    setPhase("speaking");
    cancelSpeech.current = speak(text, { onEnd: beginAnswer });
  }

  function toggleMic() {
    const next = !micOn;
    setMicOn(next);
    if (next && phase === "ready" && speechInputSupported) startListening();
    if (!next) stopListening();
  }

  function toggleVoice() {
    const next = !voiceOn;
    setVoiceOn(next);
    if (!next) {
      cancelSpeech.current();
      if (phase === "speaking") beginAnswer();
    }
  }

  function leave() {
    if (window.confirm("End this interview? Your answers so far won't be scored into a report.")) {
      cancelSpeech.current();
      stopListening();
      exitFullscreen();
      onExit();
    }
  }

  const statusText =
    phase === "loading" ? "Getting ready" : phase === "speaking" ? "Speaking" : phase === "thinking" ? "Thinking" : listener.listening ? "Listening" : "Waiting for your answer";
  const active = phase === "speaking" || (phase === "ready" && listener.listening);
  const done = Math.min(index - 1, total);

  const showText = SHOW_QUESTION_TEXT || !speechOutputSupported;
  const repeatByVoice = speechInputSupported && micOn; // otherwise a button is the way to ask again
  const questionText = question ? [question.lead_in, question.question].filter(Boolean).join(" ") : "";
  const captionText = showText
    ? questionText || "Getting your first question…"
    : phase === "loading"
      ? "Getting ready…"
      : phase === "speaking"
        ? stage === "intro" ? "Aria is saying hello…" : "Aria is asking the question…"
        : phase === "thinking"
          ? "Aria is thinking about your answer…"
          : "Your turn. Answer out loud, or type below.";

  return (
    <div className="room">
      <header className="room-top">
        <div className="room-title">
          <span className="logo" aria-hidden="true">AI</span>
          <div>
            <strong>{interview.role_title}</strong>
            <span className="muted small">{interview.difficulty} · {interview.adaptive ? "adaptive" : "standard"} questions</span>
          </div>
        </div>

        <div className="progress">
          <div className="progress-text">
            <span>{stage === "intro" ? "Introduction" : `Question ${Math.min(index, total)} of ${total}`}</span>
            <span className="muted">{done} answered</span>
          </div>
          <div className="progress-bars" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
            {Array.from({ length: total }, (_, i) => (
              <span key={i} className={i < done ? "seg done" : i === done ? "seg now" : "seg"} />
            ))}
          </div>
        </div>

        <div className="room-top-right">
          {proctor.status.on && (
            <span className="pill" title="Your camera is checked during the interview">
              <span className="dot live" aria-hidden="true" />
              Camera checks on
            </span>
          )}
          <div className="timer" aria-label="Time elapsed">{formatTime(seconds)}</div>
        </div>
      </header>

      {proctor.notice && (
        <div className="proctor-banner" role="status">
          <span className="proctor-msg">{proctor.notice.message}</span>
          <span className="muted small">Reminder {proctor.notice.used} of {proctor.notice.max}</span>
          <button type="button" className="btn ghost" onClick={proctor.dismiss}>Got it</button>
        </div>
      )}

      {REQUIRE_FULLSCREEN && fullscreenSupported && !fullscreen && (
        <div className="proctor-banner" role="status">
          <span className="proctor-msg">Please keep the interview full screen.</span>
          <button type="button" className="btn ghost" onClick={enterFullscreen}>Go full screen</button>
        </div>
      )}

      <main className="room-main">
        <section className="stage">
          <div className="pill stage-pill">
            <span className={`dot ${active ? "live" : ""}`} aria-hidden="true" />
            Aria · AI interviewer <span className="muted">{statusText}</span>
          </div>
          <CameraTile enabled={camOn || PROCTORING_ENABLED} videoRef={cameraRef} />

          <div className={`orb-wrap ${phase === "thinking" ? "thinking" : ""}`}>
            <div className="ring r1" />
            <div className="ring r2" />
            <div className={`orb ${active ? "active" : ""}`} aria-hidden="true">
              {BARS.map((h, i) => (
                <span key={i} className="wave" style={{ height: h, "--d": `${(i % 7) * 0.09}s` }} />
              ))}
            </div>
          </div>

          <div className="caption">
            <p className="eyebrow">{stage === "intro" ? "Introduction" : `Question ${Math.min(index, total)}`}</p>
            <p className="question" aria-live="polite">{captionText}</p>
            {!showText && repeatByVoice && (
              <p className="muted small caption-hint">Missed it? Just say “Can you repeat the question?”</p>
            )}
          </div>

          <div className="answer">
            <label htmlFor="answer" className="eyebrow">Your answer</label>
            <textarea
              id="answer"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={phase === "thinking" || phase === "loading"}
              rows={3}
              maxLength={12000}
              placeholder={speechInputSupported ? "Speak, or type here. You can edit before sending." : "Type your answer here."}
            />
            {listener.interim && <p className="interim">{listener.interim}</p>}
            {listener.error && <p className="error small">{listener.error}</p>}
          </div>
        </section>

        <aside className="side">
          <section className="card transcript">
            <div className="row between">
              <h2>{showText ? "Live transcript" : "Your answers"}</h2>
            </div>
            <ol className="log">
              {transcript.filter((item) => showText || item.who !== "aria").map((item, i) => (
                <li key={i} className={`msg ${item.who}`}>
                  <span className="who">{item.who === "aria" ? "Aria" : item.who === "you" ? "You" : `Feedback${item.score ? ` · ${item.score}/5` : ""}`}</span>
                  <span>{item.text}</span>
                </li>
              ))}
              {phase === "thinking" && <li className="msg status">Aria is thinking about your answer…</li>}
              <li ref={transcriptEnd} aria-hidden="true" />
            </ol>
          </section>
        </aside>
      </main>

      {error && (
        <p className="error room-error" role="alert">{error}</p>
      )}

      <footer className="controls">
        <p className="muted small hint">Take your time. Aria waits until you press "I've finished answering".</p>
        <div className="control-row">
          <button className={`icon-btn ${micOn ? "" : "off"}`} onClick={toggleMic} aria-label={micOn ? "Turn microphone off" : "Turn microphone on"} aria-pressed={!micOn}>
            <Icon>
              <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              {!micOn && <path d="M4 4l16 16" />}
            </Icon>
          </button>
          {!PROCTORING_ENABLED && (
            <button className={`icon-btn ${camOn ? "" : "off"}`} onClick={() => setCamOn((v) => !v)} aria-label={camOn ? "Turn camera off" : "Turn camera on"} aria-pressed={!camOn}>
              <Icon>
                <rect x="3" y="6" width="13" height="12" rx="2" />
                <path d="M16 10l5-3v10l-5-3" />
                {!camOn && <path d="M4 4l16 16" />}
              </Icon>
            </button>
          )}
          {showText && (
            <button className={`icon-btn ${voiceOn ? "" : "off"}`} onClick={toggleVoice} aria-label={voiceOn ? "Mute Aria's voice" : "Unmute Aria's voice"} aria-pressed={!voiceOn}>
              <Icon>
                <path d="M11 5L6 9H3v6h3l5 4V5z" />
                {voiceOn ? <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /> : <path d="M16 9l5 6M21 9l-5 6" />}
              </Icon>
            </button>
          )}
          {(showText || !repeatByVoice) && (
            <button className="btn subtle" onClick={repeatQuestion} disabled={!question || phase === "thinking"}>
              Repeat question
            </button>
          )}
        </div>
        <div className="control-row end">
          <button className="btn danger" onClick={leave}>End interview</button>
          <button className="btn primary" onClick={submit} disabled={!draft.trim() || phase === "thinking" || phase === "loading"}>
            {phase === "thinking" ? "Sending…" : "I've finished answering"}
          </button>
        </div>
      </footer>
    </div>
  );
}