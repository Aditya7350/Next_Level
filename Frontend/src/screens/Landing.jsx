import { useEffect, useRef, useState } from "react";
import Orb from "../Orb.jsx";
import { BRAND_NAME, CONTACT_EMAIL } from "../config.js";

// An example exchange for the hero. It is sample content, labelled as such on the page.
const ARIA_LINE = "You mentioned chunking. How would you decide how big each chunk should be?";
const YOU_LINE =
  "I'd start from the embedding model's token limit, then test a few sizes on a small question set and compare recall.";

const STATUS = {
  speaking: "Aria is asking",
  listening: "Your turn",
  answering: "You're answering",
  done: "Next question coming up",
};

const STEPS = [
  {
    title: "Set up the role",
    text: "Paste a job description and add your resume. Aria builds the questions around the skills they name.",
  },
  {
    title: "Answer out loud",
    text: "Aria asks, you speak. If you miss a question, just say “can you repeat that?” and she will.",
  },
  {
    title: "Read your report",
    text: "See your score by topic, what you covered, what you missed, and what a strong answer includes.",
  },
];

const FEATURES = [
  {
    term: "Questions that adapt",
    text: "A strong answer earns a harder question. A weak one gets a short follow-up, then an easier question on the basics, so you never stall on one topic.",
  },
  {
    term: "Scores tied to your words",
    text: "A point only counts as covered when the evaluator can quote it from your answer. A confident answer with nothing behind it can't score well.",
  },
  {
    term: "Built around the role",
    text: "Skills from the job description and your resume decide which topics come up and in what order.",
  },
  {
    term: "Spoken, like the real thing",
    text: "Questions are asked aloud, and Aria waits until you say you've finished. There is no countdown pushing you to rush.",
  },
];

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

// The one animated moment on the page: Aria asks, then the candidate answers. It plays once.
function Conversation() {
  const [reduced] = useState(prefersReducedMotion);
  const [aria, setAria] = useState(reduced ? ARIA_LINE : "");
  const [you, setYou] = useState(reduced ? YOU_LINE : "");
  const [phase, setPhase] = useState(reduced ? "done" : "speaking");

  useEffect(() => {
    if (reduced) return undefined;
    let cancelled = false;
    const timers = [];
    const later = (fn, ms) => timers.push(window.setTimeout(fn, ms));
    const type = (full, set, speed, next) => {
      let i = 0;
      const tick = () => {
        if (cancelled) return;
        i += 1;
        set(full.slice(0, i));
        if (i < full.length) later(tick, speed);
        else if (next) next();
      };
      tick();
    };
    later(() => {
      type(ARIA_LINE, setAria, 36, () => {
        setPhase("listening");
        later(() => {
          setPhase("answering");
          type(YOU_LINE, setYou, 24, () => setPhase("done"));
        }, 900);
      });
    }, 700);
    return () => {
      cancelled = true;
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, [reduced]);

  const moving = phase === "speaking" || phase === "answering";

  return (
    <figure className="lp-convo">
      <p className="sr-only">
        Example: Aria asks, “{ARIA_LINE}” and the candidate answers, “{YOU_LINE}”
      </p>
      <div aria-hidden="true">
        <div className="lp-convo-bar">
          <span className="pill">
            <span className={`dot ${moving ? "live" : ""}`} />
            Aria <span className="muted">{STATUS[phase]}</span>
          </span>
          <span className="muted small">Example conversation</span>
        </div>
        <div className="lp-convo-stage">
          <Orb active={moving} />
        </div>
        <div className="lp-convo-lines">
          <div className="lp-line aria">
            <span className="who">Aria</span>
            <p className={phase === "speaking" ? "lp-caret" : ""}>{aria}</p>
          </div>
          <div className="lp-line you">
            <span className="who">You</span>
            <p className={phase === "answering" ? "lp-caret" : ""}>{you}</p>
          </div>
        </div>
      </div>
    </figure>
  );
}

export default function Landing() {
  const howRef = useRef(null);

  function seeHow() {
    howRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  return (
    <div className="lp">
      <header className="lp-wrap lp-nav">
        <a className="brand" href="#/">
          <span className="logo" aria-hidden="true">AI</span>
          <span className="brand-name">{BRAND_NAME}</span>
        </a>
        <nav className="lp-nav-links" aria-label="Account">
          <a className="lp-signin" href="#/login">Sign in</a>
          <a className="btn primary" href="#/register">Start an interview</a>
        </nav>
      </header>

      <main>
        <section className="lp-wrap lp-hero">
          <div className="lp-hero-copy">
            <h1>An interviewer that listens and follows up</h1>
            <p className="lp-lede">
              Aria asks each question out loud, listens to your answer, and adapts the next question to what you said.
              You finish with a scored report.
            </p>
            <div className="lp-cta-row">
              <a className="btn primary lp-big" href="#/register">Start an interview</a>
              <button type="button" className="btn ghost lp-big" onClick={seeHow}>See how it works</button>
            </div>
            <p className="lp-note">Works best in Chrome or Edge with a microphone. You can type your answers instead.</p>
          </div>
          <Conversation />
        </section>

        <section className="lp-how" ref={howRef}>
          <div className="lp-wrap">
            <h2 className="lp-h2">How an interview runs</h2>
            <ol className="lp-steps">
              {STEPS.map((step, i) => (
                <li key={step.title} className="lp-step">
                  <span className="lp-step-n" aria-hidden="true">{i + 1}</span>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="lp-wrap lp-features">
          <h2 className="lp-h2">What happens behind the questions</h2>
          <dl className="lp-feature-list">
            {FEATURES.map((f) => (
              <div key={f.term} className="lp-feature">
                <dt>{f.term}</dt>
                <dd>{f.text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="lp-cta">
          <div className="lp-wrap lp-cta-inner">
            <div>
              <h2 className="lp-h2 lp-cta-title">Run your first interview</h2>
              <p className="lp-lede">Add a role, answer out loud, and read your report when it ends.</p>
            </div>
            <div className="lp-cta-actions">
              <a className="btn primary lp-big" href="#/register">Create your account</a>
              <p className="lp-note">
                Already have an account? <a className="text-link" href="#/login">Sign in</a>
              </p>
              {CONTACT_EMAIL && (
                <p className="lp-note">
                  Hiring for a team? <a className="text-link" href={`mailto:${CONTACT_EMAIL}`}>Talk to us</a>
                </p>
              )}
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-wrap lp-footer">
        <span>{BRAND_NAME}</span>
        <span>© {new Date().getFullYear()}</span>
      </footer>
    </div>
  );
}
