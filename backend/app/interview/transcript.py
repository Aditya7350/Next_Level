"""Saves each interview's conversation as a readable text file, so it survives a restart and can be reviewed.

Place at: app/interview/transcript.py

One Markdown file per interview, rewritten after every answer (so an unfinished interview is saved too):
  data/transcripts/2026-10-23_priya-nair_ab12cd.md
It holds what Aria said (the reaction and the question, as spoken), what the candidate answered, and, as private
review notes under each turn, the score, what was covered or missing, the question's topic and the strong-answer key points.

These files contain personal data. Keep the folder out of git, tell candidates what is kept and for how long (the consent
text on the setup screen), and delete old ones on a schedule.

Environment (optional): SAVE_TRANSCRIPTS=0 turns it off; TRANSCRIPT_DIR changes the folder (default data/transcripts).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)
ENABLED = os.getenv("SAVE_TRANSCRIPTS", "1") != "0"
FOLDER = Path(os.getenv("TRANSCRIPT_DIR", "data/transcripts"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:30] or "candidate"


def render(interview: dict, user: dict, report: dict | None = None) -> str:
    answers = {a["question_id"]: a for a in interview.get("answers", [])}
    out = [f"# Interview: {user.get('name') or 'Candidate'}", "",
           f"- Interview id: {interview['id']}",
           f"- Started: {interview.get('started_at') or interview.get('created_at')}",
           f"- Status: {interview.get('status')}",
           f"- Questions: {len(interview.get('answers', []))} answered of {interview.get('question_count')}", ""]

    intro = interview.get("intro") or {}
    if intro:
        out += ["## Introduction", "", f"**Aria:** {intro.get('greeting') or '(greeting and introduction question)'}", "",
                f"**Candidate:** {intro.get('answer', '')}", ""]

    for n, q in enumerate(interview.get("selected_questions", []), 1):
        spoken = " ".join(x for x in (q.get("lead_in"), q.get("question")) if x)
        out += [f"## {n}. {q.get('subtopic') or q.get('topic') or 'Question'}", "", f"**Aria:** {spoken}", ""]
        a = answers.get(q["id"])
        if not a:
            out += ["_(no answer yet)_", ""]
            continue
        ev = a.get("evaluation", {})
        out += [f"**Candidate:** {a['answer']}", "",
                f"> Review notes: score {ev.get('score')}/5 | {q.get('kind', 'main')} | {q.get('difficulty')} | "
                f"{q.get('plan_kind') or 'bank/other'}",
                f"> Covered: {', '.join(ev.get('covered_concepts', [])) or '-'} | "
                f"Missing: {', '.join(ev.get('missing_concepts', [])) or '-'}"]
        if ev.get("feedback"):
            out.append(f"> Feedback: {ev['feedback']}")
        if q.get("key_points"):
            out.append(f"> Strong answer would include: {'; '.join(q['key_points'])}")
        out.append("")

    if report:
        out += ["## Result", "", f"- Overall score: {report.get('score')}/5",
                f"- Strengths: {', '.join(report.get('strengths', [])) or '-'}",
                f"- To improve: {', '.join(report.get('improvement_areas', [])) or '-'}", ""]
    return "\n".join(out)


def save(interview: dict, user: dict, report: dict | None = None) -> None:
    """Never raises: a problem writing the file must not interrupt the interview."""
    if not ENABLED:
        return
    try:
        FOLDER.mkdir(parents=True, exist_ok=True)
        name = interview.get("transcript_file")
        if not name:
            day = (interview.get("started_at") or interview.get("created_at") or "")[:10]
            name = f"{day}_{_slug(user.get('name'))}_{interview['id'][:6]}.md"
            interview["transcript_file"] = name
        (FOLDER / name).write_text(render(interview, user, report), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not save the transcript: %s", exc)