"""Interview plan written from ONE candidate's resume, for any field.

Place at: app/interview/planner.py

The question bank can never cover every field, so the questions come from the resume itself. When the resume is
processed, the model reads it (profile, projects, experience, skills, plus the job description if there is one),
works out the person's field and seniority, and writes the interview: questions on their own projects and work,
real knowledge questions for their field, and a few situational ones. Each has expected concepts and key points so
answers can be scored. Three calls run in parallel to keep the "preparing" step short.

The interview then picks from this plan one question at a time (see interviews.py), moving easier or harder by how
the candidate answers. The MongoDB bank is still used when it clearly matches their field.

Environment (optional): PLAN_MODEL (default gpt-4o-mini), PLAN_TIMEOUT seconds per call (default 40).
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

MODEL = os.getenv("PLAN_MODEL", "gpt-4o-mini")
TIMEOUT = float(os.getenv("PLAN_TIMEOUT", "40"))
LEVELS = ("basic", "intermediate", "advanced")
BANK_TO_API = {"basic": "foundational", "intermediate": "intermediate", "advanced": "advanced"}

SYSTEM = "You are an experienced hiring interviewer in the candidate's own field. Reply with one JSON object only."

COMMON_RULES = """Rules for every question:
- The resume text may be messy (columns, tables, odd headings), and the parsed fields may be incomplete or put under the wrong
  heading. Trust the full resume text. Ignore formatting noise.
- If the candidate is a fresher or student, build on education, academic and personal projects, internships, certifications,
  coursework and extracurricular work, and set the difficulty to match. If they are changing careers, include how their earlier
  experience carries over. Write the questions in English.
- Be fair: never base a question on the candidate's name, gender, age, religion, nationality, marital status, health, photo,
  or on how well known their school or employer is. Only ask about skills, knowledge, work and experience.
- The interview is spoken aloud: no code to write, no tables, no diagrams. Natural wording, under 45 words, one clear question.
- First work out the candidate's field and seniority from the resume (a fresher, mid-level and senior person get different depth).
  Ask what a good hiring manager in THAT field would ask. Never assume the field is software or AI.
- Do not begin with "Your resume mentions" or similar templates. Refer to specifics naturally ("You built X; how did you...").
- Questions must be different from each other and each test something specific.
- difficulty is basic, intermediate or advanced, matched to the candidate's seniority and what the question demands.
- expected_concepts: 3-5 short, concrete items a strong answer would name.
- reference_answer.key_points: 3-5 checkable points a strong answer contains. For questions about the candidate's OWN work you
  cannot know the facts, so write what a credible answer shows (their specific role, a decision and its reason, a result).
  For knowledge questions write the correct content.
