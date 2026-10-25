"""Interview lifecycle, question delivery, and answer evaluation."""
import os
import secrets
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.ai.question_generation import generate_resume_questions
from backend.app.api.dependencies import current_user
from backend.app.interview.engine import bank_available, start_session
from backend.app.interview.engine import next_question as adaptive_next
from backend.app.interview.evaluator import evaluate_answer, keyword_evaluate
from backend.app.interview.planner import build_plan
from backend.app.interview.planner import pick as plan_pick
from backend.app.interview.reaction import transition
from backend.app.interview.transcript import save as save_transcript
from backend.app.services.store import INTERVIEWS, JDS, REPORTS, RESUMES

router = APIRouter(prefix="/interview", tags=["interviews"])
QUESTION_BANK = [
    ("Explain how a retrieval-augmented generation system works.", "RAG", "intermediate", ["retrieval", "generation", "grounding"]),
    ("How do you choose chunk size and overlap for a document retrieval pipeline?", "RAG", "intermediate", ["chunking", "context", "evaluation"]),
    ("Why add a reranker after vector search, and how would you evaluate it?", "RAG", "advanced", ["reranking", "ndcg", "recall"]),
    ("How would you prevent hallucinations in an LLM application?", "LLM", "advanced", ["grounding", "citations", "evaluation"]),
    ("Describe a project you built and the tradeoffs you made.", "projects", "foundational", ["ownership", "tradeoffs", "impact"]),
    ("How would you design a reliable API service that handles growing traffic?", "system design", "advanced", ["scaling", "availability", "observability"]),
    ("How do you test and deploy a Python web service?", "Python", "intermediate", ["testing", "deployment", "monitoring"]),
    ("Tell me about a time you received difficult feedback.", "behavioral", "foundational", ["reflection", "action", "outcome"]),
]
# Adaptive questions carry the answer key; never send these fields to the candidate.
_HIDDEN_FROM_CANDIDATE = {"key_points", "bank_id", "expected_concepts", "selection", "plan_kind"}
SITUATION_SLOTS = {10, 15}            # question numbers reserved for a scenario question
PROJECT_SLOTS = {2, 5, 8, 11, 14}     # question numbers reserved for the candidate's own projects and experience


class CreateInterview(BaseModel):
    interview_type: str = Field(default="technical", max_length=40)
    resume_id: str | None = None
    jd_id: str | None = None
    difficulty: str = Field(default="intermediate", pattern="^(foundational|intermediate|advanced)$")
    question_count: int = Field(default=5, ge=1, le=20)
    # Opt-in: pick questions one at a time from the MongoDB bank and score with the LLM judge.
    adaptive: bool = False


class IntroRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)
    greeting: str = Field(default="", max_length=1000)      # what Aria said, so the saved conversation is complete


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)


