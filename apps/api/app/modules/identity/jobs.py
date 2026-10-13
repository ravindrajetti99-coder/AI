"""Account emails that carry a secret link. The handler creates the token and sends the email
itself, so the raw token exists only in memory and in the recipient's inbox (never in the jobs
table). A failed send rolls the token back; the retry issues a fresh one."""

import uuid
from datetime import timedelta
from urllib.parse import quote

from sqlalchemy import select

from app.core.config import get_settings
from app.jobs.context import JobContext
from app.jobs.mail import QUEUE, deliver
from app.jobs.registry import handler
from app.modules.identity import emails, service
from app.modules.identity.models import User


def _link(path: str, token: str) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}{path}?token={quote(token)}"


def _skip(ctx: JobContext, reason: str) -> None:
    ctx.result.update(sent=False, reason=reason)


@handler("account.password_reset", queue=QUEUE, max_attempts=5)
def send_password_reset(ctx: JobContext) -> None:
    s = get_settings()
    user = ctx.db.scalar(select(User).where(User.email == ctx.payload["email"]))
    if not user or user.status != "active":
        return _skip(ctx, "no active account")  # the requester was told the same as everyone else
    if service.tokens_sent_recently(ctx.db, user.id, "reset", ctx.now()) >= s.account_emails_per_hour:
        return _skip(ctx, "hourly limit reached")
    token = service.issue_account_token(ctx.db, user, "reset", ctx.payload.get("ip", ""), timedelta(minutes=s.password_reset_minutes))
    deliver(ctx, emails.password_reset(user.name, user.email, user.preferred_locale, _link("/reset-password", token), s.password_reset_minutes))
    ctx.result["sent"] = True


@handler("account.verify_email", queue=QUEUE, max_attempts=5)
def send_verification(ctx: JobContext) -> None:
    s = get_settings()
    user = ctx.db.get(User, uuid.UUID(ctx.payload["user_id"]))
    if not user or user.status != "active":
        return _skip(ctx, "no active account")
    if user.email_verified_at:
        return _skip(ctx, "already verified")
    if service.tokens_sent_recently(ctx.db, user.id, "verify", ctx.now()) >= s.account_emails_per_hour:
        return _skip(ctx, "hourly limit reached")
    token = service.issue_account_token(ctx.db, user, "verify", ctx.payload.get("ip", ""), timedelta(hours=s.email_verify_hours))
    deliver(ctx, emails.verify_email(user.name, user.email, user.preferred_locale, _link("/verify-email", token), s.email_verify_hours))
    ctx.result["sent"] = True
