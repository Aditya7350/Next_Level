import os
os.environ["TESTING_ENV"] = "1"
import secrets
import pytest
from fastapi.testclient import TestClient

from backend.app.api.v1.interviews import _report
from backend.app.main import app
from backend.app.services.store import INTERVIEWS, JDS, REPORTS, RESUMES, SESSIONS, USERS

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    for s in (INTERVIEWS, JDS, REPORTS, RESUMES, SESSIONS, USERS):
        s._cache.clear()
    yield
    for s in (INTERVIEWS, JDS, REPORTS, RESUMES, SESSIONS, USERS):
        s._cache.clear()


def test_admin_stats_and_candidate_listing():
    # Setup candidate user and session
    user = {"id": "u_test_1", "email": "test@demo.com", "name": "Alex Smith", "role": "candidate", "created_at": "2026-11-23T00:00:00Z"}
    USERS["u_test_1"] = user
    SESSIONS["tok_test_1"] = "u_test_1"

    # Setup admin user and session
    admin_user = {"id": "u_admin_1", "email": "admin@interview.ai", "name": "Lead Recruiter", "role": "admin", "created_at": "2026-11-23T00:00:00Z"}
    USERS["u_admin_1"] = admin_user
    SESSIONS["tok_admin_1"] = "u_admin_1"

    # Setup resume
    RESUMES["r_test_1"] = {
        "id": "r_test_1",
        "user_id": "u_test_1",
        "filename": "alex_resume.pdf",
        "parsed_text": "Alex Smith. Python, FastAPI, Docker developer.",
        "profile": {"skills": ["Python", "FastAPI", "Docker"], "experience": ["Backend Dev at Corp"]},
        "created_at": "2026-11-23T01:00:00Z",
    }

    # Setup interview & report
    interview = {
        "id": "iv_test_1",
        "user_id": "u_test_1",
        "interview_type": "Senior Python Engineer",
        "difficulty": "advanced",
        "status": "completed",
        "selected_questions": [
            {"id": "q1", "question": "What is GIL?", "subtopic": "Python Core", "key_points": ["global interpreter lock"]},
        ],
        "answers": [
            {
                "question_id": "q1",
                "question": "What is GIL?",
                "answer": "The Global Interpreter Lock ensures one thread executes Python bytecode.",
                "evaluation": {"score": 5, "covered_concepts": ["GIL", "bytecode"], "missing_concepts": []},
            }
        ],
        "proctoring": {"events": [], "warnings": 0},
    }
    INTERVIEWS["iv_test_1"] = interview

    report = _report(interview)
    REPORTS["iv_test_1"] = report

    # 1. Candidate must be forbidden from admin endpoints
    cand_headers = {"Authorization": "Bearer tok_test_1"}
    res_cand_block = client.get("/api/v1/admin/stats", headers=cand_headers)
    assert res_cand_block.status_code == 403

    # 2. Admin successfully gets stats
    admin_headers = {"Authorization": "Bearer tok_admin_1"}
    res_stats = client.get("/api/v1/admin/stats", headers=admin_headers)
    assert res_stats.status_code == 200
    data_stats = res_stats.json()
    assert data_stats["total_candidates"] >= 1
    assert data_stats["total_resumes"] >= 1
    assert data_stats["total_interviews"] >= 1
    assert data_stats["completed_interviews"] >= 1
    assert data_stats["average_score"] is not None

    # 3. Test Candidates List
    res_cand = client.get("/api/v1/admin/candidates", headers=admin_headers)
    assert res_cand.status_code == 200
    candidates = res_cand.json()["candidates"]
    assert len(candidates) >= 1
    alex = next(c for c in candidates if c["id"] == "u_test_1")
    assert alex["name"] == "Alex Smith"
    assert alex["has_resume"] is True
    assert "Python" in alex["skills"]
    assert alex["latest_interview"]["score"] == 5.0
    assert alex["latest_interview"]["verdict"] == "Strong Hire"

    # 4. Test Candidate Dossier
    res_dossier = client.get("/api/v1/admin/candidate/u_test_1", headers=admin_headers)
    assert res_dossier.status_code == 200
    dossier = res_dossier.json()
    assert dossier["candidate"]["name"] == "Alex Smith"
    assert dossier["resume"]["filename"] == "alex_resume.pdf"
    assert len(dossier["interviews"]) == 1
    assert dossier["interviews"][0]["report"]["score"] == 5.0

    # 5. Test Enhanced Report Fields
    assert report["verdict"] == "Strong Hire"
    assert report["candidate_name"] == "Alex Smith"
    assert report["integrity"]["integrity_score"] == 100
    assert report["integrity"]["integrity_verdict"] == "Clean Session"
    assert len(report["qna"]) == 1
    assert report["qna"][0]["score"] == 5
    assert "Global Interpreter Lock" in report["qna"][0]["candidate_answer"]