def _owned(interview_id: str, user_id: str) -> dict:
    interview = INTERVIEWS.get(interview_id)
    if interview is None or interview["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


def _question(interview: dict) -> dict | None:
    idx = interview["current_index"]
    if idx >= len(interview["selected_questions"]):
        return None
    return interview["selected_questions"][idx]


def _public(question: dict | None) -> dict | None:
    """Strip the answer key from adaptive questions before returning them to the client."""
    if question is None or "key_points" not in question:
        return question
    hidden = set(_HIDDEN_FROM_CANDIDATE)
    if os.getenv("INTERVIEW_DEBUG") == "1":      # local debugging only: shows why a question was chosen
        hidden.discard("selection")
    return {k: v for k, v in question.items() if k not in hidden}


def _public_eval(evaluation: dict) -> dict:
    """The per-point judge detail is for developers; candidates only get score, concepts and feedback."""
    if os.getenv("INTERVIEW_DEBUG") == "1":
        return evaluation
    return {k: v for k, v in evaluation.items() if k not in {"points", "rescued_points", "missing_key_points"}}


def _static_questions(payload: CreateInterview, jd_skills: list[str]) -> list:
    questions = generate_resume_questions(
        RESUMES[payload.resume_id],
        payload.interview_type,
        payload.difficulty,
        payload.question_count,
    ) if payload.resume_id else []
    if not questions:
        questions = list(QUESTION_BANK)
    if jd_skills:
        questions.sort(key=lambda q: 0 if any(s.lower() in (q[1] + " " + q[0]).lower() for s in jd_skills) else 1)
    return questions


def _static_fallback(interview: dict) -> dict | None:
    """Next unused question from the built-in list, used if the adaptive bank is unreachable."""
    asked = {q["question"] for q in interview["selected_questions"]}
    for text, topic, difficulty, concepts in QUESTION_BANK:
        if text not in asked:
            return {"id": f"q{len(interview['selected_questions']) + 1}", "bank_id": None, "kind": "main",
                    "question": text, "topic": topic, "subtopic": topic, "difficulty": difficulty,
                    "expected_concepts": concepts, "key_points": []}
    return None


def _resume_question(interview: dict) -> dict | None:
    """A question written from THIS candidate's resume, for when the MongoDB bank has nothing for their field.
    The list is generated once per interview and kept on the record; each call hands out the next unused one."""
    resume = RESUMES.get(interview.get("resume_id") or "")
    if not resume:
        return None
    if "resume_questions" not in interview:
        try:
            jd = JDS.get(interview.get("jd_id") or "", {})
            role = jd.get("title") or jd.get("role") or jd.get("role_title") or "this role"
            interview["resume_questions"] = [list(q) for q in generate_resume_questions(
                resume, role, interview["difficulty"], interview["question_count"] + 2)]
        except Exception:
            interview["resume_questions"] = []
    asked = {q["question"] for q in interview["selected_questions"]}
    for text, topic, difficulty, concepts in interview["resume_questions"]:
        if text not in asked:
            return {"id": f"q{len(interview['selected_questions']) + 1}", "bank_id": None, "kind": "main",
                    "question": text, "topic": topic, "subtopic": topic, "difficulty": difficulty,
                    "expected_concepts": concepts, "key_points": []}
    return None


def _resume_skills(resume: dict) -> list[str]:
    """The parser keeps skills inside resume["profile"]; older records may have them at the top level."""
    profile = resume.get("profile") if isinstance(resume.get("profile"), dict) else {}
    skills = profile.get("skills") or resume.get("skills") or []
    return [s for s in skills if isinstance(s, str) and s.strip()]


def _skills_for(resume_skills: list[str], jd_skills: list[str]) -> list[str]:
    """Skills to steer the interview. The candidate's own skills come first (skills the job also asks for lead),
    then the rest of the job's skills. Before, a job description replaced the resume completely."""
    jd_l = {s.lower() for s in jd_skills}
    both = [s for s in resume_skills if s.lower() in jd_l]
    rest = [s for s in resume_skills if s.lower() not in jd_l] + [s for s in jd_skills if s not in both]
    seen, out = set(), []
    for s in both + rest:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:10]


def _choose_next(interview: dict, evaluation: dict, answered: dict, answer: str) -> dict | None:
    """Follow-up on a weak answer, else the next question: the candidate's own projects in the reserved slots,
    otherwise a bank question when one clearly fits their field, otherwise the next question from their plan."""
    number = len(interview["selected_questions"]) + 1
    chosen = adaptive_next(interview, evaluation, answered, answer)        # a follow-up, or a bank question
    if chosen and chosen.get("kind") == "follow_up":
        return chosen
    level = (interview.get("adaptive_state") or {}).get("level", "intermediate")
    if number in PROJECT_SLOTS:
        chosen = plan_pick(interview, level, "projects") or chosen
    elif number in SITUATION_SLOTS:
        chosen = plan_pick(interview, level, "situational") or chosen
    else:
        chosen = chosen or plan_pick(interview, level, "domain")
    return chosen or plan_pick(interview, level) or _resume_question(interview) or _static_fallback(interview)


