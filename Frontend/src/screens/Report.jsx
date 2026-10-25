const normalise = (s) => String(s).toLowerCase().replace(/[^a-z0-9@ ]+/g, " ").replace(/\s+/g, " ").trim();

// Two labels name the same idea if they match after tidying case and punctuation, or if one
// (at least three words long) sits inside the other, e.g. "Define dataset size" and "dataset size".
function sameIdea(a, b) {
  if (a === b) return true;
  const [short, long] = a.length <= b.length ? [a, b] : [b, a];
  return short.split(" ").length >= 3 && long.includes(short);
}

// Drops repeats, and anything that matches the `exclude` labels, keeping the first wording.
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
  const areas = Object.entries(report.area_scores || {});
  const score = Number(report.score) || 0;
  const strengths = tidy(report.strengths);
  // Something the candidate covered in one answer shouldn't also be listed as a gap.
  const gaps = tidy(report.improvement_areas, strengths);

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">AI</span>
          <span className="brand-name">AI Interview</span>
        </div>
        <div className="topbar-right">
          <span className="muted">{user?.name}</span>
          <button className="btn ghost" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <main className="report">
        <section className="card report-head">
          <div>
            <p className="eyebrow">Interview complete</p>
            <h1>Your results</h1>
            <p className="muted">Here is how you did and where to focus next.</p>
          </div>
          <div className="score-badge" aria-label={`Overall score ${score} out of 5`}>
            <span className="score-num">{score}</span>
            <span className="score-of">out of 5</span>
          </div>
        </section>

        <div className="report-grid">
          <section className="card">
            <h2>Score by topic</h2>
            {areas.length === 0 && <p className="muted">No topic scores yet.</p>}
            <ul className="bars">
              {areas.map(([area, value]) => (
                <li key={area}>
                  <div className="bar-label">
                    <span>{area}</span>
                    <span className="muted">{value} / 5</span>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${Math.max(0, Math.min(100, (value / 5) * 100))}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="card">
            <h2>What to do next</h2>
            <ul className="plain">
              {(report.recommendations || []).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </section>
        </div>

        <div className="report-grid">
          <section className="card">
            <h2>Strengths</h2>
            {strengths.length ? (
              <ul className="chips">
                {strengths.map((s) => (
                  <li key={s} className="chip good">{s}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">Nothing recorded yet.</p>
            )}
          </section>
          <section className="card">
            <h2>Worth practising</h2>
            {gaps.length ? (
              <ul className="chips">
                {gaps.map((s) => (
                  <li key={s} className="chip">{s}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">No gaps found.</p>
            )}
          </section>
        </div>

        {report.review?.length > 0 && (
          <section className="card">
            <h2>Questions to review</h2>
            <ul className="review">
              {report.review.map((item) => (
                <li key={item.question}>
                  <div className="review-head">
                    <strong>{item.question}</strong>
                    <span className="muted">{item.score} / 5</span>
                  </div>
                  {item.key_points?.length > 0 && (
                    <>
                      <p className="small muted">A strong answer covers:</p>
                      <ul className="plain">
                        {item.key_points.map((k) => (
                          <li key={k}>{k}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="actions">
          <button className="btn primary" onClick={onNew}>Start another interview</button>
        </div>
      </main>
    </div>
  );
}
