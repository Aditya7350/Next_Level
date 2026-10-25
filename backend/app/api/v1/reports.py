"""Interview history, reports, and candidate dashboard."""
from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import current_user
from backend.app.services.store import INTERVIEWS, REPORTS

router = APIRouter(tags=["reports"])


@router.get("/interview/{interview_id}/report")
def get_report(interview_id: str, user: dict = Depends(current_user)) -> dict:
    report = REPORTS.get(interview_id)
    if report is None or report["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Interview report not found or interview is incomplete")
    return report


@router.get("/interview/history")
def history(user: dict = Depends(current_user)) -> dict:
    rows = [{k: v for k, v in interview.items() if k not in {"selected_questions", "answers"}}
            for interview in INTERVIEWS.values() if interview["user_id"] == user["id"]]
    return {"items": rows, "total": len(rows)}


@router.get("/dashboard")
def dashboard(user: dict = Depends(current_user)) -> dict:
    interviews = [i for i in INTERVIEWS.values() if i["user_id"] == user["id"]]
    scores = [REPORTS[i["id"]]["score"] for i in interviews if i["id"] in REPORTS]
    return {"interviews_total": len(interviews), "interviews_completed": len(scores),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "recent_interviews": sorted(({k: v for k, v in i.items() if k not in {"selected_questions", "answers"}} for i in interviews), key=lambda r: r["created_at"], reverse=True)[:5]}
