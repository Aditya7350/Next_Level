"""Registration and login endpoints for candidates and recruiters."""
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime

try:
    import email_validator
    email_validator.CHECK_DELIVERABILITY = False
except Exception:
    pass

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend.app.services.store import SESSIONS, USERS

router = APIRouter(prefix="/auth", tags=["auth"])

ADMIN_DEFAULT_EMAIL = os.getenv("ADMIN_EMAIL", "admin@interview.ai").lower()
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminPass123")
ADMIN_DEFAULT_NAME = os.getenv("ADMIN_NAME", "Recruiter Admin")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return salt.hex(), digest.hex()


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> dict:
    """Register a new candidate account. Role is strictly 'candidate'."""
    email = payload.email.lower()
    if any((user.get("email") or "").lower() == email for user in USERS.values()):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user_id = secrets.token_urlsafe(16)
    salt, digest = _hash_password(payload.password)
    user = {
        "id": user_id,
        "email": email,
        "name": payload.name,
        "salt": salt,
        "password_hash": digest,
        "role": "candidate",
        "created_at": datetime.now(UTC).isoformat(),
    }
    USERS[user_id] = user
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user_id
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.get("id", user_id),
            "email": user.get("email", email),
            "name": user.get("name", payload.name),
            "role": user.get("role", "candidate"),
            "created_at": user.get("created_at") or datetime.now(UTC).isoformat(),
        },
    }


@router.post("/login")
def login(payload: LoginRequest) -> dict:
    """Sign in for candidates."""
    email = payload.email.lower()
    user = next((u for u in USERS.values() if (u.get("email") or "").lower() == email), None)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="No account found with this email. Please click 'Create an account' below to register first.",
        )
    salt_hex = user.get("salt")
    pwd_hash = user.get("password_hash")
    if not salt_hex or not pwd_hash:
        raise HTTPException(status_code=401, detail="Incorrect password. Please verify and try again.")
    try:
        _, digest = _hash_password(payload.password, bytes.fromhex(salt_hex))
    except Exception:
        raise HTTPException(status_code=401, detail="Incorrect password. Please verify and try again.")
    if not hmac.compare_digest(digest, pwd_hash):
        raise HTTPException(status_code=401, detail="Incorrect password. Please verify and try again.")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user["id"]
    role = user.get("role", "candidate")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.get("id", ""),
            "email": user.get("email", email),
            "name": user.get("name", "Candidate"),
            "role": role,
            "created_at": user.get("created_at") or datetime.now(UTC).isoformat(),
        },
    }


@router.post("/admin/login")
def admin_login(payload: LoginRequest) -> dict:
    """Dedicated sign in for recruiters and platform administrators."""
    email = payload.email.lower()
    user = next((u for u in USERS.values() if (u.get("email") or "").lower() == email and u.get("role") == "admin"), None)

    # Auto-seed default admin credentials if matching default env configuration
    if user is None and email == ADMIN_DEFAULT_EMAIL and payload.password == ADMIN_DEFAULT_PASSWORD:
        user_id = "admin_master_001"
        salt, digest = _hash_password(payload.password)
        user = {
            "id": user_id,
            "email": ADMIN_DEFAULT_EMAIL,
            "name": ADMIN_DEFAULT_NAME,
            "salt": salt,
            "password_hash": digest,
            "role": "admin",
            "created_at": datetime.now(UTC).isoformat(),
        }
        USERS[user_id] = user

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    salt_hex = user.get("salt")
    pwd_hash = user.get("password_hash")
    if not salt_hex or not pwd_hash:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    try:
        _, digest = _hash_password(payload.password, bytes.fromhex(salt_hex))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    if not hmac.compare_digest(digest, pwd_hash):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: Candidate accounts cannot access the Recruiter Admin Portal.",
        )

    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user["id"]
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.get("id", ""),
            "email": user.get("email", email),
            "name": user.get("name", ADMIN_DEFAULT_NAME),
            "role": "admin",
            "created_at": user.get("created_at") or datetime.now(UTC).isoformat(),
        },
    }
