"""Persistent repositories backed by MongoDB Atlas with in-memory fallback."""
from backend.app.db.mongo import MongoStore

USERS = MongoStore("users", key_field="id")
SESSIONS = MongoStore("sessions", key_field="token")
RESUMES = MongoStore("resumes", key_field="id")
JDS = MongoStore("jds", key_field="id")
INTERVIEWS = MongoStore("interviews", key_field="id")
REPORTS = MongoStore("reports", key_field="interview_id")
