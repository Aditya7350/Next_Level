"""Spoken, human-sounding reaction to every answer, joined with the bridge to the next question.

Place at: app/interview/reaction.py

After each answer the interviewer says ONE short line before the next question, for example:
  strong:   "That's a clear explanation, and I liked how you tied chunk size to the embedding limit. Let's look at retrieval."
  partial:  "You've got the main idea, though you skipped how you'd measure it. Let's move to something different."
  weak:     "That's not quite it, and that's okay. Let me ask it another way."
  no idea:  "Thanks for being honest about that. Let's try a different area."

One model call writes the line from the question, the candidate's answer, the evaluation and the next question,
so it refers to what the person actually said. It is never allowed to give the answer away or mention a score.
If the call fails or is slow, a scripted line chosen by score is used instead, so the interview never waits on it.

Environment (all optional):
  REACTION_STYLE     honest (default: says plainly when an answer is not right) | neutral (never signals quality;
                     use this for real hiring interviews)
  SPOKEN_REACTIONS   0 turns this off and the engine's own lead-in is used
  REACTION_MODEL     default gpt-4o-mini
  REACTION_TIMEOUT   seconds before falling back to a scripted line (default 6)
"""
from __future__ import annotations

import json
import logging
import os
import random
import re

log = logging.getLogger(__name__)

MODEL = os.getenv("REACTION_MODEL", "gpt-4o-mini")
STYLE = os.getenv("REACTION_STYLE", "honest").lower()
ENABLED = os.getenv("SPOKEN_REACTIONS", "1") != "0"
TIMEOUT = float(os.getenv("REACTION_TIMEOUT", "6"))

DONT_KNOW = re.compile(r"\b(i (do not|don'?t) know|no idea|not sure|can'?t (recall|remember)|skip (this|it)|pass)\b", re.I)

SYSTEM = """You are Aria, a warm, experienced human interviewer speaking aloud in a live interview.
Write what you say right after the candidate finishes an answer, before you ask the next question.

Style: {style_rules}

Always:
- One or two short sentences, at most 35 words. Plain spoken English, contractions are fine. No lists, no emojis.
- React to something SPECIFIC the candidate said, not to the topic in general.
- Never reveal or hint at the correct answer, never mention scores, points, ratings or the answer key.
- Do not ask a question: the next question is asked right after your line.
- Then bridge naturally to what comes next: if the next item is a follow-up, say you'll dig into or rephrase one part;
  if it is a new question, say you'll move to another area (name the area loosely, never read the question).
- Do not begin with the same word as any of your recent lines, and do not reuse their phrasing.
- If the candidate said they don't know, be kind and appreciate the honesty, then move on.
- If the answer was very short or vague, gently say you'd have liked a bit more detail.
Reply with the spoken line only."""

STYLE_RULES = {
    "honest": ("Be genuinely honest, like a good interviewer who is kind. Strong answer: say so and say what was good. "
               "Partly right: credit what was right and say what was missing in general terms. Weak or wrong: say "
               "plainly but gently that it wasn't quite right, without lecturing."),
    "neutral": ("Be warm but NEUTRAL. Never signal whether the answer was good or bad, and never praise or criticise. "
                "Just acknowledge it ('Thanks, that's helpful', 'Got it') and move on. You may mention something "
                "specific they said, without judging it."),
}

SCRIPTED = {
    "strong": ["That's a clear answer, thank you.", "Good, that covers it well.", "Nice, that makes sense."],
    "partial": ["Okay, you've got part of it.", "That's partly there, thanks.", "Fair enough, thanks for that."],
    "weak": ["That's not quite it, and that's okay.", "Not quite, but let's keep going.", "I'd have liked a bit more there."],
    "unknown": ["Thanks for being honest about that.", "That's fine, it happens."],
    "neutral": ["Thanks, that's helpful.", "Got it, thank you.", "Okay, thanks for that."],
}
BRIDGES = {
    "follow_up": ["Let me ask that another way.", "Let me dig into one part of that."],
    "main": ["Let's move to something different.", "Let's look at another area.", "Let's try a different topic."],
}


def _band(score: int, answer: str) -> str:
    if DONT_KNOW.search(answer) and len(answer.split()) <= 14:
        return "unknown"
    return "strong" if score >= 4 else "partial" if score == 3 else "weak"


def scripted(score: int, answer: str, upcoming: dict, recent: list[str]) -> str:
    band = "neutral" if STYLE == "neutral" and _band(score, answer) != "unknown" else _band(score, answer)
    options = [o for o in SCRIPTED[band] if o not in recent] or SCRIPTED[band]
    bridge = random.choice(BRIDGES["follow_up" if upcoming.get("kind") == "follow_up" else "main"])
    return f"{random.choice(options)} {bridge}"


def _clean(text: str) -> str | None:
    text = " ".join(str(text).split()).strip(" \"'“”")
    if not text or len(text) > 320 or re.search(r"\b(score|scored|rating|out of|\d+\s*/\s*\d+)\b", text, re.I):
        return None
    return text


def _ask_model(question: dict, answer: str, evaluation: dict, upcoming: dict, recent: list[str],
               name: str | None) -> str | None:
    from openai import OpenAI

    payload = {
        "question_asked": question.get("question"),
        "candidate_answer": answer[:1800],
        "answer_quality_1_to_5": int(evaluation.get("score", 3)),  # private: for your judgement only
        "covered": evaluation.get("covered_concepts", [])[:5],
        "missing": evaluation.get("missing_concepts", [])[:4],
        "said_they_dont_know": bool(DONT_KNOW.search(answer) and len(answer.split()) <= 14),
        "next_item": {"type": upcoming.get("kind", "main"), "area": upcoming.get("subtopic") or upcoming.get("topic")},
        "your_recent_lines": recent[-3:],
        "candidate_first_name": name,  # use it at most occasionally, and only if it sounds natural
    }
    resp = OpenAI(timeout=TIMEOUT).chat.completions.create(
        model=MODEL, temperature=0.9, max_tokens=90,
        messages=[{"role": "system", "content": SYSTEM.format(style_rules=STYLE_RULES.get(STYLE, STYLE_RULES["honest"]))},
                  {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    return _clean(resp.choices[0].message.content or "")


def transition(interview: dict, question: dict, answer: str, evaluation: dict, upcoming: dict,
               name: str | None = None) -> str | None:
    """The line to speak before `upcoming`. Never raises. None means: keep the engine's own lead-in."""
    if not ENABLED:
        return None
    recent = interview.setdefault("reactions", [])
    first = (name or "").split()[0] if name else None
    use_name = first if first and len(recent) % 4 == 3 else None   # about once every four answers
    line = None
    try:
        line = _ask_model(question, answer, evaluation, upcoming, recent, use_name)
    except Exception as exc:  # no key, timeout, rate limit
        log.info("Spoken reaction fell back to a scripted line: %s", exc)
    if not line:
        line = scripted(int(evaluation.get("score", 3)), answer, upcoming, recent)
    recent.append(line)
    del recent[:-8]
    return line