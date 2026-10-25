// Product name shown on the landing and sign-in pages. Change it here.
export const BRAND_NAME = "AI Interview";

// Shown as "Talk to us" on the landing page for hiring teams. Leave empty to hide the link.
export const CONTACT_EMAIL = "";

// Practice mode shows Aria's feedback after every answer (your /answer endpoint returns it).
// Set to false for real hiring interviews, where candidates should not see scoring detail.
export const SHOW_FEEDBACK = true;

// false: the candidate only HEARS each question (like a real interview) and can say "can you repeat the
// question?" to hear it again. true: the question is also shown as text on screen.
// The text is shown anyway if the browser can't speak, so nobody is left without the question.
export const SHOW_QUESTION_TEXT = false;

// Camera checks during the interview (other people, phones, leaving the tab). Needs the proctoring routes on the
// backend; if they're missing the interview just runs without checks. Set to false to switch everything off.
export const PROCTORING_ENABLED = true;
export const PROCTOR_FRAME_INTERVAL_MS = 4000;

// Shown on the setup screen. Have these checked by someone who knows your privacy obligations before launch,
// and update them if you turn on PROCTOR_SAVE_SNAPSHOTS on the backend.
export const PROCTORING_CONSENT_TEXT =
  "I understand that my camera is checked during the interview for other people in view, phones or other devices, and leaving the interview tab. A note of anything flagged is kept for the hiring team to review.";
export const PROCTORING_PRIVACY_NOTE =
  "Still images from your camera are sent to our server during the interview to run these checks. The images are not stored.";

// The adaptive engine needs MongoDB + OpenAI on the backend. If it is unavailable the backend quietly
// falls back to the built-in question list, so leaving this on is safe.
export const DEFAULT_ADAPTIVE = true;

// The interview flow: the candidate only uploads a resume. Everything else is decided here.
export const INTERVIEW_QUESTION_COUNT = 16;      // the backend allows 1-20
export const DEFAULT_DIFFICULTY = "intermediate"; // foundational | intermediate | advanced

// Ask the browser to go full screen when the interview starts (needs the click on "Start interview").
export const REQUIRE_FULLSCREEN = true;

// Shown on the "check and start" screen. The backend saves each conversation as a text file; keep this in step with
// SAVE_TRANSCRIPTS on the backend and have it checked against the privacy rules where you operate.
export const TRANSCRIPT_NOTICE = "Your spoken answers are converted to text and saved so the interview can be reviewed.";