def _report(interview: dict) -> dict:
    answers = interview["answers"]
    qmap = {q["id"]: q for q in interview["selected_questions"]}
    scores = [a["evaluation"]["score"] for a in answers]
    score = round(sum(scores) / len(scores), 1) if scores else 0

    by_area = defaultdict(list)
    for a in answers:
        q = qmap.get(a["question_id"], {})
        by_area[q.get("subtopic") or q.get("topic") or "general"].append(a["evaluation"]["score"])
    area_scores = {area: round(sum(v) / len(v), 1) for area, v in by_area.items()}
    weakest = sorted(area_scores.items(), key=lambda kv: kv[1])[:3]
    recommendations = [f"Review {area} (average {avg}/5)." for area, avg in weakest if avg < 4] \
        or ["Practice explaining your reasoning with specific examples."]
    # For practice: show what a strong answer contains on the questions that scored 3 or lower.
    review = [{"question": a["question"], "score": a["evaluation"]["score"],
               "missing": a["evaluation"]["missing_concepts"],
               "key_points": qmap.get(a["question_id"], {}).get("key_points", [])}
              for a in answers if a["evaluation"]["score"] <= 3 and a.get("kind", "main") == "main"][:6]

    return {"id": secrets.token_urlsafe(16), "interview_id": interview["id"], "user_id": interview["user_id"],
            "score": score, "strengths": sorted({c for a in answers for c in a["evaluation"]["covered_concepts"]}),
            "improvement_areas": sorted({c for a in answers for c in a["evaluation"]["missing_concepts"]}),
            "area_scores": area_scores, "review": review,
            "recommendations": recommendations,
            "completed_at": datetime.now(UTC).isoformat()}


@router.post("/create", status_code=201)
def create_interview(payload: CreateInterview, user: dict = Depends(current_user)) -> dict:
    if payload.resume_id and (payload.resume_id not in RESUMES or RESUMES[payload.resume_id]["user_id"] != user["id"]):
        raise HTTPException(status_code=404, detail="Resume not found")
    if payload.jd_id and (payload.jd_id not in JDS or JDS[payload.jd_id]["user_id"] != user["id"]):
        raise HTTPException(status_code=404, detail="Job description not found")
    jd_skills = JDS.get(payload.jd_id or "", {}).get("required_skills", [])
    interview_id = secrets.token_urlsafe(16)
    record = {"id": interview_id, "user_id": user["id"], "interview_type": payload.interview_type,
              "difficulty": payload.difficulty, "status": "draft", "resume_id": payload.resume_id,
              "jd_id": payload.jd_id, "question_count": payload.question_count, "adaptive": False,
              "selected_questions": [], "current_index": 0, "answers": [], "asked_question_ids": [],
              "started_at": None, "created_at": datetime.now(UTC).isoformat()}

    if payload.resume_id:
        profile = RESUMES[payload.resume_id].get("profile") or {}
        if profile.get("extraction_warnings"):          # fewer than 40 characters were read from the file
            raise HTTPException(status_code=422, detail="We couldn't read any text in that file. Please upload a text-based "
                                "PDF or DOCX (not a scan or photo), or a TXT file.")
    plan = []
    if payload.adaptive and payload.resume_id:
        # Questions written from THIS resume (any field). The bank is a bonus when it matches the candidate's field.
        plan = build_plan(RESUMES[payload.resume_id], JDS.get(payload.jd_id or ""), payload.question_count)
        record["plan"] = plan

    if payload.adaptive and (bank_available() or plan):
        resume_skills = _resume_skills(RESUMES[payload.resume_id]) if payload.resume_id else []
        focus = _skills_for(list(resume_skills), list(jd_skills))   # empty is fine: the engine has a default
        bank_first = start_session(record, focus, payload.difficulty)   # also sets up the adaptive state
        first = (plan_pick(record, "basic", "projects") if plan else None) or bank_first or _resume_question(record)
        if first:
            record["adaptive"] = True
            record["selected_questions"] = [first]
        else:
            record.pop("adaptive_state", None)

    if not record["adaptive"]:
        questions = _static_questions(payload, jd_skills)
        count = min(payload.question_count, len(questions))
        record["question_count"] = count
        record["selected_questions"] = [
            {"id": f"q{i+1}", "question": q[0], "topic": q[1], "difficulty": q[2], "expected_concepts": q[3]}
            for i, q in enumerate(questions[:count])]

    INTERVIEWS[interview_id] = record
    return {k: v for k, v in record.items() if k not in {"selected_questions", "answers", "adaptive_state", "resume_questions", "plan"}}


