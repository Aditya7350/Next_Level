import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AdminDashboard({ user, onSwitchToCandidate, onLogout }) {
  const [stats, setStats] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"); // all | has_resume | completed
  const [loading, setLoading] = useState(true);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerTab, setDrawerTab] = useState("profile"); // profile | report | transcript

  useEffect(() => {
    loadDashboard();
  }, []);

  async function loadDashboard() {
    setLoading(true);
    try {
      const [s, c] = await Promise.all([
        api.getAdminStats().catch(() => ({})),
        api.listCandidates().catch(() => ({ candidates: [] })),
      ]);
      setStats(s);
      setCandidates(c.candidates || []);
    } catch (err) {
      console.error("Failed to load admin data", err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSearch(e) {
    const q = e.target.value;
    setSearch(q);
    try {
      const res = await api.listCandidates(q);
      setCandidates(res.candidates || []);
    } catch (err) {
      console.error(err);
    }
  }

  async function openCandidate(candidateId) {
    setDrawerLoading(true);
    setSelectedCandidate({ id: candidateId });
    setDrawerTab("profile");
    try {
      const dossier = await api.getCandidateDossier(candidateId);
      setSelectedCandidate(dossier);
    } catch (err) {
      console.error("Failed to fetch candidate dossier", err);
    } finally {
      setDrawerLoading(false);
    }
  }

  const filteredCandidates = candidates.filter((c) => {
    if (filter === "has_resume") return c.has_resume;
    if (filter === "completed") return c.latest_interview && c.latest_interview.status === "completed";
    return true;
  });

  return (
    <div className="page admin-page">
      {/* Top Navigation */}
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">AI</span>
          <span className="brand-name">AI Interview • Recruiter Portal</span>
        </div>
        <div className="topbar-right">
          <span className="muted">{user?.name} (Admin)</span>
          <button className="btn subtle" onClick={onSwitchToCandidate}>
            Candidate View
          </button>
          <button className="btn ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      {/* KPI Stats Bar */}
      <section className="admin-stats-grid">
        <div className="admin-stat-card">
          <span className="stat-card-title">Total Candidates</span>
          <span className="stat-card-number">{stats?.total_candidates ?? "—"}</span>
        </div>
        <div className="admin-stat-card">
          <span className="stat-card-title">Resumes Uploaded</span>
          <span className="stat-card-number">{stats?.total_resumes ?? "—"}</span>
        </div>
        <div className="admin-stat-card">
          <span className="stat-card-title">Interviews Conducted</span>
          <span className="stat-card-number">{stats?.total_interviews ?? "—"}</span>
        </div>
        <div className="admin-stat-card">
          <span className="stat-card-title">Average Assessment Score</span>
          <span className="stat-card-number" style={{ color: "var(--accent)" }}>
            {stats?.average_score ? `${stats.average_score} / 5.0` : "—"}
          </span>
        </div>
        <div className="admin-stat-card">
          <span className="stat-card-title">Integrity Flags</span>
          <span className="stat-card-number" style={{ color: stats?.flagged_sessions ? "var(--danger)" : "var(--text)" }}>
            {stats?.flagged_sessions ?? 0}
          </span>
        </div>
      </section>

      {/* Toolbar & Search */}
      <div className="admin-toolbar">
        <div>
          <h2>Candidate Talent Pool</h2>
          <p className="muted small">Review resumes, extracted skill profiles, and live interview audit reports.</p>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="search"
            className="admin-search-input"
            placeholder="Search candidates, skills, or email…"
            value={search}
            onChange={handleSearch}
          />
          <div className="report-tabs" style={{ margin: 0 }}>
            <button
              className={`tab-btn ${filter === "all" ? "active" : ""}`}
              onClick={() => setFilter("all")}
            >
              All ({candidates.length})
            </button>
            <button
              className={`tab-btn ${filter === "has_resume" ? "active" : ""}`}
              onClick={() => setFilter("has_resume")}
            >
              Resume Attached
            </button>
            <button
              className={`tab-btn ${filter === "completed" ? "active" : ""}`}
              onClick={() => setFilter("completed")}
            >
              Completed Interviews
            </button>
          </div>
        </div>
      </div>

      {/* Candidates Data Table */}
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Extracted Top Skills</th>
              <th>Resume</th>
              <th>Latest Interview</th>
              <th>Score & Verdict</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan="6" style={{ textAlign: "center", padding: "32px" }}>
                  <p className="muted">Loading candidate data…</p>
                </td>
              </tr>
            ) : filteredCandidates.length === 0 ? (
              <tr>
                <td colSpan="6" style={{ textAlign: "center", padding: "32px" }}>
                  <p className="muted">No candidates match your search filter.</p>
                </td>
              </tr>
            ) : (
              filteredCandidates.map((c) => {
                const latest = c.latest_interview;
                const score = latest?.score;
                const verdict = latest?.verdict;
                return (
                  <tr key={c.id}>
                    <td>
                      <div>
                        <strong>{c.name}</strong>
                        <div className="muted small">{c.email}</div>
                      </div>
                    </td>
                    <td>
                      <div className="chips" style={{ gap: "4px" }}>
                        {c.skills?.length > 0 ? (
                          c.skills.slice(0, 4).map((s) => (
                            <span key={s} className="chip small" style={{ padding: "2px 8px", fontSize: "11px" }}>
                              {s}
                            </span>
                          ))
                        ) : (
                          <span className="muted small">No parsed skills</span>
                        )}
                        {c.skills?.length > 4 && (
                          <span className="muted small">+{c.skills.length - 4}</span>
                        )}
                      </div>
                    </td>
                    <td>
                      {c.has_resume ? (
                        <span className="badge-tag success">Uploaded</span>
                      ) : (
                        <span className="badge-tag neutral">Missing</span>
                      )}
                    </td>
                    <td>
                      {latest ? (
                        <div>
                          <div>{latest.role_title}</div>
                          <div className="muted small" style={{ textTransform: "capitalize" }}>
                            {latest.difficulty} • {latest.status}
                          </div>
                        </div>
                      ) : (
                        <span className="muted small">Not started</span>
                      )}
                    </td>
                    <td>
                      {score !== null && score !== undefined ? (
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <strong>{score} / 5.0</strong>
                          {verdict && (
                            <span className={`verdict-pill ${verdict.toLowerCase().replace(/[^a-z]+/g, "-")}`} style={{ padding: "2px 8px", fontSize: "11px" }}>
                              {verdict}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="muted small">—</span>
                      )}
                    </td>
                    <td>
                      <button className="btn subtle" onClick={() => openCandidate(c.id)}>
                        View Dossier
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Candidate Dossier Drawer / Modal */}
      {selectedCandidate && (
        <div className="modal-overlay" onClick={() => setSelectedCandidate(null)}>
          <div className="drawer-content" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <div>
                <span className="eyebrow">Candidate Dossier</span>
                <h2>{selectedCandidate.candidate?.name || "Candidate Details"}</h2>
                <span className="muted small">{selectedCandidate.candidate?.email}</span>
              </div>
              <button className="drawer-close-btn" onClick={() => setSelectedCandidate(null)}>
                ✕
              </button>
            </div>

            {/* Drawer Tabs */}
            <div className="report-tabs" style={{ marginBottom: "16px" }}>
              <button
                className={`tab-btn ${drawerTab === "profile" ? "active" : ""}`}
                onClick={() => setDrawerTab("profile")}
              >
                Profile & Resume
              </button>
              <button
                className={`tab-btn ${drawerTab === "report" ? "active" : ""}`}
                onClick={() => setDrawerTab("report")}
              >
                Assessment Report
              </button>
              <button
                className={`tab-btn ${drawerTab === "transcript" ? "active" : ""}`}
                onClick={() => setDrawerTab("transcript")}
              >
                Integrity & History
              </button>
            </div>

            {drawerLoading ? (
              <div style={{ padding: "40px", textAlign: "center" }}>
                <p className="muted">Loading full candidate dossier…</p>
              </div>
            ) : (
              <div className="drawer-body">
                {/* DRAWER TAB 1: PROFILE & RESUME */}
                {drawerTab === "profile" && (
                  <>
                    <section className="card">
                      <h3>Extracted Skills & Competencies</h3>
                      {selectedCandidate.resume?.skills?.length ? (
                        <ul className="chips" style={{ marginTop: "10px" }}>
                          {selectedCandidate.resume.skills.map((s) => (
                            <li key={s} className="chip good">✓ {s}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted small">No extracted skills found.</p>
                      )}
                    </section>

                    {selectedCandidate.resume?.profile?.experience?.length > 0 && (
                      <section className="card">
                        <h3>Extracted Work Experience</h3>
                        <ul className="plain small" style={{ marginTop: "8px" }}>
                          {selectedCandidate.resume.profile.experience.map((exp, i) => (
                            <li key={i}>• {exp}</li>
                          ))}
                        </ul>
                      </section>
                    )}

                    {selectedCandidate.resume?.profile?.projects?.length > 0 && (
                      <section className="card">
                        <h3>Key Projects Mentioned</h3>
                        <ul className="plain small" style={{ marginTop: "8px" }}>
                          {selectedCandidate.resume.profile.projects.map((proj, i) => (
                            <li key={i}>• {proj}</li>
                          ))}
                        </ul>
                      </section>
                    )}

                    {selectedCandidate.resume?.parsed_text && (
                      <section className="card">
                        <h3>Raw Parsed Resume Text</h3>
                        <pre style={{
                          background: "var(--bg)",
                          padding: "14px",
                          borderRadius: "10px",
                          fontSize: "12px",
                          whiteSpace: "pre-wrap",
                          maxHeight: "260px",
                          overflowY: "auto",
                          color: "var(--soft)",
                        }}>
                          {selectedCandidate.resume.parsed_text}
                        </pre>
                      </section>
                    )}
                  </>
                )}

                {/* DRAWER TAB 2: LATEST INTERVIEW REPORT */}
                {drawerTab === "report" && (
                  <>
                    {selectedCandidate.interviews?.[0]?.report ? (
                      (() => {
                        const rep = selectedCandidate.interviews[0].report;
                        return (
                          <>
                            {(rep.status === "terminated" || rep.termination_reason) && (
                              <section
                                className="card"
                                style={{
                                  background: "rgba(239, 68, 68, 0.12)",
                                  border: "1px solid rgba(239, 68, 68, 0.4)",
                                  padding: "12px 16px",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "10px",
                                }}
                              >
                                <span style={{ fontSize: "20px" }}>⚠️</span>
                                <div>
                                  <strong style={{ color: "#f87171", fontSize: "13px" }}>
                                    Concluded Early: Proctoring Warning Limit Reached
                                  </strong>
                                  <p className="small muted" style={{ margin: 0 }}>
                                    Candidate reached maximum guideline warnings. Scorecard reflects answers submitted prior to conclusion.
                                  </p>
                                </div>
                              </section>
                            )}

                            <section className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <div>
                                <h3>Technical Score: {rep.score} / 5.0</h3>
                                <p className="muted small">{rep.verdict || "Assessment Complete"}</p>
                              </div>
                              <div className="score-badge" style={{ width: "80px", height: "80px" }}>
                                <span className="score-num" style={{ fontSize: "24px" }}>{rep.score}</span>
                              </div>
                            </section>

                            <section className="card">
                              <h3>Score by Topic</h3>
                              <ul className="bars" style={{ marginTop: "12px" }}>
                                {Object.entries(rep.area_scores || {}).map(([area, val]) => (
                                  <li key={area}>
                                    <div className="bar-label">
                                      <span style={{ textTransform: "capitalize" }}>{area}</span>
                                      <span className="muted">{val} / 5</span>
                                    </div>
                                    <div className="bar-track">
                                      <div className="bar-fill" style={{ width: `${(val / 5) * 100}%` }} />
                                    </div>
                                  </li>
                                ))}
                              </ul>
                            </section>

                            <section className="card">
                              <h3>Demonstrated Strengths</h3>
                              <ul className="chips" style={{ marginTop: "8px" }}>
                                {(rep.strengths || []).map((s) => (
                                  <li key={s} className="chip good">{s}</li>
                                ))}
                              </ul>
                            </section>

                            <section className="card">
                              <h3>Improvement Areas</h3>
                              <ul className="chips" style={{ marginTop: "8px" }}>
                                {(rep.improvement_areas || []).map((s) => (
                                  <li key={s} className="chip">{s}</li>
                                ))}
                              </ul>
                            </section>
                          </>
                        );
                      })()
                    ) : (
                      <p className="muted">No completed interview report available for this candidate.</p>
                    )}
                  </>
                )}

                {/* DRAWER TAB 3: PROCTORING & HISTORY */}
                {drawerTab === "transcript" && (
                  <>
                    <section className="card">
                      <h3>Proctoring & Trust Summary</h3>
                      {selectedCandidate.interviews?.[0]?.report?.integrity ? (
                        (() => {
                          const integ = selectedCandidate.interviews[0].report.integrity;
                          const ivId = selectedCandidate.interviews[0].interview.id;
                          return (
                            <div style={{ marginTop: "10px" }}>
                              <p><strong>Trust Score:</strong> {integ.integrity_score ?? 100}% ({integ.integrity_verdict || "Clean"})</p>
                              <p className="small muted">Total warnings issued: {integ.warnings || 0}</p>
                              <p className="small muted">
                                Identity / Person Mismatches:{" "}
                                <strong style={{ color: (integ.by_type?.different_person || 0) > 0 ? "#ef4444" : "inherit" }}>
                                  {integ.by_type?.different_person || 0}
                                </strong>
                              </p>
                              <p className="small muted">Multiple people detected: {integ.by_type?.multiple_people || 0}</p>
                              <p className="small muted">Tab switch violations: {integ.by_type?.tab_hidden || 0}</p>
                              <p className="small muted">Device detected: {integ.by_type?.device || 0}</p>

                              {integ.has_baseline_image && (
                                <div style={{ marginTop: "16px", padding: "12px", background: "rgba(255,255,255,0.03)", borderRadius: "8px", border: "1px solid var(--line)" }}>
                                  <strong style={{ fontSize: "12px", display: "block", marginBottom: "8px", color: "var(--accent)" }}>
                                    ✓ Verified Baseline Portrait (Starting Candidate):
                                  </strong>
                                  <img
                                    src={`/api/v1/admin/interview/${ivId}/snapshot/baseline.jpg`}
                                    alt="Candidate baseline"
                                    style={{ width: "110px", height: "110px", objectFit: "cover", borderRadius: "8px", border: "2px solid #10b981" }}
                                    onError={(e) => { e.target.style.display = "none"; }}
                                  />
                                </div>
                              )}
                            </div>
                          );
                        })()
                      ) : (
                        <p className="muted small">No proctoring session recorded.</p>
                      )}
                    </section>

                    <section className="card">
                      <h3>Interview Sessions ({selectedCandidate.interviews?.length || 0})</h3>
                      <ul className="plain small" style={{ marginTop: "8px" }}>
                        {(selectedCandidate.interviews || []).map((iv, idx) => (
                          <li key={idx} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                            <strong>{iv.interview.role_title}</strong> ({iv.interview.difficulty})
                            <div className="muted">Status: {iv.interview.status} • Answers: {iv.answers_count}</div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
