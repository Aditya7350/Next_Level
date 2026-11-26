"""Interview history, reports, and candidate dashboard."""
from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import current_user
from backend.app.services.store import INTERVIEWS, REPORTS

router = APIRouter(tags=["reports"])


@router.get("/interview/{interview_id}/report")
def get_report(interview_id: str, user: dict = Depends(current_user)) -> dict:
    report = REPORTS.get(interview_id)
    if report is None:
        interview = INTERVIEWS.get(interview_id)
        if interview and (interview.get("user_id") == user["id"] or user.get("role") == "admin"):
            from backend.app.api.v1.interviews import _report, save_transcript
            from backend.app.services.store import USERS
            report = _report(interview)
            REPORTS[interview_id] = report
            cand_user = USERS.get(interview.get("user_id"), user)
            save_transcript(interview, cand_user, report)

    if report is None or (report["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=404, detail="Interview report not found or interview is incomplete")
    return report


@router.get("/interview/history")
def history(user: dict = Depends(current_user)) -> dict:
    rows = []
    for interview in INTERVIEWS.values():
        if interview["user_id"] == user["id"]:
            row = {k: v for k, v in interview.items() if k not in {"selected_questions", "answers"}}
            rep = REPORTS.get(interview["id"])
            if rep:
                row["score"] = rep.get("score")
                row["verdict"] = rep.get("verdict")
            rows.append(row)
    return {"items": rows, "total": len(rows)}


@router.get("/dashboard")
def dashboard(user: dict = Depends(current_user)) -> dict:
    interviews = [i for i in INTERVIEWS.values() if i["user_id"] == user["id"]]
    scores = [REPORTS[i["id"]]["score"] for i in interviews if i["id"] in REPORTS]
    return {"interviews_total": len(interviews), "interviews_completed": len(scores),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "recent_interviews": sorted(({k: v for k, v in i.items() if k not in {"selected_questions", "answers"}} for i in interviews), key=lambda r: r["created_at"], reverse=True)[:5]}