@router.post("/{interview_id}/start")
def start_interview(interview_id: str, user: dict = Depends(current_user)) -> dict:
    interview = _owned(interview_id, user["id"])
    if interview["status"] == "completed":
        raise HTTPException(status_code=409, detail="Interview is already complete")
    interview["status"] = "in_progress"
    interview["started_at"] = interview["started_at"] or datetime.now(UTC).isoformat()
    question = _question(interview)
    if question and question["id"] not in interview["asked_question_ids"]:
        interview["asked_question_ids"].append(question["id"])
    return {"interview_id": interview_id, "status": interview["status"], "question": _public(question)}


@router.post("/{interview_id}/intro")
def submit_intro(interview_id: str, payload: IntroRequest, user: dict = Depends(current_user)) -> dict:
    """The candidate's spoken introduction. Not scored; kept for the saved conversation."""
    interview = _owned(interview_id, user["id"])
    if interview["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Interview is not in progress")
    interview["intro"] = {"greeting": payload.greeting, "answer": payload.answer}
    save_transcript(interview, user)
    return {"status": "ok"}


@router.get("/{interview_id}/question")
def get_question(interview_id: str, user: dict = Depends(current_user)) -> dict:
    interview = _owned(interview_id, user["id"])
    if interview["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Start the interview before requesting a question")
    question = _question(interview)
    if question is None:
        raise HTTPException(status_code=404, detail="No more questions; retrieve the report")
    if question["id"] not in interview["asked_question_ids"]:
        interview["asked_question_ids"].append(question["id"])
    return {"interview_id": interview_id, "question": _public(question)}


@router.post("/{interview_id}/answer")
def submit_answer(interview_id: str, payload: AnswerRequest, user: dict = Depends(current_user)) -> dict:
    interview = _owned(interview_id, user["id"])
    if interview["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Interview is not in progress")
    question = _question(interview)
    if question is None:
        raise HTTPException(status_code=409, detail="There is no unanswered question")

    if interview.get("adaptive"):
        evaluation = evaluate_answer(question, payload.answer)
    else:
        evaluation = keyword_evaluate(question, payload.answer)
    interview["answers"].append({"question_id": question["id"], "question": question["question"],
                                 "kind": question.get("kind", "main"),
                                 "answer": payload.answer, "evaluation": evaluation,
                                 "answered_at": datetime.now(UTC).isoformat()})
    interview["current_index"] += 1

    if interview.get("adaptive") and len(interview["answers"]) < interview["question_count"]:
        upcoming = _choose_next(interview, evaluation, question, payload.answer)
        if upcoming:
            interview["selected_questions"].append(upcoming)

    next_question = _question(interview)
    if next_question is None:
        interview["status"] = "completed"
        report = _report(interview)
        REPORTS[interview_id] = report
    else:
        interview["asked_question_ids"].append(next_question["id"])
        # A human-sounding reaction to THIS answer plus the bridge to the next question (falls back safely).
        line = transition(interview, question, payload.answer, evaluation, next_question, user.get("name"))
        if line:
            next_question["lead_in"] = line
        report = None
    save_transcript(interview, user, report)
    return {"evaluation": _public_eval(evaluation), "next_question": _public(next_question),
            "status": interview["status"], "report": report}