"""Typed responses for resume ingestion and retrieval."""
from pydantic import BaseModel


class ResumeLinks(BaseModel):
    linkedin: str | None = None
    github: str | None = None


class ResumeProfile(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    links: ResumeLinks = ResumeLinks()
    summary: str | None = None
    skills: list[str] = []
    experience: list[str] = []
    education: list[str] = []
    projects: list[str] = []
    certifications: list[str] = []
    sections_found: list[str] = []
    extraction_warnings: list[str] = []


class ResumeUploadResponse(BaseModel):
    id: str
    user_id: str
    filename: str | None
    profile: ResumeProfile
    skills: list[str]
    created_at: str
    text_characters: int


class ResumeResponse(ResumeUploadResponse):
    parsed_text: str
    text_characters: int | None = None
