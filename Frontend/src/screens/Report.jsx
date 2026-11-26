import { useState } from "react";

const normalise = (s) => String(s).toLowerCase().replace(/[^a-z0-9@ ]+/g, " ").replace(/\s+/g, " ").trim();

function sameIdea(a, b) {
  if (a === b) return true;
  const [short, long] = a.length <= b.length ? [a, b] : [b, a];
  return short.split(" ").length >= 3 && long.includes(short);
}

function tidy(list, exclude = []) {
  const seen = exclude.map(normalise);
  const out = [];
  for (const item of list || []) {
    const key = normalise(item);
    if (!key || seen.some((s) => sameIdea(s, key))) continue;
    seen.push(key);
    out.push(item);
  }
  return out;
}

export default function Report({ report, user, onNew, onLogout }) {
  const [activeTab, setActiveTab] = useState("overview"); // overview | qna | integrity
  const areas = Object.entries(report.area_scores || {});
  const score = Number(report.score) || 0;
  const strengths = tidy(report.strengths);
  const gaps = tidy(report.improvement_areas, strengths);

  const candidateName = report.candidate_name || user?.name || "Candidate";
  const roleTitle = report.role_title || "Technical Interview";
  const verdict = report.verdict || (score >= 4.2 ? "Strong Hire" : score >= 3.6 ? "Qualified" : score >= 3.0 ? "Borderline / Needs Review" : "Needs Improvement");
  const duration = report.duration_minutes ? `${report.duration_minutes} min` : "15 min";
  const dateFormatted = report.completed_at ? new Date(report.completed_at).toLocaleDateString(undefined, { dateStyle: "medium" }) : new Date().toLocaleDateString();

  const integrity = report.integrity || { checked: false, warnings: 0, flags: 0, by_type: {}, integrity_score: 100, integrity_verdict: "Clean Session" };
  const integrityScore = integrity.integrity_score ?? Math.max(0, 100 - ((integrity.warnings || 0) * 20 + (integrity.flags || 0) * 5));
  const integrityVerdict = integrity.integrity_verdict || ((integrity.warnings || 0) === 0 ? "Clean & Verified" : "Minor Flags Logged");

  const qnaList = report.qna || [];

  return (
    <div className="page report-page">
      <header className="topbar no-print">
        <div className="brand">
          <span className="logo" aria-hidden="true">AI</span>
          <span className="brand-name">AI Interview</span>
        </div>
        <div className="topbar-right">
          <span className="muted">{candidateName}</span>
          <button className="btn subtle" onClick={() => window.print()}>
            Export / Print PDF
          </button>
          <button className="btn ghost" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <main className="report">
        {/* Early Conclusion / Warning Notice if session terminated */}
        {(report.status === "terminated" || report.termination_reason) && (
          <div
            className="card"
            style={{
              background: "rgba(239, 68, 68, 0.12)",
              border: "1px solid rgba(239, 68, 68, 0.4)",
              borderRadius: "12px",
              padding: "16px 20px",
              marginBottom: "16px",
              display: "flex",
              alignItems: "center",
              gap: "14px",
            }}
          >
            <span style={{ fontSize: "28px" }}>⚠️</span>
            <div>
              <strong style={{ display: "block", color: "#f87171", fontSize: "15px", marginBottom: "3px" }}>
                Interview Concluded Early (Proctoring Warnings Limit Reached)
              </strong>
              <p className="small muted" style={{ margin: 0, color: "var(--soft)", lineHeight: "1.5" }}>
                This session was ended before all questions were completed due to guideline warnings.
                The technical scorecard below evaluates all answers submitted prior to conclusion, alongside complete integrity audit logs.
              </p>
            </div>
          </div>
        )}

        {/* Candidate & Assessment Metadata Header */}
        <section className="card candidate-meta-card">
          <div className="meta-left">
            <span className="eyebrow">Official Assessment Dossier</span>
            <h1>{candidateName}</h1>
            <p className="muted small meta-subtitle">
              Role: <strong>{roleTitle}</strong> • Level: <strong style={{ textTransform: "capitalize" }}>{report.difficulty || "Intermediate"}</strong> • Duration: <strong>{duration}</strong> • Date: <strong>{dateFormatted}</strong>
            </p>
          </div>
          <div className="meta-right">
            <span className={`verdict-pill ${verdict.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
              {verdict}
            </span>
          </div>
        </section>

        {/* Executive Score & Overall Metrics */}
        <section className="card report-head">
          <div className="head-text">
            <h2>Overall Technical Evaluation</h2>
            <p className="muted">
              {score >= 4.0
                ? "Demonstrated high technical depth, robust trade-off reasoning, and clear verbal communication across key competencies."
                : score >= 3.2
                ? "Solid foundational grasp with commendable practical experience. Minor gaps identified in advanced production trade-offs."
                : "Needs further hands-on practice in core system fundamentals and explaining architectural mechanisms."}
            </p>
          </div>
          <div className="score-badge" aria-label={`Overall score ${score} out of 5`}>
            <span className="score-num">{score}</span>
            <span className="score-of">out of 5.0</span>
          </div>
        </section>

        {/* Navigation Tabs */}
        <div className="report-tabs no-print">
          <button
            className={`tab-btn ${activeTab === "overview" ? "active" : ""}`}
            onClick={() => setActiveTab("overview")}
          >
            Performance Overview
          </button>
          <button
            className={`tab-btn ${activeTab === "qna" ? "active" : ""}`}
            onClick={() => setActiveTab("qna")}
          >
            Question-by-Question Audit ({qnaList.length || report.review?.length || 0})
          </button>
          <button
            className={`tab-btn ${activeTab === "integrity" ? "active" : ""}`}
            onClick={() => setActiveTab("integrity")}
          >
            Integrity & Proctoring ({integrityScore}%)
          </button>
        </div>

        {/* TAB 1: OVERVIEW */}
        {(activeTab === "overview" || window.matchMedia?.("print")?.matches) && (
          <>
            <div className="report-grid">
              <section className="card">
                <h2>Score by Competency Area</h2>
                {areas.length === 0 && <p className="muted">No topic scores available.</p>}
                <ul className="bars">
                  {areas.map(([area, value]) => (
                    <li key={area}>
                      <div className="bar-label">
                        <span style={{ textTransform: "capitalize" }}>{area}</span>
                        <span className="muted"><strong>{value}</strong> / 5.0</span>
                      </div>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width: `${Math.max(5, Math.min(100, (value / 5) * 100))}%`,
                            background: value >= 4 ? "var(--accent)" : value >= 3 ? "#f2b84b" : "var(--danger)",
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="card">
                <h2>Proctoring & Session Integrity</h2>
                <div className="integrity-mini-card">
                  <div className="integrity-score-dial">
                    <span className="int-score-num">{integrityScore}%</span>
                    <span className="int-score-label">Trust Index</span>
                  </div>
                  <div className="integrity-mini-info">
                    <strong className="int-verdict-title">{integrityVerdict}</strong>
                    <p className="muted small">
                      {integrity.warnings === 0
                        ? "Zero candidate warnings issued. Candidate remained present and attentive."
                        : `${integrity.warnings} warning(s) issued during the interview session.`}
                    </p>
                  </div>
                </div>
                <ul className="plain small" style={{ marginTop: "12px" }}>
                  <li>Tab Switch Events: <strong>{integrity.by_type?.tab_hidden || 0}</strong></li>
                  <li>Secondary Devices Detected: <strong>{integrity.by_type?.device || 0}</strong></li>
                  <li>Multiple People in View: <strong>{integrity.by_type?.multiple_people || 0}</strong></li>
                  <li>Identity Mismatch Flags: <strong style={{ color: (integrity.by_type?.different_person || 0) > 0 ? "var(--danger)" : "inherit" }}>{integrity.by_type?.different_person || 0}</strong></li>
                </ul>
              </section>
            </div>

            <div className="report-grid">
              <section className="card">
                <h2>Demonstrated Strengths</h2>
                {strengths.length ? (
                  <ul className="chips">
                    {strengths.map((s) => (
                      <li key={s} className="chip good">✓ {s}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Nothing recorded yet.</p>
                )}
              </section>

              <section className="card">
                <h2>Areas for Further Practice</h2>
                {gaps.length ? (
                  <ul className="chips">
                    {gaps.map((s) => (
                      <li key={s} className="chip">⚠ {s}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No knowledge gaps detected.</p>
                )}
              </section>
            </div>

            <section className="card">
              <h2>Key Hiring Recommendations & Feedback</h2>
              <ul className="plain">
                {(report.recommendations || []).map((r, i) => (
                  <li key={i}>• {r}</li>
                ))}
              </ul>
            </section>
          </>
        )}

        {/* TAB 2: DETAILED QUESTION & ANSWER AUDIT */}
        {activeTab === "qna" && (
          <section className="card">
            <h2>Detailed Question & Answer Audit Trail</h2>
            <p className="muted small" style={{ marginBottom: "16px" }}>
              Verbatim candidate transcripts scored by the Evidence-Based AI Judge with checkable rubric points.
            </p>

            {qnaList.length > 0 ? (
              <div className="qna-dossier-list">
                {qnaList.map((item, idx) => (
                  <div key={idx} className="qna-item-box">
                    <div className="qna-item-head">
                      <div>
                        <span className="qna-tag">Q{item.index || idx + 1} • {item.topic}</span>
                        <h3 className="qna-question-text">{item.question}</h3>
                      </div>
                      <div className="qna-score-pill">
                        Score: <strong>{item.score}</strong> / 5
                      </div>
                    </div>

                    <div className="qna-answer-box">
                      <span className="qna-label">Candidate Answer:</span>
                      <p className="qna-answer-text">
                        "{item.candidate_answer || "(No verbal answer recorded)"}"
                      </p>
                    </div>

                    {item.feedback && (
                      <div className="qna-feedback-box">
                        <span className="qna-label">Interviewer Feedback:</span>
                        <p className="small">{item.feedback}</p>
                      </div>
                    )}

                    {item.key_points?.length > 0 && (
                      <div className="qna-rubric-box">
                        <span className="qna-label">Key Rubric Expectations:</span>
                        <ul className="plain small">
                          {item.key_points.map((kp, kIdx) => (
                            <li key={kIdx}>• {kp}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : report.review?.length > 0 ? (
              <ul className="review">
                {report.review.map((item, i) => (
                  <li key={i}>
                    <div className="review-head">
                      <strong>{item.question}</strong>
                      <span className="muted">{item.score} / 5</span>
                    </div>
                    {item.key_points?.length > 0 && (
                      <ul className="plain small" style={{ marginTop: "6px" }}>
                        {item.key_points.map((k, j) => (
                          <li key={j}>• {k}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No specific question review items recorded.</p>
            )}
          </section>
        )}

        {/* TAB 3: PROCTORING & INTEGRITY LOG */}
        {activeTab === "integrity" && (
          <section className="card">
            <h2>Integrity Verification Audit Log</h2>
            <div className="integrity-detail-grid">
              <div className="int-stat-box">
                <span className="int-stat-label">Trust Score</span>
                <span className="int-stat-val" style={{ color: integrityScore >= 80 ? "var(--accent)" : "var(--danger)" }}>
                  {integrityScore}%
                </span>
              </div>
              <div className="int-stat-box">
                <span className="int-stat-label">Warnings Issued</span>
                <span className="int-stat-val">{integrity.warnings || 0}</span>
              </div>
              <div className="int-stat-box">
                <span className="int-stat-label">Tab Switches</span>
                <span className="int-stat-val">{integrity.by_type?.tab_hidden || 0}</span>
              </div>
              <div className="int-stat-box">
                <span className="int-stat-label">Devices Detected</span>
                <span className="int-stat-val">{integrity.by_type?.device || 0}</span>
              </div>
              <div className="int-stat-box">
                <span className="int-stat-label">Person Mismatches</span>
                <span className="int-stat-val" style={{ color: (integrity.by_type?.different_person || 0) > 0 ? "var(--danger)" : "inherit" }}>
                  {integrity.by_type?.different_person || 0}
                </span>
              </div>
            </div>

            <h3 style={{ marginTop: "24px", fontSize: "14px" }}>Proctoring Verification Events</h3>
            {(integrity.events || []).length > 0 ? (
              <ul className="integrity-event-timeline">
                {integrity.events.map((evt, idx) => (
                  <li key={idx} className="timeline-item">
                    <span className="timeline-time">
                      {evt.at ? new Date(evt.at).toLocaleTimeString() : `Event #${idx + 1}`}
                    </span>
                    <span className="timeline-type">
                      {evt.type === "tab_hidden" ? "Browser tab hidden / navigated away" :
                       evt.type === "device" ? "External device (phone/tablet) detected in frame" :
                       evt.type === "multiple_people" ? "Multiple faces detected in camera view" :
                       evt.type === "different_person" ? "Identity mismatch: Different person detected in camera view" :
                       evt.type === "no_face" ? "Candidate face not in view" :
                       evt.type === "head_turned" ? "Head turned away from camera" : evt.type}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small" style={{ marginTop: "8px" }}>
                ✓ No adverse proctoring events recorded. Candidate adhered to all interview integrity rules.
              </p>
            )}

            <div className="privacy-badge-note">
              <span>🔒 <strong>Privacy Assurance:</strong> Video frames were processed in-memory via client-edge vision models and discarded immediately. No raw video files were permanently stored.</span>
            </div>
          </section>
        )}

        <div className="actions no-print">
          <button className="btn primary" onClick={onNew}>Start Another Interview</button>
        </div>
      </main>
    </div>
  );
}
