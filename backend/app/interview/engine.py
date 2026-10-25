"""Answer-driven adaptive question selection (architecture document, sections 5, 6, 11, 12, 13).

Place at: app/interview/engine.py   (replaces the previous version)

After every answer the engine does this:

  1. ANALYZE      the evaluator has already produced score, covered / missing / mentioned concepts.
  2. BUILD QUERY  what the candidate SAID decides what we search for:
                    strong answer  -> dig deeper into the things they mentioned
                    medium answer  -> mix of what they mentioned and what they missed
                    weak answer    -> probe the gaps (after one clarifying follow-up)
                  plus a second query from the JD / resume skills so the interview stays on target.
  3. RETRIEVE     vector search for both queries (no difficulty filter, ranking handles difficulty).
  4. FILTER       drop already-asked questions and semantically near-identical ones.
  5. RERANK       weighted score: semantic 35%, skill 25%, difficulty fit 15%, weak-topic 15%,
                  conversation context 10%, minus small penalties for repeating a subtopic and for
                  re-asking concepts the candidate has already shown they know.
  6. SELECT       best candidate at the target difficulty (or within one level if too few exist), with a
                  human-sounding lead-in ("You mentioned FAISS, so let's go deeper."). The first question
                  is a warm-up, one level easier than requested.
  7. UPDATE STATE asked ids, level, weak and covered topics, history.

Each selected question stores a "selection" trace (intent, queries, scores, runners-up) so you can see
why it was chosen. It is never sent to the candidate.
"""
from __future__ import annotations

import logging
import math
import os
import re
from functools import lru_cache

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backend.app.interview.evaluator import generate_follow_up

log = logging.getLogger(__name__)

LEVELS = ["basic", "intermediate", "advanced"]
API_TO_BANK = {"foundational": "basic", "basic": "basic", "intermediate": "intermediate", "advanced": "advanced"}
BANK_TO_API = {"basic": "foundational", "intermediate": "intermediate", "advanced": "advanced"}

# Ranking weights from section 13 of the architecture document. Tune these on real interviews.
WEIGHTS = {"semantic": 0.35, "skill": 0.25, "difficulty": 0.15, "weak": 0.15, "context": 0.10}
REPEAT_PENALTY = 0.12            # subtracted per earlier question in the same subtopic (coverage goal)
REDUNDANCY_PENALTY = 0.15        # subtracted when the question tests concepts the candidate already covered
SEMANTIC_SPAN_FLOOR = 0.15       # cosine scores bunch together; differences below this are mostly noise
SEMANTIC_DUP_THRESHOLD = float(os.getenv("SEMANTIC_DUP_THRESHOLD", "0.90"))  # cosine; calibrate on your bank
CANDIDATES_PER_QUERY = 15
MAX_FOLLOW_UPS = 2
AVOID_PENALTY = 0.35             # after a failed follow-up, steer away from that subtopic ("let's move on")
# One-word hooks like "LLM" or "model" match half the bank and must not steer the interview.
GENERIC = frozenset("""llm llms rag model models embedding embeddings vector vectors retrieval search system systems
data api apis database databases""".split())
# Skills that appear on almost every resume. They must never be the reason a question is "on target": otherwise a
# software resume that lists "Communication" would be matched to an HR bank question about "Communication Skills".
SOFT = frozenset("""communication communications teamwork team collaboration leadership management time skills skill
interpersonal organizational organisational adaptability multitasking planning problem solving professional
general""".split())
GENERIC = GENERIC | SOFT
HOOK_MIN_COVERAGE = 0.6          # a lead-in may only say "you mentioned X" if X clearly relates to the question
MIN_AT_LEVEL = 3                 # if this many candidates exist at the target level, only consider those
WARM_UP_OPENING = os.getenv("WARM_UP_OPENING", "1") != "0"   # first question one level easier than requested
# The bank only covers some fields. Vector search ALWAYS returns the nearest questions, even for a marketing resume,
# so a candidate is only given a bank question when it clearly matches their skills or what they just said.
# Otherwise select() returns None and the caller writes a question from the resume instead. Set to 0 to disable.
# The MongoDB question bank is switched OFF by default: every question is written from the candidate's own resume.
# Set USE_QUESTION_BANK=1 to bring the bank back for candidates whose field it covers.
USE_BANK = os.getenv("USE_QUESTION_BANK", "0") == "1"
REQUIRE_FIELD_MATCH = os.getenv("REQUIRE_FIELD_MATCH", "1") != "0"

_STOP = frozenset("""the and for with how what why when your you that this are from into use using can would
should does not but their they them have has was were will which about between than then also any all out one
two""".split())


