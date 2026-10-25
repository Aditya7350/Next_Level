"""Job description analysis endpoint."""
import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api.dependencies import current_user
from backend.app.services.store import JDS

router = APIRouter(prefix="/jd", tags=["job descriptions"])
SKILLS = ("python", "java", "javascript", "typescript", "fastapi", "react", "sql", "mongodb",
          "machine learning", "deep learning", "rag", "llm", "vector search", "aws", "gcp",
          "docker", "kubernetes", "system design", "communication", "leadership")


class JDRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=30, max_length=30000)


@router.post("/analyze", status_code=201)
def analyze_jd(payload: JDRequest, user: dict = Depends(current_user)) -> dict:
    text = payload.description.lower()
    skills = [skill for skill in SKILLS if re.search(r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])", text)]
    record = {"id": secrets.token_urlsafe(16), "user_id": user["id"], "title": payload.title,
              "required_skills": skills, "description": payload.description,
              "created_at": datetime.now(UTC).isoformat()}
    JDS[record["id"]] = record
    return {k: v for k, v in record.items() if k != "description"}
