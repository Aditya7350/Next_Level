"""Admin dashboard endpoints for recruiter oversight of candidates, resumes, and reports."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.dependencies import current_user
from backend.app.services.store import INTERVIEWS, REPORTS, RESUMES, USERS

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: dict = Depends(current_user)) -> dict:
    """Validate user is authenticated and possesses the 'admin' role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin authorization required. Access forbidden for candidates.",
        )
    return user


@router.get("/stats")
def get_admin_stats(admin: dict = Depends(_require_admin)) -> dict:
    """Return platform-wide candidate and interview metrics for the admin dashboard."""
    candidates = [u for u in USERS.values() if u.get("role") != "admin"]
    interviews = list(INTERVIEWS.values())
    reports = list(REPORTS.values())
    resumes = list(RESUMES.values())

    completed_reports = [r for r in reports if r.get("score") is not None]
    scores = [r["score"] for r in completed_reports]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    # Count integrity flags
    flagged_count = sum(
        1 for i in interviews
        if (i.get("proctoring") or {}).get("warnings", 0) > 0
        or len((i.get("proctoring") or {}).get("events", [])) > 1
    )

    return {
        "total_candidates": len(candidates),
        "total_resumes": len(resumes),
        "total_interviews": len(interviews),
        "completed_interviews": len(completed_reports),
        "average_score": avg_score,
        "flagged_sessions": flagged_count,
    }


@router.get("/candidates")
def list_candidates(
    q: str = Query("", description="Search term by candidate name, email, or skill"),
    admin: dict = Depends(_require_admin),
) -> dict:
    """List all candidate profiles with resume details, interview counts, and latest scores."""
    search = q.strip().lower()
    items = []

    # Map resumes and interviews by user_id
    user_resumes = {}
    for r in RESUMES.values():
        user_resumes[r.get("user_id")] = r

    user_interviews: dict[str, list[dict]] = {}
    for iv in INTERVIEWS.values():
        uid = iv.get("user_id")
        if uid:
            user_interviews.setdefault(uid, []).append(iv)

    for user in USERS.values():
        if user.get("role") == "admin":
            continue
        uid = user.get("id")
        name = user.get("name", "Candidate")
        email = user.get("email", "")

        resume = user_resumes.get(uid)
        skills = (resume.get("profile") or {}).get("skills", []) if resume else []
        role_focus = (resume.get("profile") or {}).get("summary", "") if resume else ""

        # Filter if search query provided
        if search:
            match_name = search in name.lower()
            match_email = search in email.lower()
            match_skill = any(search in s.lower() for s in skills)
            if not (match_name or match_email or match_skill):
                continue

        ivs = user_interviews.get(uid, [])
        latest_iv = sorted(ivs, key=lambda x: x.get("created_at", ""), reverse=True)[0] if ivs else None

        latest_info = None
        if latest_iv:
            rep = REPORTS.get(latest_iv["id"])
            if rep is None and (latest_iv.get("status") in ("completed", "terminated") or latest_iv.get("answers")):
                from backend.app.api.v1.interviews import _report
                rep = _report(latest_iv)
                REPORTS[latest_iv["id"]] = rep
            integrity = rep.get("integrity") if rep else latest_iv.get("proctoring")
            latest_info = {
                "interview_id": latest_iv["id"],
                "role_title": latest_iv.get("interview_type", "Technical Interview"),
                "difficulty": latest_iv.get("difficulty", "intermediate"),
                "status": latest_iv.get("status", "draft"),
                "created_at": latest_iv.get("created_at"),
                "score": rep.get("score") if rep else None,
                "verdict": rep.get("verdict") if rep else None,
                "integrity_warnings": (integrity or {}).get("warnings", 0),
            }

        items.append({
            "id": uid,
            "name": name,
            "email": email,
            "created_at": user.get("created_at"),
            "has_resume": resume is not None,
            "resume_id": resume.get("id") if resume else None,
            "skills": skills[:8],
            "role_focus": role_focus[:90] + ("…" if len(role_focus) > 90 else ""),
            "interviews_count": len(ivs),
            "latest_interview": latest_info,
        })

    items.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    return {"candidates": items, "total": len(items)}


@router.get("/candidate/{user_id}")
def get_candidate_dossier(user_id: str, admin: dict = Depends(_require_admin)) -> dict:
    """Retrieve full candidate dossier including extracted resume, profile, and interview history."""
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Find resume
    resume = next((r for r in RESUMES.values() if r.get("user_id") == user_id), None)

    # Find interviews and reports
    candidate_interviews = []
    for iv in INTERVIEWS.values():
        if iv.get("user_id") == user_id:
            rep = REPORTS.get(iv["id"])
            if rep is None and (iv.get("status") in ("completed", "terminated") or iv.get("answers")):
                from backend.app.api.v1.interviews import _report
                rep = _report(iv)
                REPORTS[iv["id"]] = rep
            candidate_interviews.append({
                "interview": {
                    "id": iv["id"],
                    "role_title": iv.get("interview_type", "Technical"),
                    "difficulty": iv.get("difficulty", "intermediate"),
                    "status": iv.get("status"),
                    "question_count": iv.get("question_count"),
                    "started_at": iv.get("started_at"),
                    "created_at": iv.get("created_at"),
                    "proctoring": iv.get("proctoring"),
                },
                "report": rep,
                "answers_count": len(iv.get("answers", [])),
            })

    candidate_interviews.sort(key=lambda x: x["interview"].get("created_at") or "", reverse=True)

    return {
        "candidate": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "created_at": user.get("created_at"),
        },
        "resume": {
            "id": resume["id"],
            "filename": resume.get("filename"),
            "skills": (resume.get("profile") or {}).get("skills", []),
            "profile": resume.get("profile"),
            "parsed_text": resume.get("parsed_text", ""),
            "created_at": resume.get("created_at"),
        } if resume else None,
        "interviews": candidate_interviews,
    }


@router.get("/interview/{interview_id}/snapshot/{filename}")
def get_interview_snapshot(
    interview_id: str,
    filename: str,
    admin: dict = Depends(_require_admin),
):
    """Serve verified baseline photo or proctoring violation snapshot to administrators."""
    import re
    from fastapi.responses import FileResponse
    from backend.app.proctoring.session import SNAPSHOT_DIR

    if not re.fullmatch(r"[A-Za-z0-9_-]+", interview_id) or not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise HTTPException(status_code=400, detail="Invalid snapshot identifier")

    snapshot_path = SNAPSHOT_DIR / interview_id / filename
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return FileResponse(snapshot_path, media_type="image/jpeg")