# --------------------------------------------------------------------------- bank access
@lru_cache(maxsize=1)
def _db():
    from pymongo import MongoClient

    client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=3000)
    return client[os.getenv("MONGODB_DB", "interview_platform")]


def bank_available() -> bool:
    """True when MongoDB and OpenAI are configured and the bank contains questions."""
    if not USE_BANK or not (os.getenv("MONGODB_URI") and os.getenv("OPENAI_API_KEY")):
        return False
    try:
        from backend.app.rag.ingestion import COLLECTION

        return _db()[COLLECTION].estimated_document_count() > 0
    except Exception as exc:
        log.warning("Question bank unavailable: %s", exc)
        return False


def _asked_vectors(ids: list[str]) -> dict[str, list[float]]:
    if not ids:
        return {}
    try:
        from backend.app.rag.ingestion import COLLECTION

        docs = _db()[COLLECTION].find({"_id": {"$in": ids}}, {"embedding": 1})
        return {d["_id"]: d["embedding"] for d in docs if d.get("embedding")}
    except Exception as exc:
        log.warning("Could not load vectors for duplicate filtering: %s", exc)
        return {}


# --------------------------------------------------------------------------- text helpers
def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOP}


def _specific(label: str) -> set[str]:
    return {t for t in _terms(label) if t not in GENERIC}


def _coverage(label: str, hit_terms: set[str]) -> float:
    """Share of the label's SPECIFIC words that appear in the candidate question's text (0..1)."""
    lt = _specific(label)
    return len(lt & hit_terms) / len(lt) if lt else 0.0


def _strong_terms(label: str) -> set[str]:
    # Crude stems (first 6 letters) so "recruitment" meets "recruiter" and "analysis" meets "analyst".
    return {t[:6] for t in _terms(label) - SOFT}


def _label_match_strong(a: str, b: str) -> bool:
    """Like _label_match, but ignores everyday skills (communication, teamwork...) so only real subject matter counts."""
    ta, tb = _strong_terms(a), _strong_terms(b)
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def _label_match(a: str, b: str) -> bool:
    ta, tb = _terms(a), _terms(b)
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _level_idx(level: str | None) -> int:
    return LEVELS.index(level) if level in LEVELS else 1


# --------------------------------------------------------------------------- pipeline steps
def _to_question(doc: dict, idx: int) -> dict:
    ref = doc.get("reference_answer") or {}
    return {"id": f"q{idx}", "bank_id": doc["_id"], "kind": "main", "question": doc["question"],
            "topic": doc["topic"], "subtopic": doc["subtopic"],
            "difficulty": BANK_TO_API.get(doc["difficulty"], doc["difficulty"]),
            "expected_concepts": doc.get("expected_concepts", []),
            "key_points": ref.get("key_points", [])}


def target_level(level: str, score: int, kind: str) -> str:
    """Section 11: weak answer -> easier, strong answer -> harder, otherwise stay."""
    if kind == "follow_up":
        delta = -1 if score <= 2 else 0
    else:
        delta = 1 if score >= 4 else (-1 if score <= 2 else 0)
    return LEVELS[max(0, min(len(LEVELS) - 1, _level_idx(level) + delta))]


def _focus(st: dict) -> str:
    return " ".join(st["skills"][:6]) or "software engineering fundamentals"


def _build_queries(st: dict, evaluation: dict | None, answered: dict | None) -> tuple[str, list[str]]:
    focus = _focus(st)
    if not evaluation or not answered:
        # Opening: one query per pair of skills, so a candidate with several different skills is not matched
        # against one blurry blend of them all.
        pairs = [" ".join(st["skills"][i:i + 2]) for i in range(0, min(len(st["skills"]), 6), 2)]
        return "opening", [p for p in pairs if p] or [focus]
    score = int(evaluation.get("score", 3))
    mentioned = evaluation.get("mentioned_concepts", [])
    missing = evaluation.get("missing_concepts", [])
    if score >= 4:
        intent, hooks = "dig deeper", mentioned[:4]
    elif score == 3:
        intent, hooks = "balance", mentioned[:2] + missing[:2]
    else:
        intent, hooks = "probe gaps", missing[:3] or mentioned[:2]
    hooks = [h for h in hooks if _specific(h)]
    queries = []
    if hooks:
        queries.append(f"{answered.get('topic') or ''} {' '.join(hooks)}".strip())
    queries.append(focus)
    return intent, queries


def _retrieve(queries: list[str], asked: list[str]) -> dict[str, dict]:
    from backend.app.rag.ingestion import search_questions

    pool: dict[str, dict] = {}
    for q in queries:
        for hit in search_questions(_db(), q, k=CANDIDATES_PER_QUERY, exclude_ids=asked, with_vectors=True):
            best = pool.get(hit["_id"])
            if best is None or hit.get("score", 0) > best.get("score", 0):
                pool[hit["_id"]] = hit
    return pool


