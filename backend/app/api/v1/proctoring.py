"""Proctoring routes for an interview in progress.

Place at: app/api/v1/proctoring.py   and add it to router.py (see README-PROCTORING.md).

POST /interview/{id}/proctor/frame   one camera frame (multipart field "file"); returns a warning to show, if any
POST /interview/{id}/proctor/event   something only the browser can see: tab hidden, camera unavailable

Both need the candidate's login and only work on their own interview while it is in progress. If the detection
libraries aren't installed the frame route answers {"status": "unavailable"} and the front end stops sending.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.app.api.dependencies import current_user
from backend.app.proctoring.analyzer import FrameError, ProctoringUnavailable, analyze_frame
from backend.app.proctoring.session import (
    accept_frame,
    apply_event,
    apply_observation,
    save_snapshot,
)
from backend.app.services.store import INTERVIEWS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/interview", tags=["proctoring"])

MAX_FRAME_BYTES = 1_500_000   # a 640-pixel JPEG is about 50 KB; this only stops abuse


class ProctorEvent(BaseModel):
    type: str = Field(pattern="^(tab_hidden|camera_unavailable)$")


def _active_interview(interview_id: str, user_id: str) -> dict:
    interview = INTERVIEWS.get(interview_id)
    if interview is None or interview["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    if interview["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Interview is not in progress")
    return interview


# A plain "def" (not "async def"): the model work is slow and CPU-bound, so FastAPI runs it in a worker thread
# instead of freezing every other request.
@router.post("/{interview_id}/proctor/frame")
def check_frame(interview_id: str, file: UploadFile = File(...), user: dict = Depends(current_user)) -> dict:
    interview = _active_interview(interview_id, user["id"])
    if not accept_frame(interview):
        return {"status": "skipped"}
    data = file.file.read(MAX_FRAME_BYTES + 1)
    if len(data) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="Frame is too large")
    try:
        observation = analyze_frame(data)
    except ProctoringUnavailable:
        return {"status": "unavailable"}
    except FrameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = apply_observation(interview, observation)
    if result.get("violation"):
        save_snapshot(interview["id"], result["violation"], data)
    return result


@router.post("/{interview_id}/proctor/event")
def browser_event(interview_id: str, payload: ProctorEvent, user: dict = Depends(current_user)) -> dict:
    interview = _active_interview(interview_id, user["id"])
    return apply_event(interview, payload.type)
