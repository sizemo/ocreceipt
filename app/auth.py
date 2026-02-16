import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User, UserSession

PBKDF2_ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "210000"))
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if not password:
        raise ValueError("Password cannot be empty")

    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return actual_salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, computed = hash_password(password, salt)
    return hmac.compare_digest(computed, expected_hash)




def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(db: Session, user_id: int) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_session_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)

    db.add(UserSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
    db.commit()
    return raw_token


def delete_session(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return

    token_hash = hash_session_token(raw_token)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if session is not None:
        db.delete(session)
        db.commit()


def get_user_by_session_token(db: Session, raw_token: str | None) -> User | None:
    if not raw_token:
        return None

    token_hash = hash_session_token(raw_token)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if session is None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        db.delete(session)
        db.commit()
        return None

    return db.scalar(select(User).where(User.id == session.user_id, User.is_active == True))