def _drop_semantic_duplicates(pool: dict[str, dict], asked: list[str]) -> dict[str, dict]:
    vectors = _asked_vectors(asked)
    if not vectors:
        return pool
    kept = {hid: h for hid, h in pool.items()
            if not (h.get("embedding") and any(_cos(h["embedding"], v) >= SEMANTIC_DUP_THRESHOLD
                                               for v in vectors.values()))}
    return kept or pool  # never run out of questions just because of the duplicate filter


def _rank(pool: dict[str, dict], st: dict, target: str, profile: list[str],
          mentioned: list[str], weak: list[str], covered: list[str], avoid: str | None = None) -> list[dict]:
    hits = list(pool.values())
    scores = [h.get("score", 0.0) for h in hits]
    lo, hi = min(scores), max(scores)
    span = max(hi - lo, SEMANTIC_SPAN_FLOOR)
    ti = _level_idx(target)
    ranked = []
    for h in hits:
        terms = _terms(" ".join([h["question"], h["subtopic"], h["topic"],
                                 *h.get("expected_concepts", []), *h.get("skills", [])]))
        labels = [*h.get("skills", []), h["subtopic"], h["topic"]]
        matches = sum(1 for lab in labels if any(_label_match(lab, p) for p in profile))
        field_hits = sum(1 for lab in labels if any(_label_match_strong(lab, p) for p in profile))
        gap = abs(_level_idx(h.get("difficulty")) - ti)
        comps = {
            "semantic": 1.0 if hi == lo else (h.get("score", 0.0) - lo) / span,
            "skill": min(1.0, matches / 2),
            "difficulty": {0: 1.0, 1: 0.5}.get(gap, 0.0),
            "weak": max((_coverage(w, terms) for w in weak), default=0.0),
            "context": max((_coverage(m, terms) for m in mentioned), default=0.0),
        }
        field_ok = float(field_hits)
        concepts = h.get("expected_concepts", [])
        redundant = (sum(1 for c in concepts if any(_label_match(c, cv) for cv in covered)) / len(concepts)
                     if concepts else 0.0)
        total = sum(WEIGHTS[k] * v for k, v in comps.items()) \
            - REPEAT_PENALTY * st["subtopics"].get(h["subtopic"], 0) \
            - REDUNDANCY_PENALTY * redundant \
            - (AVOID_PENALTY if avoid and h["subtopic"] == avoid else 0.0)
        ranked.append({"hit": h, "total": round(total, 4), "gap": gap,
                       "components": {**{k: round(v, 3) for k, v in comps.items()},
                                      "redundant": round(redundant, 3), "field": field_ok}})
    ranked.sort(key=lambda r: (-r["total"], -r["hit"].get("score", 0.0)))
    return ranked


def _pick_hook(mentioned: list[str], hit: dict) -> str | None:
    terms = _terms(" ".join([hit["question"], hit["subtopic"], *hit.get("expected_concepts", [])]))
    def fit(label: str) -> tuple[float, int]:          # whole-label fit first, then number of specific matches
        lt = _terms(label)
        return (len(lt & terms) / len(lt) if lt else 0.0, len(_specific(label) & terms))

    # A lead-in claims "you mentioned X", so the WHOLE label must fit the question, and at least one
    # specific (non-generic) word must really match.
    best = max((m for m in mentioned if _specific(m) & terms), key=fit, default=None)
    return best if best and fit(best)[0] >= HOOK_MIN_COVERAGE else None


def _lead_in(intent: str, delta: int, hook: str | None) -> str:
    if intent == "opening":
        return "Let's get started."
    if intent == "move on":
        return "No problem. Let's move on to a different area."
    if intent == "probe gaps":
        return "Let's step back to something a little more foundational."
    if intent == "dig deeper":
        if hook:
            return f"Nice. You mentioned {hook}, so let's go a bit deeper."
        return "Good answer. Let's try something more challenging." if delta > 0 else "Good. Let's look at another area."
    return f"You mentioned {hook}. Let's explore that." if hook else "Okay, let's move on to another area."


