"""Proctoring routes for an interview in progress.

Place at: app/api/v1/proctoring.py   and add it to router.py (see README-PROCTORING.md).

POST /interview/{id}/proctor/frame   one camera frame (multipart field "file"); returns a warning to show, if any
POST /interview/{id}/proctor/event   something only the browser can see: tab hidden, camera unavailable

Both need the candidate's login and only work on their own interview while it is in progress. If the detection
libraries aren't installed the frame route answers {"status": "unavailable"} and the front end stops sending.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.app.api.dependencies import current_user
from backend.app.proctoring.analyzer import (
    DEVICE_CONF,
    FrameError,
    ProctoringUnavailable,
    analyze_frame,
)
from backend.app.proctoring.session import (
    SNAPSHOT_DIR,
    accept_frame,
    apply_event,
    apply_observation,
    save_snapshot,
    set_baseline,
)
from backend.app.services.store import INTERVIEWS

log = logging.getLogger(__name__)
if not any(getattr(handler, "_proctor_file_handler", False) for handler in log.handlers):
    configured_path = os.getenv("PROCTOR_LOG_FILE")
    log_path = (
        Path(configured_path)
        if configured_path
        else Path(__file__).resolve().parents[3] / "logs" / "proctoring.log"
    )
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=int(os.getenv("PROCTOR_LOG_MAX_BYTES", "5242880")),
        backupCount=int(os.getenv("PROCTOR_LOG_BACKUPS", "3")), encoding="utf-8",
    )
    file_handler._proctor_file_handler = True
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(file_handler)
    log.setLevel(logging.INFO)
router = APIRouter(prefix="/interview", tags=["proctoring"])

MAX_FRAME_BYTES = 1_500_000   # a 640-pixel JPEG is about 50 KB; this only stops abuse


class ProctorEvent(BaseModel):
    type: str = Field(pattern="^(tab_hidden|camera_unavailable)$")


def _owned_interview(interview_id: str, user_id: str) -> dict:
    interview = INTERVIEWS.get(interview_id)
    if interview is None or interview["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


def _active_interview(interview_id: str, user_id: str) -> dict:
    interview = _owned_interview(interview_id, user_id)
    if interview["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="Interview is not in progress")
    return interview


@router.post("/{interview_id}/proctor/baseline")
def set_proctor_baseline(
    interview_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
) -> dict:
    """Register the verified candidate reference photo and face biometric descriptor."""
    interview = _owned_interview(interview_id, user["id"])
    data = file.file.read(MAX_FRAME_BYTES + 1)
    if len(data) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="Frame is too large")
    try:
        obs = analyze_frame(data)
    except ProctoringUnavailable as exc:
        log.warning("Proctoring baseline unavailable for %s: %s", interview_id, exc)
        return {"status": "unavailable", "message": "Proctoring analyzer unavailable."}
    except FrameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if obs.get("faces", 0) == 0:
        raise HTTPException(
            status_code=422,
            detail="No face detected. Please look clearly into the camera with good lighting.",
        )
    if obs.get("faces", 0) > 1:
        raise HTTPException(
            status_code=422,
            detail="Multiple faces detected. Please ensure you are alone in front of the camera.",
        )
    desc = obs.get("face_descriptor")
    if not desc:
        raise HTTPException(
            status_code=422,
            detail="Could not extract face biometric signature. Please look directly at the camera.",
        )

    set_baseline(interview, desc, image_data=data)
    log.info("interview_id=%s baseline_registered=True", interview_id)
    return {
        "status": "ok",
        "baseline_set": True,
        "message": "Candidate reference identity photo registered successfully.",
    }


@router.get("/{interview_id}/proctor/baseline")
def get_proctor_baseline(interview_id: str, user: dict = Depends(current_user)):
    """Retrieve the registered baseline reference image if present."""
    from fastapi.responses import FileResponse
    _owned_interview(interview_id, user["id"])
    path = SNAPSHOT_DIR / interview_id / "baseline.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No baseline image on record")
    return FileResponse(path, media_type="image/jpeg")


def _end_at_warning_limit(interview: dict, result: dict) -> dict:
    """End the interview as soon as its third candidate warning has been issued, and generate its report."""
    warning_limit = result.get("warnings_max", 0)
    if warning_limit and result.get("warnings_used", 0) >= warning_limit:
        interview["status"] = "terminated"
        interview["ended_at"] = datetime.now(UTC).isoformat()
        interview["termination_reason"] = "proctoring_warning_limit"
        result["interview_ended"] = True

        from backend.app.api.v1.interviews import _report, save_transcript
        from backend.app.services.store import REPORTS, USERS
        report = _report(interview)
        REPORTS[interview["id"]] = report
        cand_user = USERS.get(interview.get("user_id"), {})
        save_transcript(interview, cand_user, report)
        result["report"] = report

        log.warning(
            "interview_id=%s ended reason=warning_limit warnings=%s/%s report_generated=True",
            interview["id"], result.get("warnings_used"), result.get("warnings_max"),
        )
    return result


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
    except ProctoringUnavailable as exc:
        log.warning("Proctoring unavailable for interview %s: %s", interview_id, exc)
        return {"status": "unavailable"}
    except FrameError as exc:
        log.warning("Invalid proctoring frame for interview %s: %s", interview_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        result = apply_observation(interview, observation)
    except Exception as exc:
        log.exception("Error applying proctoring observation for %s: %s", interview_id, exc)
        return {
            "status": "ok",
            "violation": None,
            "warning": None,
            "warnings_used": (interview.get("proctoring") or {}).get("warnings", 0),
            "warnings_max": 5,
        }
    log.info(
        "interview_id=%s frame=analyzed image_size=%s faces=%s people=%s objects=%s "
        "devices=%s candidates=%s device_threshold=%s yaw=%s "
        "finding=%s warning=%s warnings_used=%s/%s",
        interview_id, observation.get("image_size"), observation["faces"], observation["people"],
        observation.get("objects", []),
        ",".join(observation["devices"]) or "none", observation.get("device_scores", []), DEVICE_CONF,
        observation["yaw"],
        result.get("violation") or "none", bool(result.get("warning")),
        result.get("warnings_used"), result.get("warnings_max"),
    )
    if result.get("violation"):
        save_snapshot(interview["id"], result["violation"], data)
    return _end_at_warning_limit(interview, result)


@router.post("/{interview_id}/proctor/event")
def browser_event(interview_id: str, payload: ProctorEvent, user: dict = Depends(current_user)) -> dict:
    interview = _active_interview(interview_id, user["id"])
    result = apply_event(interview, payload.type)
    if result.get("status") == "ok":
        log.info(
            "interview_id=%s event=%s warning=%s warnings_used=%s/%s",
            interview_id, payload.type, bool(result.get("warning")),
            result.get("warnings_used"), result.get("warnings_max"),
        )
    return _end_at_warning_limit(interview, result)
