"""Password hashing, JWT access tokens and opaque refresh tokens."""

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def _prehash(password: str) -> bytes:
    # bcrypt only reads 72 bytes; pre-hashing keeps long passphrases fully significant.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, role: str, version: int = 0) -> str:
    """`version` is the user's token_version: bumping it (password reset or change) makes every
    access token issued before that stop working immediately, not when it expires."""
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "ver": version,
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the client, sha256 hash for storage)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
