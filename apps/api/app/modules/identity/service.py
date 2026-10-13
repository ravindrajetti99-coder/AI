import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_utc
from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.modules.identity.models import AuditLog, LearnerProfile, RefreshToken, User

# Constant-time-ish defence: verify against a dummy hash when the email is unknown.
_DUMMY_HASH = hash_password("not-a-real-password")


def audit(db: Session, actor_id, action: str, entity: str, entity_id="", **detail) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, entity=entity, entity_id=str(entity_id), detail=detail))


def create_user(db: Session, email: str, password: str, name: str, role: str = "learner", locale: str = "en") -> User:
    email = email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("An account with this email already exists")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password), role=role, preferred_locale=locale)
    db.add(user)
    db.flush()
    db.add(LearnerProfile(user_id=user.id))
    audit(db, user.id, "register", "user", user.id)
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user:
        verify_password(password, _DUMMY_HASH)
        raise Unauthorized("Incorrect email or password")
    if not verify_password(password, user.password_hash):
        raise Unauthorized("Incorrect email or password")
    if user.status != "active":
        raise Unauthorized("Account is suspended")
    return user


def issue_tokens(db: Session, user: User, family_id: uuid.UUID | None = None) -> tuple[str, str]:
    s = get_settings()
    raw, hashed = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hashed,
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days),
        )
    )
    db.commit()
    return create_access_token(user.id, user.role), raw


def rotate_refresh(db: Session, raw: str) -> tuple[User, str, str]:
    """Exchange a refresh token for a new pair. Reuse of a spent token revokes the whole family."""
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    now = datetime.now(UTC)
    if not token or token.revoked_at:
        raise Unauthorized("Invalid refresh token")
    if token.used_at and now - as_utc(token.used_at) > timedelta(seconds=get_settings().refresh_reuse_grace_seconds):
        db.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        audit(db, token.user_id, "refresh_reuse_detected", "session", token.family_id)
        db.commit()
        raise Unauthorized("Refresh token reuse detected; please sign in again")
    if as_utc(token.expires_at) < now:
        raise Unauthorized("Refresh token expired")
    user = db.get(User, token.user_id)
    if not user or user.status != "active":
        raise Unauthorized("User inactive")
    token.used_at = token.used_at or now
    access, new_raw = issue_tokens(db, user, family_id=token.family_id)
    return user, access, new_raw


def revoke_refresh(db: Session, raw: str) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if token:
        db.execute(
            update(RefreshToken).where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC))
        )
        db.commit()


def get_profile(db: Session, user: User) -> LearnerProfile:
    profile = db.get(LearnerProfile, user.id)
    if not profile:
        profile = LearnerProfile(user_id=user.id)
        db.add(profile)
        db.commit()
    return profile