- evaluation_criteria: 2-4 checkable statements, each tied to an expected concept. No vague traits like "critical thinking".
Return: {"questions": [{"difficulty": "basic|intermediate|advanced", "topic": "...", "subtopic": "...", "question": "...",
"expected_concepts": ["..."], "reference_answer": {"summary": "...", "key_points": ["..."]},
"evaluation_criteria": ["..."]}]}"""

BRIEFS = {
    "projects": ("Write {n} questions that dig into the candidate's OWN projects and work experience: what they built or did, "
                 "what they personally owned, a decision they made and why, something that went wrong, how they measured the result. "
                 "Use the real project and company details from the resume. Make the first one an easy, friendly opener about their "
                 "background or a project they are proud of."),
    "domain": ("Write {n} knowledge questions on the core skills and subject matter of this candidate's field and role, drawn from the "
               "skills they list and what the job needs. Cover different areas, from fundamentals to harder judgement calls. For a "
               "technical field ask technical questions; for a non-technical field ask real domain questions (methods, tools, "
               "standards, how things are done)."),
    "situational": ("Write {n} realistic scenario questions for this field ('a customer/client/colleague does X; what do you do?' or "
                    "'tell me about a time...'), specific to the role and the candidate's seniority."),
}
SPLIT = {"projects": 0.375, "domain": 0.5, "situational": 0.125}   # of 16: 6 / 8 / 2


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _strings(value, lo: int, hi: int, maxlen: int) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out = [" ".join(v.split())[:maxlen] for v in value if isinstance(v, str) and v.strip()][:hi]
    return out if len(out) >= lo else None


def _clean(raw: dict, kind: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    q = " ".join(str(raw.get("question", "")).split())
    level = str(raw.get("difficulty", "")).lower()
    ref = raw.get("reference_answer") if isinstance(raw.get("reference_answer"), dict) else {}
    concepts = _strings(raw.get("expected_concepts"), 2, 5, 70)
    points = _strings(ref.get("key_points"), 3, 5, 220)
    if level not in LEVELS or not (15 <= len(q) <= 420) or not concepts or not points:
        return None
    topic = " ".join(str(raw.get("topic") or "").split())[:50] or kind.title()
    sub = " ".join(str(raw.get("subtopic") or "").split())[:60] or topic
    return {"question": q, "difficulty": level, "topic": topic, "subtopic": sub, "expected_concepts": concepts,
            "key_points": points, "criteria": _strings(raw.get("evaluation_criteria"), 0, 4, 180) or [],
            "plan_kind": kind}


RAW_TEXT_KEYS = ("text", "raw_text", "resume_text", "extracted_text", "content")


def resume_text(resume: dict) -> str:
    """The full extracted text of the resume, if the record kept it (looks at the usual key names)."""
    profile = resume.get("profile") if isinstance(resume.get("profile"), dict) else {}
    for holder in (resume, profile):
        for key in RAW_TEXT_KEYS:
            if isinstance(holder.get(key), str) and holder[key].strip():
                return holder[key]
    return ""


def profile_brief(resume: dict, jd: dict | None) -> str:
    """The resume as plain text for the prompt: the FULL text first (any field, any layout), the parser's profile as hints."""
    profile = resume.get("profile") if isinstance(resume.get("profile"), dict) else {}
    parts = []
    raw = resume_text(resume)
    if raw:
        parts.append(f"FULL RESUME TEXT:\n{raw[:9000]}")
    hints = []
    for key in ("summary", "experience", "projects", "skills", "education", "certifications"):
        val = profile.get(key)
        if isinstance(val, list):
            val = "; ".join(str(v) for v in val if v)
        if val:
            hints.append(f"{key.title()}: {str(val)[:1500]}")
    if hints:
        parts.append("PARSED FIELDS (may be incomplete):\n" + "\n".join(hints))
    if jd:
        parts.append(f"Target job: {jd.get('title') or jd.get('role') or ''}; "
                     f"required skills: {', '.join(jd.get('required_skills', [])[:15])}")
    return "\n\n".join(parts)[:13000]


def _call(brief: str, kind: str, n: int) -> list[dict]:
    from openai import OpenAI

    prompt = f"CANDIDATE\n{brief}\n\nTASK\n{BRIEFS[kind].format(n=n)}\n\n{COMMON_RULES}"
    resp = OpenAI(timeout=TIMEOUT).chat.completions.create(
        model=MODEL, temperature=0.7, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
    items = json.loads(resp.choices[0].message.content or "{}").get("questions", [])
    return [q for q in (_clean(i, kind) for i in items) if q]


def build_plan(resume: dict, jd: dict | None, count: int = 16) -> list[dict]:
    """Questions for this candidate, about 1.5x what will be asked so the interview can adapt. [] if it fails."""
    brief = profile_brief(resume, jd)
    if len(brief) < 40:
        return []
    want = max(count, 8) + 4
    jobs = {k: max(2, round(want * share)) for k, share in SPLIT.items()}

    def run(kind: str) -> list[dict]:
        try:
            return _call(brief, kind, jobs[kind])
        except Exception as exc:  # no key, timeout, bad JSON
            log.warning("Interview plan (%s) failed: %s", kind, exc)
            return []

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, jobs))
    plan, seen = [], set()
    for group in results:
        for q in group:
            if _norm(q["question"]) not in seen:
                seen.add(_norm(q["question"]))
                plan.append(q)
    return plan


def pick(interview: dict, target: str, prefer: str | None = None) -> dict | None:
    """Next unused plan question: closest to the target level, preferring `prefer` (a plan_kind) and a new subtopic."""
    plan = interview.get("plan") or []
    asked = {q["question"] for q in interview["selected_questions"]}
    used_sub = {q.get("subtopic") for q in interview["selected_questions"]}
    ti = LEVELS.index(target) if target in LEVELS else 1
    pool = [q for q in plan if q["question"] not in asked]
    if not pool:
        return None
    best = min(pool, key=lambda q: (0 if not prefer or q["plan_kind"] == prefer else 1,   # the kind asked for first
                                    abs(LEVELS.index(q["difficulty"]) - ti),               # then the right difficulty
                                    1 if q["subtopic"] in used_sub else 0))                # then a fresh subtopic
    return {"id": f"q{len(interview['selected_questions']) + 1}", "bank_id": None, "kind": "main",
            "question": best["question"], "topic": best["topic"], "subtopic": best["subtopic"],
            "difficulty": BANK_TO_API[best["difficulty"]], "expected_concepts": best["expected_concepts"],
            "key_points": best["key_points"], "plan_kind": best["plan_kind"]}