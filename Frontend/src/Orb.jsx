// The interviewer's "voice" shown as a waveform in a ring. Used on the landing and sign-in pages.
// The ring and wave styles live in styles.css; `active` makes the bars move.
const BARS = [16, 30, 48, 26, 62, 84, 50, 34, 70, 96, 58, 38, 74, 52, 30, 64, 42, 22, 34, 18];

export default function Orb({ active = false }) {
  return (
    <div className="orb-lg" aria-hidden="true">
      <span className="ring r1" />
      <span className="ring r2" />
      <div className={`orb ${active ? "active" : ""}`}>
        {BARS.map((h, i) => (
          <span key={i} className="wave" style={{ height: h, "--d": `${(i % 7) * 0.09}s` }} />
        ))}
      </div>
    </div>
  );
}
