"""Registration and login endpoints for local development."""
import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend.app.services.store import SESSIONS, USERS

router = APIRouter(prefix="/auth", tags=["auth"])


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
    email = payload.email.lower()
    if any(user["email"] == email for user in USERS.values()):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user_id = secrets.token_urlsafe(16)
    salt, digest = _hash_password(payload.password)
    user = {"id": user_id, "email": email, "name": payload.name, "salt": salt,
            "password_hash": digest, "created_at": datetime.now(UTC).isoformat()}
    USERS[user_id] = user
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user_id
    return {"access_token": token, "token_type": "bearer", "user": {k: user[k] for k in ("id", "email", "name", "created_at")}}


@router.post("/login")
def login(payload: LoginRequest) -> dict:
    user = next((u for u in USERS.values() if u["email"] == payload.email.lower()), None)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _, digest = _hash_password(payload.password, bytes.fromhex(user["salt"]))
    if not hmac.compare_digest(digest, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = user["id"]
    return {"access_token": token, "token_type": "bearer", "user": {k: user[k] for k in ("id", "email", "name", "created_at")}}
