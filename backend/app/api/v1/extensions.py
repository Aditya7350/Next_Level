"""Explicit placeholders for later voice and isolated coding integrations."""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.app.api.dependencies import current_user
from backend.app.api.v1.interviews import _question
from backend.app.services.store import INTERVIEWS, SESSIONS, USERS

router = APIRouter(tags=["extensions"])


class CodeRequest(BaseModel):
    language: str = Field(min_length=1, max_length=40)
    source_code: str = Field(min_length=1, max_length=20000)
    test_cases: list[dict] = Field(default_factory=list, max_length=50)


@router.post("/coding/execute", status_code=501)
def execute_code(payload: CodeRequest, user: dict = Depends(current_user)) -> None:
    raise HTTPException(status_code=501, detail="Code execution is unavailable until an isolated sandbox is configured")


@router.post("/interview/{interview_id}/voice", status_code=501)
def voice_interview(interview_id: str, user: dict = Depends(current_user)) -> None:
    if interview_id not in INTERVIEWS or INTERVIEWS[interview_id]["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Interview not found")
    raise HTTPException(status_code=501, detail="Voice interviews require an STT/TTS provider configuration")


@router.websocket("/ws/interview/{interview_id}")
async def interview_socket(websocket: WebSocket, interview_id: str) -> None:
    token = websocket.query_params.get("token", "")
    user = USERS.get(SESSIONS.get(token, ""))
    interview = INTERVIEWS.get(interview_id)
    if user is None or interview is None or interview["user_id"] != user["id"]:
        await websocket.close(code=1008, reason="Valid bearer token and owned interview required")
        return
    await websocket.accept()
    try:
        await websocket.send_json({"type": "question", "question": _question(interview), "status": interview["status"]})
        while True:
            answer = await websocket.receive_text()
            if len(answer) > 12000:
                await websocket.send_json({"type": "error", "detail": "Answer must be 12000 characters or fewer"})
                continue
            # Keep the socket contract aligned with the REST answer flow.
            if interview["status"] != "in_progress" or _question(interview) is None:
                await websocket.send_json({"type": "error", "detail": "Interview is not accepting answers"})
                continue
            question = _question(interview)
            words = set(answer.lower().replace("/", " ").replace("-", " ").split())
            covered = [c for c in question["expected_concepts"] if any(p in words for p in c.lower().split())]
            missing = [c for c in question["expected_concepts"] if c not in covered]
            evaluation = {"score": max(1, min(5, 1 + len(covered))), "covered_concepts": covered,
                          "missing_concepts": missing, "feedback": "Answer received."}
            interview["answers"].append({"question_id": question["id"], "question": question["question"], "answer": answer, "evaluation": evaluation})
            interview["current_index"] += 1
            next_question = _question(interview)
            if next_question is None:
                from backend.app.api.v1.interviews import _report
                from backend.app.services.store import REPORTS
                interview["status"] = "completed"
                report = _report(interview)
                REPORTS[interview_id] = report
            else:
                interview["asked_question_ids"].append(next_question["id"])
                report = None
            await websocket.send_json({"type": "evaluation", "evaluation": evaluation,
                                       "next_question": next_question, "report": report,
                                       "status": interview["status"]})
    except WebSocketDisconnect:
        return
