"""
Generate a starter question bank for ANY field, in the format app/rag/ingestion.py loads.

Place at: scripts/generate_field_bank.py   (next to your existing generate_question_bank.py, which stays as it is;
this one adds any role or field, and also writes a reference_answer with key points for scoring)
Install:  pip install openai python-dotenv
Env:      OPENAI_API_KEY   (optional: GENERATION_MODEL, default gpt-4o-mini)

Run:
  python scripts/generate_field_bank.py --dry-run                       # shows the plan, no API calls
  python scripts/generate_field_bank.py --roles "Sales Executive,HR Recruiter" --subtopics 6
  python scripts/generate_field_bank.py                                  # all default roles
  python app/rag/ingestion.py --path data/generated_bank.jsonl              # embed + load into MongoDB

For each role the model first lists the skill areas that matter, then writes questions for each area at three
difficulty levels, each with expected concepts and a reference answer (key points) so answers can be scored.

Questions are written to be SPOKEN: the interview is audio only, so no code to write, no tables, short wording.

Everything is written with source="llm_generated". By default review_status is "pending" and ingestion.py skips it;
approve a role after you (or someone from that field) have read it, or use --auto-approve to load it straight away
and review later. Re-running skips role + skill areas that are already in the output file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MODEL = os.getenv("GENERATION_MODEL", "gpt-4o-mini")
LEVELS = ("basic", "intermediate", "advanced")

DEFAULT_ROLES = [
    "Software Engineer", "Data Analyst", "Data Scientist", "DevOps Engineer", "QA Engineer",
    "Product Manager", "UI/UX Designer", "Digital Marketing Specialist", "Sales Executive",
    "Customer Support Executive", "HR Recruiter", "Accountant", "Financial Analyst",
    "Operations Manager", "Business Analyst", "Content Writer", "Project Manager",
    "Mechanical Engineer", "Civil Engineer", "Teacher",
]

SYSTEM = "You write interview question banks. Reply with one JSON object only."

SKILL_AREAS_PROMPT = """List the {n} most important skill areas an interviewer should cover for the role "{role}".
Cover a spread: core knowledge of the field, practical day-to-day work, tools commonly used, and working with people.
Return JSON: {{"topic": "<short field name, 1-3 words>", "areas": [{{"name": "<skill area, 1-4 words>",
"skills": ["<3-6 keywords a candidate would write on a resume for this area>"]}}]}}"""

QUESTIONS_PROMPT = """Write interview questions for the role "{role}", skill area "{area}" (field: {topic}).
Write exactly {per_level} questions at EACH of three levels: basic, intermediate, advanced (so {total} in all).

Rules:
- The interview is spoken aloud, so every question must be answerable by speaking: no code to write, no tables, no
  diagrams, no "see the following". Keep each question under 40 words and make it sound natural.
- Mix kinds: explaining a concept, a realistic work scenario, what they would do and why. For people-facing or
  non-technical roles lean on scenarios and "tell me about a time" questions with real domain substance.
- basic = fundamentals for someone new; intermediate = real working experience; advanced = judgment, trade-offs,
  edge cases, leading others.
- No two questions may test the same thing.
- expected_concepts: 3-5 short phrases (1-4 words) naming what a good answer touches.
- reference_answer.summary: 2-3 sentences. reference_answer.key_points: 3-5 specific, checkable points.
- follow_up_topics: 1-3 short phrases for digging deeper.
- evaluation_criteria: 2-4 checkable statements about the answer, each naming one of the expected concepts
  (e.g. "Gives a realistic example of handling a price objection"). Never vague traits like "critical thinking".
- Make expected_concepts concrete (named techniques, tools, metrics, steps), not "importance of X".

Return JSON: {{"questions": [{{"difficulty": "basic|intermediate|advanced", "question": "...",
"expected_concepts": ["..."], "reference_answer": {{"summary": "...", "key_points": ["..."]}},
"follow_up_topics": ["..."], "evaluation_criteria": ["..."]}}]}}"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def chat_json(client, prompt: str) -> dict:
    last = None
    for _ in range(2):
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.7, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
        try:
            return json.loads(resp.choices[0].message.content)
        except json.JSONDecodeError as exc:
            last = exc
    raise ValueError(f"Model did not return valid JSON: {last}")


def _strings(value, lo: int, hi: int, maxlen: int = 120) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out = [" ".join(v.split()) for v in value if isinstance(v, str) and v.strip()]
    out = [v[:maxlen] for v in out][:hi]
    return out if len(out) >= lo else None