def test_report_generated_for_warning_terminated_interview():
    """Verify report is properly generated and retrieved when interview is terminated due to proctoring warnings."""
    from backend.app.api.v1.proctoring import _end_at_warning_limit

    user = {"id": "u_term_1", "email": "term@demo.com", "name": "Taylor Ray", "role": "candidate", "created_at": "2026-11-23T00:00:00Z"}
    USERS["u_term_1"] = user
    SESSIONS["tok_term_1"] = "u_term_1"

    interview = {
        "id": "iv_term_1",
        "user_id": "u_term_1",
        "interview_type": "Frontend Developer",
        "difficulty": "intermediate",
        "status": "in_progress",
        "selected_questions": [
            {"id": "q1", "question": "What is React state?", "subtopic": "React", "key_points": ["state"]},
            {"id": "q2", "question": "What is CSS Grid?", "subtopic": "CSS", "key_points": ["grid"]},
        ],
        "answers": [
            {
                "question_id": "q1",
                "question": "What is React state?",
                "answer": "State holds reactive component data.",
                "evaluation": {"score": 4, "covered_concepts": ["state"], "missing_concepts": []},
            }
        ],
        "proctoring": {
            "events": [{"type": "multiple_people", "time": "2026-11-23T00:01:00Z"}],
            "warnings": 3,
        },
    }
    INTERVIEWS["iv_term_1"] = interview

    # Trigger warning limit termination
    proctor_res = {"status": "ok", "warning": "Third warning", "warnings_used": 3, "warnings_max": 3}
    term_res = _end_at_warning_limit(interview, proctor_res)

    assert term_res["interview_ended"] is True
    assert "report" in term_res
    assert interview["status"] == "terminated"
    assert interview["termination_reason"] == "proctoring_warning_limit"
    assert "iv_term_1" in REPORTS

    # Verify report contents
    rep = REPORTS["iv_term_1"]
    assert rep["status"] == "terminated"
    assert rep["termination_reason"] == "proctoring_warning_limit"
    assert rep["score"] == 4.0
    assert any("proctoring limit was reached" in r for r in rep["recommendations"])

    # Verify candidate can fetch it via API
    headers = {"Authorization": "Bearer tok_term_1"}
    api_rep = client.get("/api/v1/interview/iv_term_1/report", headers=headers)
    assert api_rep.status_code == 200
    assert api_rep.json()["status"] == "terminated"
    assert api_rep.json()["score"] == 4.0


def test_finish_interview_endpoint_generates_report():
    """Verify candidate can conclude interview early and retrieve scorecard."""
    user = {"id": "u_fin_1", "email": "fin@demo.com", "name": "Jordan Lee", "role": "candidate", "created_at": "2026-11-23T00:00:00Z"}
    USERS["u_fin_1"] = user
    SESSIONS["tok_fin_1"] = "u_fin_1"

    interview = {
        "id": "iv_fin_1",
        "user_id": "u_fin_1",
        "interview_type": "DevOps Engineer",
        "difficulty": "intermediate",
        "status": "in_progress",
        "selected_questions": [
            {"id": "q1", "question": "What is Docker?", "subtopic": "Containers", "key_points": ["isolation"]},
        ],
        "answers": [
            {
                "question_id": "q1",
                "question": "What is Docker?",
                "answer": "Docker provides containerized isolation for apps.",
                "evaluation": {"score": 5, "covered_concepts": ["isolation"], "missing_concepts": []},
            }
        ],
        "proctoring": {"events": [], "warnings": 0},
    }
    INTERVIEWS["iv_fin_1"] = interview

    headers = {"Authorization": "Bearer tok_fin_1"}
    res = client.post("/api/v1/interview/iv_fin_1/finish", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "completed"
    assert res.json()["report"]["score"] == 5.0
    assert "iv_fin_1" in REPORTS


def test_get_report_dynamic_fallback():
    """Verify get_report generates report on the fly if missing from in-memory cache."""
    test_uid = f"u_fall_{secrets.token_hex(4)}"
    test_ivid = f"iv_fall_{secrets.token_hex(4)}"
    test_tok = f"tok_fall_{secrets.token_hex(4)}"

    user = {"id": test_uid, "email": f"{test_uid}@demo.com", "name": "Sam Carter", "role": "candidate", "created_at": "2026-11-23T00:00:00Z"}
    USERS[test_uid] = user
    SESSIONS[test_tok] = test_uid

    interview = {
        "id": test_ivid,
        "user_id": test_uid,
        "interview_type": "Fullstack",
        "difficulty": "intermediate",
        "status": "completed",
        "selected_questions": [
            {"id": "q1", "question": "Explain REST", "subtopic": "APIs", "key_points": ["stateless"]},
        ],
        "answers": [
            {
                "question_id": "q1",
                "question": "Explain REST",
                "answer": "REST is a stateless architectural style.",
                "evaluation": {"score": 4, "covered_concepts": ["stateless"], "missing_concepts": []},
            }
        ],
        "proctoring": {"events": [], "warnings": 0},
    }
    INTERVIEWS[test_ivid] = interview

    assert test_ivid not in REPORTS
    headers = {"Authorization": f"Bearer {test_tok}"}
    res = client.get(f"/api/v1/interview/{test_ivid}/report", headers=headers)
    assert res.status_code == 200
    assert res.json()["score"] == 4.0
    assert test_ivid in REPORTS