def _select(interview: dict, evaluation: dict | None, answered: dict | None,
            target: str, delta: int, avoid: str | None = None) -> dict | None:
    if not USE_BANK:
        return None
    st = interview["adaptive_state"]
    intent, queries = _build_queries(st, evaluation, answered)
    if avoid:                                  # failed follow-up: change topic instead of grilling further
        intent, queries = "move on", [_focus(st)]
    asked = [q["bank_id"] for q in interview["selected_questions"] if q.get("bank_id")]
    mentioned = (evaluation or {}).get("mentioned_concepts", [])
    try:
        pool = _retrieve(queries, asked)
        if not pool:
            return None
        pool = _drop_semantic_duplicates(pool, asked)
        ranked = _rank(pool, st, target, st["skills"] + mentioned, mentioned, st["weak"], st["covered"], avoid)
    except Exception as exc:
        log.warning("Adaptive question lookup failed: %s", exc)
        return None

    if REQUIRE_FIELD_MATCH:
        on_target = [r for r in ranked
                     if r["components"]["field"] > 0 or r["components"]["context"] >= HOOK_MIN_COVERAGE]
        if not on_target:
            log.info("Question bank has nothing on target for skills=%s (best total %.3f); using the resume instead",
                     st["skills"][:6], ranked[0]["total"] if ranked else 0.0)
            return None
        ranked = on_target

    # Difficulty is a gate, not just a score: with enough candidates at the target level, stay there
    # (so a strong candidate really reaches advanced questions); otherwise allow one level either side.
    at_level = [r for r in ranked if r["gap"] == 0]
    candidates = at_level if len(at_level) >= MIN_AT_LEVEL else ([r for r in ranked if r["gap"] <= 1] or ranked)
    best = candidates[0]
    hit = best["hit"]
    st["level"] = target
    st["subtopics"][hit["subtopic"]] = st["subtopics"].get(hit["subtopic"], 0) + 1

    question = _to_question(hit, len(interview["selected_questions"]) + 1)
    question["lead_in"] = _lead_in(intent, delta, _pick_hook(mentioned, hit))
    question["selection"] = {
        "intent": intent, "queries": queries, "target_level": target,
        "chosen": {"total": best["total"], **best["components"]},
        "runners_up": [{"bank_id": r["hit"]["_id"], "total": r["total"]} for r in candidates[1:4]],
    }
    return question


# --------------------------------------------------------------------------- public API
def start_session(interview: dict, focus_skills: list[str] | str, start_difficulty: str) -> dict | None:
    """Set up adaptive state on the interview record and return the first question."""
    skills = [focus_skills] if isinstance(focus_skills, str) else list(focus_skills)
    skills = [s.strip() for s in skills if s and s.strip()]
    level = API_TO_BANK.get(start_difficulty, "intermediate")
    interview["adaptive_state"] = {"level": level, "skills": skills, "focus": " ".join(skills),
                                   "subtopics": {}, "follow_ups": 0, "weak": [], "covered": [],
                                   "history": []}
    opening = LEVELS[max(0, _level_idx(level) - 1)] if WARM_UP_OPENING else level
    question = _select(interview, None, None, opening, 0)
    interview["adaptive_state"]["level"] = level     # the first answer moves from the REQUESTED level
    return question


def next_question(interview: dict, evaluation: dict, answered: dict, answer_text: str) -> dict | None:
    st = interview["adaptive_state"]
    score = int(evaluation.get("score", 3))
    missing = evaluation.get("missing_concepts", [])
    kind = answered.get("kind", "main")
    idx = len(interview["selected_questions"]) + 1

    # State update (section 12): weak and covered topics, history.
    if score <= 3:
        for m in missing:
            if m not in st["weak"]:
                st["weak"].append(m)
        st["weak"] = st["weak"][-8:]
    for c in evaluation.get("covered_concepts", []):
        if c not in st["covered"]:
            st["covered"].append(c)
    st["covered"] = st["covered"][-30:]
    st["history"].append({"question_id": answered["id"], "subtopic": answered.get("subtopic"),
                          "level": st["level"], "score": score,
                          "mentioned": evaluation.get("mentioned_concepts", []), "missing": missing})

    # A weak first answer gets one clarifying follow-up before we move on.
    if kind == "main" and score <= 2 and st["follow_ups"] < MAX_FOLLOW_UPS:
        st["follow_ups"] += 1
        return {"id": f"q{idx}", "bank_id": None, "kind": "follow_up", "parent_id": answered["id"],
                "question": generate_follow_up(answered, answer_text, missing),
                "topic": answered.get("topic"), "subtopic": answered.get("subtopic"),
                "difficulty": answered.get("difficulty"),
                "expected_concepts": missing[:3],
                # judged only on what was missed the first time, not on the whole answer key again
                "key_points": evaluation.get("missing_key_points") or answered.get("key_points", [])}

    old_level = st["level"]
    new_level = target_level(old_level, score, kind)
    avoid = answered.get("subtopic") if (kind == "follow_up" and score <= 2) else None
    return _select(interview, evaluation, answered, new_level,
                   _level_idx(new_level) - _level_idx(old_level), avoid)