import base64
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_utc
from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.jobs import service as jobs
from app.modules.identity import emails
from app.modules.identity.models import AccountToken, AuditLog, Invite, LearnerProfile, RefreshToken, User

# Constant-time-ish defence: verify against a dummy hash when the email is unknown.
_DUMMY_HASH = hash_password("not-a-real-password")


def audit(db: Session, actor_id, action: str, entity: str, entity_id="", **detail) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, entity=entity, entity_id=str(entity_id), detail=detail))


def create_user(db: Session, email: str, password: str, name: str, role: str = "learner", locale: str = "en", commit: bool = True, **audit_detail) -> User:
    email = email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("An account with this email already exists")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password), role=role, preferred_locale=locale)
    db.add(user)
    db.flush()
    db.add(LearnerProfile(user_id=user.id))
    audit(db, user.id, "register", "user", user.id, **audit_detail)
    if commit:
        db.commit()
    return user


def register(db: Session, email: str, password: str, name: str, locale: str, invite_code: str | None, ip: str) -> User:
    """Self-service sign-up. With EDU_REGISTRATION_MODE=invite a valid invite code is required;
    in open mode a code is optional (it can still grant the reviewer role). The invite is
    redeemed, the account created and the verification email queued in one transaction."""
    invite = None
    if invite_code:
        invite = redeem_invite(db, invite_code, email)
    elif get_settings().registration_mode == "invite":
        raise Forbidden("Registration is by invitation only. Ask your teacher or admin for an invite code.")
    extra = {"invite": str(invite.id)} if invite else {}
    user = create_user(db, email, password, name, role=invite.role if invite else "learner", locale=locale, commit=False, **extra)
    request_verification(db, user, ip)
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


# --------------------------------------------------------------------------- invites


INVITE_ALPHABET_LEN = 16  # base32 characters: 80 random bits, shown as XXXX-XXXX-XXXX-XXXX


def new_invite_code() -> str:
    raw = base64.b32encode(secrets.token_bytes(10)).decode()[:INVITE_ALPHABET_LEN]
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def invite_hash(code: str) -> str:
    """Codes are typed by people: ignore case, spaces and dashes."""
    return hash_token(re.sub(r"[\s-]", "", code).upper())


def invite_status(invite: Invite, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if invite.revoked_at:
        return "revoked"
    if invite.uses >= invite.max_uses:
        return "used"
    if invite.expires_at and as_utc(invite.expires_at) < now:
        return "expired"
    return "active"


def create_invite(db: Session, admin: User, email: str | None, role: str, note: str, max_uses: int, expires_in_days: int | None) -> tuple[Invite, str]:
    code = new_invite_code()
    invite = Invite(
        code_hash=invite_hash(code),
        email=email.lower().strip() if email else None,
        role=role,
        note=note.strip(),
        max_uses=max_uses,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None,
        created_by=admin.id,
    )
    db.add(invite)
    db.flush()
    audit(db, admin.id, "invite_create", "invite", invite.id, email=invite.email, role=role, max_uses=max_uses)
    return invite, code


def redeem_invite(db: Session, code: str, email: str) -> Invite:
    invalid = AppError("This invite code is not valid: it may be mistyped, used up, expired or revoked")
    invite = db.scalar(select(Invite).where(Invite.code_hash == invite_hash(code)))
    if not invite or invite_status(invite) != "active":
        raise invalid
    if invite.email and invite.email != email.lower().strip():
        raise AppError("This invite is for a different email address")
    # Count the use atomically, so two sign-ups racing for the last use cannot both get in.
    taken = db.execute(
        update(Invite).where(Invite.id == invite.id, Invite.uses < Invite.max_uses, Invite.revoked_at.is_(None)).values(uses=Invite.uses + 1)
    ).rowcount
    if taken != 1:
        raise invalid
    return invite


def revoke_invite(db: Session, admin: User, invite_id: uuid.UUID) -> Invite:
    invite = db.get(Invite, invite_id)
    if not invite:
        raise NotFound("Invite not found")
    if not invite.revoked_at:
        invite.revoked_at = datetime.now(UTC)
        audit(db, admin.id, "invite_revoke", "invite", invite.id)
    return invite


# --------------------------------------------------------------------------- emailed tokens


def issue_account_token(db: Session, user: User, purpose: str, ip: str, ttl: timedelta) -> str:
    """A fresh single-use token; earlier unused ones for the same purpose stop working."""
    now = datetime.now(UTC)
    db.execute(update(AccountToken).where(AccountToken.user_id == user.id, AccountToken.purpose == purpose, AccountToken.used_at.is_(None)).values(used_at=now))
    raw = secrets.token_urlsafe(32)
    db.add(AccountToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw), email=user.email, requested_ip=ip[:64], expires_at=now + ttl))
    db.flush()
    return raw


