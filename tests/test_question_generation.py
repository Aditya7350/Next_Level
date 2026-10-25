import pytest
from fastapi.testclient import TestClient

from backend.app.ai.question_generation import generate_resume_questions
from backend.app.main import app
from backend.app.services.store import INTERVIEWS, JDS, REPORTS, RESUMES, SESSIONS, USERS

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_in_memory_store() -> None:
    for store in (INTERVIEWS, JDS, REPORTS, RESUMES, SESSIONS, USERS):
        store.clear()
    yield
    for store in (INTERVIEWS, JDS, REPORTS, RESUMES, SESSIONS, USERS):
        store.clear()


def test_resume_questions_use_profile_details_and_selected_difficulty() -> None:
    resume = {
        "profile": {
            "skills": ["Python", "FastAPI"],
            "projects": ["Built an invoice anomaly detector"],
            "experience": ["Owned production API services"],
            "summary": "Backend engineer focused on reliable systems",
        }
    }

    questions = generate_resume_questions(resume, "Platform Engineer", "advanced")
    prompts = [question[0] for question in questions]

    assert any("invoice anomaly detector" in prompt for prompt in prompts)
    assert any("production API services" in prompt for prompt in prompts)
    assert any("Python" in prompt and "Platform Engineer" in prompt for prompt in prompts)
    assert any("reliable systems" in prompt for prompt in prompts)
    assert all(question[2] == "advanced" for question in questions)


def test_empty_resume_profile_returns_no_personalized_questions() -> None:
    assert generate_resume_questions({"profile": {}}, "Engineer", "intermediate") == []


def test_sparse_resume_still_fills_requested_question_count() -> None:
    questions = generate_resume_questions(
        {"profile": {"skills": ["Python"]}},
        "Backend Engineer",
        "foundational",
        question_count=8,
    )

    assert len(questions) == 8
    assert all("Python" in question[0] for question in questions)


def test_interview_creation_uses_uploaded_resume_details() -> None:
    account = client.post(
        "/api/v1/auth/register",
        json={"name": "Jordan Lee", "email": "jordan@example.com", "password": "DemoPass123"},
    )
    headers = {"Authorization": f"Bearer {account.json()['access_token']}"}
    resume_text = (
        "Jordan Lee\nSkills\nPython, FastAPI\n"
        "Experience\nBuilt scheduling APIs at Acme and reduced queue time by 30%.\n"
        "Projects\nCreated a resume skill matcher with FastAPI.\n"
        "Summary\nBackend developer building reliable services."
    )
    upload = client.post(
        "/api/v1/resume/upload",
        headers=headers,
        files={"file": ("resume.txt", resume_text.encode(), "text/plain")},
    )
    assert upload.status_code == 201

    created = client.post(
        "/api/v1/interview/create",
        headers=headers,
        json={
            "interview_type": "Platform Engineer",
            "difficulty": "advanced",
            "question_count": 5,
            "resume_id": upload.json()["id"],
        },
    )

    assert created.status_code == 201
    questions = INTERVIEWS[created.json()["id"]]["selected_questions"]
    prompt_text = " ".join(question["question"] for question in questions)
    assert "resume skill matcher" in prompt_text
    assert "scheduling APIs" in prompt_text
    assert "Platform Engineer" in prompt_text
    assert len(questions) == 5
    assert all(question["difficulty"] == "advanced" for question in questions)