def clean_question(raw: dict) -> dict | None:
    """Keep only well-formed questions. Anything else is dropped rather than repaired."""
    if not isinstance(raw, dict):
        return None
    q = " ".join(str(raw.get("question", "")).split())
    level = str(raw.get("difficulty", "")).lower()
    ref = raw.get("reference_answer") if isinstance(raw.get("reference_answer"), dict) else {}
    concepts = _strings(raw.get("expected_concepts"), 2, 5, 60)
    points = _strings(ref.get("key_points"), 3, 5, 200)
    if level not in LEVELS or not (15 <= len(q) <= 400) or not concepts or not points:
        return None
    return {"question": q, "difficulty": level, "expected_concepts": concepts,
            "reference_answer": {"summary": " ".join(str(ref.get("summary", "")).split())[:600], "key_points": points},
            "follow_up_topics": _strings(raw.get("follow_up_topics"), 0, 3, 60) or [],
            "evaluation_criteria": _strings(raw.get("evaluation_criteria"), 2, 4, 160) or []}


def plan_role(client, role: str, n_areas: int) -> tuple[str, list[dict]]:
    data = chat_json(client, SKILL_AREAS_PROMPT.format(role=role, n=n_areas))
    topic = " ".join(str(data.get("topic") or role).split())[:40]
    areas = []
    for a in data.get("areas", []):
        if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"].strip():
            skills = _strings(a.get("skills"), 0, 6, 40) or []
            areas.append({"name": " ".join(a["name"].split())[:50], "skills": skills})
    return topic, areas[:n_areas]


def write_area(client, role: str, topic: str, area: dict, per_level: int) -> list[dict]:
    data = chat_json(client, QUESTIONS_PROMPT.format(role=role, area=area["name"], topic=topic,
                                                    per_level=per_level, total=per_level * 3))
    rows, seen = [], set()
    for raw in data.get("questions", []):
        q = clean_question(raw)
        if not q or norm(q["question"]) in seen:
            continue
        seen.add(norm(q["question"]))
        n = sum(1 for r in rows if r["difficulty"] == q["difficulty"]) + 1
        rows.append({
            "id": f"gen-{slug(role)}-{slug(area['name'])}-{q['difficulty'][:3]}-{n}",
            "topic": topic, "subtopic": area["name"], "difficulty": q["difficulty"],
            "question": q["question"],
            # What resumes say matters for the engine's field matching: area name, role and resume keywords.
            "skills": list(dict.fromkeys([area["name"], *area["skills"], role])),
            "expected_concepts": q["expected_concepts"], "follow_up_topics": q["follow_up_topics"],
            "evaluation_criteria": q["evaluation_criteria"], "reference_answer": q["reference_answer"], "source": "llm_generated",
        })
    return rows


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", help="comma-separated roles; default is the built-in list of 20")
    ap.add_argument("--subtopics", type=int, default=8, help="skill areas per role (default 8)")
    ap.add_argument("--per-level", type=int, default=2, help="questions per difficulty per area (default 2)")
    ap.add_argument("--out", type=Path, default=Path("data/generated_bank.jsonl"))
    ap.add_argument("--auto-approve", action="store_true", help="mark new questions approved so ingestion loads them")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    roles = [r.strip() for r in args.roles.split(",") if r.strip()] if args.roles else DEFAULT_ROLES
    calls = len(roles) * (1 + args.subtopics)
    print(f"{len(roles)} roles x {args.subtopics} skill areas x {args.per_level * 3} questions "
          f"= about {len(roles) * args.subtopics * args.per_level * 3} questions, {calls} API calls ({MODEL}).")
    if args.dry_run:
        print("Roles:", ", ".join(roles))
        return

    from openai import OpenAI
    client = OpenAI()
    existing = load_existing(args.out)
    done = {(r["topic"], r["subtopic"]) for r in existing}
    seen_text = {norm(r["question"]) for r in existing}
    status = "approved" if args.auto_approve else "pending"
    args.out.parent.mkdir(parents=True, exist_ok=True)

    for role in roles:
        try:
            topic, areas = plan_role(client, role, args.subtopics)
        except Exception as exc:
            print(f"[{role}] could not plan skill areas: {exc}")
            continue
        todo = [a for a in areas if (topic, a["name"]) not in done]
        print(f"[{role}] {topic}: {len(areas)} areas, {len(todo)} to write")

        def job(area):
            try:
                return area, write_area(client, role, topic, area, args.per_level)
            except Exception as exc:
                print(f"  ! {area['name']}: {exc}")
                return area, []

        with ThreadPoolExecutor(max_workers=args.workers) as pool, args.out.open("a", encoding="utf-8") as out:
            for area, rows in pool.map(job, todo):
                fresh = [r for r in rows if norm(r["question"]) not in seen_text]
                for r in fresh:
                    seen_text.add(norm(r["question"]))
                    out.write(json.dumps({**r, "review_status": status}, ensure_ascii=False) + "\n")
                out.flush()
                if fresh:
                    done.add((topic, area["name"]))
                print(f"  {area['name']}: {len(fresh)} questions")
    print(f"Done. Output: {args.out}  (review_status={status}).")


if __name__ == "__main__":
    main()