def tokens_sent_recently(db: Session, user_id: uuid.UUID, purpose: str, now: datetime) -> int:
    since = now - timedelta(hours=1)
    return db.scalar(
        select(func.count()).select_from(AccountToken).where(AccountToken.user_id == user_id, AccountToken.purpose == purpose, AccountToken.created_at >= since)
    )


def _use_token(db: Session, raw: str, purpose: str) -> tuple[AccountToken, User]:
    invalid = AppError("This link is invalid or has expired. Request a new one.")
    token = db.scalar(select(AccountToken).where(AccountToken.token_hash == hash_token(raw), AccountToken.purpose == purpose))
    now = datetime.now(UTC)
    if not token or token.used_at or as_utc(token.expires_at) < now:
        raise invalid
    user = db.get(User, token.user_id)
    if not user or user.status != "active" or user.email != token.email:
        raise invalid
    # Single use even when the link is opened twice at the same moment.
    if db.execute(update(AccountToken).where(AccountToken.id == token.id, AccountToken.used_at.is_(None)).values(used_at=now)).rowcount != 1:
        raise invalid
    return token, user


def request_password_reset(db: Session, email: str, ip: str) -> None:
    """Always the same response and the same work in the request (enqueue one job), whether or
    not the address has an account, so the endpoint reveals nothing. The worker looks it up."""
    jobs.enqueue(db, "account.password_reset", {"email": email.lower().strip(), "ip": ip})
    db.commit()


def request_verification(db: Session, user: User, ip: str = "") -> None:
    if not user.email_verified_at:
        jobs.enqueue(db, "account.verify_email", {"user_id": str(user.id), "ip": ip}, created_by=user.id)


def _set_password(db: Session, user: User, new_password: str) -> None:
    """New hash, and every existing session ends: refresh tokens revoked, access tokens
    invalidated through token_version."""
    user.password_hash = hash_password(new_password)
    user.token_version = (user.token_version or 0) + 1
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))


def _notify_password_changed(db: Session, user: User) -> None:
    from app.jobs.mail import queue_email  # handler modules import this module

    link = f"{get_settings().public_web_url.rstrip('/')}/forgot-password"
    queue_email(db, emails.password_changed(user.name, user.email, user.preferred_locale, link), created_by=user.id)


def reset_password(db: Session, raw: str, new_password: str, ip: str) -> User:
    token, user = _use_token(db, raw, "reset")
    _set_password(db, user, new_password)
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)  # they just proved the mailbox is theirs
    audit(db, user.id, "password_reset", "user", user.id, ip=ip)
    _notify_password_changed(db, user)
    db.commit()
    return user


def change_password(db: Session, user: User, current: str, new_password: str, ip: str) -> None:
    # 400, not 401: a 401 would make the web app think the session itself is gone.
    if not verify_password(current, user.password_hash):
        raise AppError("Your current password is not correct")
    _set_password(db, user, new_password)
    audit(db, user.id, "password_change", "user", user.id, ip=ip)
    _notify_password_changed(db, user)
    db.commit()


def verify_email(db: Session, raw: str) -> User:
    token = db.scalar(select(AccountToken).where(AccountToken.token_hash == hash_token(raw), AccountToken.purpose == "verify"))
    if token and token.used_at:  # the link opened again after it worked: still a success
        user = db.get(User, token.user_id)
        if user and user.email_verified_at and user.email == token.email:
            return user
    token, user = _use_token(db, raw, "verify")
    user.email_verified_at = user.email_verified_at or datetime.now(UTC)
    audit(db, user.id, "email_verified", "user", user.id)
    db.commit()
    return user


def resend_verification(db: Session, user: User, ip: str) -> None:
    if user.email_verified_at:
        raise Conflict("Your email address is already verified")
    request_verification(db, user, ip)
    db.commit()


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
    return create_access_token(user.id, user.role, user.token_version), raw


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


def purge_expired_refresh_tokens(db: Session, now: datetime) -> int:
    """Expired tokens can never be exchanged again (a replay gets 401 either way), so drop them."""
    return db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now)).rowcount


def purge_expired_account_tokens(db: Session, now: datetime) -> int:
    """Reset and verification tokens a day past expiry (kept that long for the per-hour email limit)."""
    return db.execute(delete(AccountToken).where(AccountToken.expires_at < now - timedelta(days=1))).rowcount


def get_profile(db: Session, user: User) -> LearnerProfile:
    profile = db.get(LearnerProfile, user.id)
    if not profile:
        profile = LearnerProfile(user_id=user.id)
        db.add(profile)
        db.commit()
    return profile
