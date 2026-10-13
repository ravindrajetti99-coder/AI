import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import as_utc, get_db
from app.core.deps import client_ip, get_current_user, rate_limit_auth, require_admin
from app.core.errors import AppError, NotFound, Unauthorized
from app.jobs.mail import queue_email
from app.modules.identity import emails, service
from app.modules.identity.models import Invite, User
from app.modules.identity.schemas import (
    AdminUserPatch,
    AuthOptionsOut,
    ChangePasswordIn,
    ForgotPasswordIn,
    InviteCreatedOut,
    InviteIn,
    InviteOut,
    LoginIn,
    MeOut,
    MePatch,
    ProfileOut,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
    VerifyEmailIn,
)

router = APIRouter(tags=["auth"])
COOKIE = "edu_refresh"


def _token_response(response: Response, user: User, access: str, refresh: str) -> TokenOut:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        refresh,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        max_age=s.refresh_token_days * 86400,
        path=f"{s.api_prefix}/auth",
    )
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=s.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.get("/auth/options", response_model=AuthOptionsOut)
def auth_options():
    """What the sign-up page needs to know (whether an invite code is required)."""
    return AuthOptionsOut(registration=get_settings().registration_mode)


@router.post("/auth/register", response_model=TokenOut, status_code=201, dependencies=[Depends(rate_limit_auth)])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = service.register(db, body.email, body.password, body.name, body.preferred_locale, body.invite_code, client_ip(request))
    access, refresh = service.issue_tokens(db, user)
    return _token_response(response, user, access, refresh)


@router.post("/auth/password/forgot", status_code=202, dependencies=[Depends(rate_limit_auth)])
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    service.request_password_reset(db, body.email, client_ip(request))
    return {"status": "accepted", "detail": "If an account uses this address, a reset link is on its way."}


@router.post("/auth/password/reset", status_code=204, dependencies=[Depends(rate_limit_auth)])
def reset_password(body: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    service.reset_password(db, body.token, body.new_password, client_ip(request))
    return Response(status_code=204)


@router.post("/auth/email/verify", response_model=UserOut, dependencies=[Depends(rate_limit_auth)])
def verify_email(body: VerifyEmailIn, db: Session = Depends(get_db)):
    return service.verify_email(db, body.token)


@router.post("/auth/email/resend", status_code=202, dependencies=[Depends(rate_limit_auth)])
def resend_verification(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.resend_verification(db, user, client_ip(request))
    return {"status": "accepted"}


@router.post("/me/password", response_model=TokenOut, tags=["me"], dependencies=[Depends(rate_limit_auth)])
def change_password(body: ChangePasswordIn, request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every session ends (other devices are signed out); this one continues with fresh tokens."""
    service.change_password(db, user, body.current_password, body.new_password, client_ip(request))
    access, refresh = service.issue_tokens(db, user)
    return _token_response(response, user, access, refresh)


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(rate_limit_auth)])
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = service.authenticate(db, body.email, body.password)
    access, refresh = service.issue_tokens(db, user)
    return _token_response(response, user, access, refresh)


@router.post("/auth/refresh", response_model=TokenOut, dependencies=[Depends(rate_limit_auth)])
def refresh(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    raw = (body.refresh_token if body else None) or request.cookies.get(COOKIE)
    if not raw:
        raise Unauthorized("No refresh token")
    user, access, new_raw = service.rotate_refresh(db, raw)
    return _token_response(response, user, access, new_raw)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, body: RefreshIn | None = None, db: Session = Depends(get_db)):
    raw = (body.refresh_token if body else None) or request.cookies.get(COOKIE)
    if raw:
        service.revoke_refresh(db, raw)
    response.delete_cookie(COOKIE, path=f"{get_settings().api_prefix}/auth")
    response.status_code = 204
    return response


def _me(db: Session, user: User) -> MeOut:
    profile = service.get_profile(db, user)
    return MeOut(**UserOut.model_validate(user).model_dump(), profile=ProfileOut.model_validate(profile))


@router.get("/me", response_model=MeOut, tags=["me"])
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _me(db, user)


@router.patch("/me", response_model=MeOut, tags=["me"])
def patch_me(body: MePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    profile = service.get_profile(db, user)
    for field in ("name", "preferred_locale"):
        if field in data:
            setattr(user, field, data.pop(field))
    for field, value in data.items():
        setattr(profile, field, value)
    db.commit()
    return _me(db, user)


@router.get("/admin/users", response_model=list[UserOut], tags=["admin"])
def list_users(q: str = "", limit: int = 50, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc()).limit(min(limit, 200))
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    return db.scalars(stmt).all()


@router.patch("/admin/users/{user_id}", response_model=UserOut, tags=["admin"])
def patch_user(user_id: uuid.UUID, body: AdminUserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise NotFound("User not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(target, k, v)
    service.audit(db, admin.id, "user_update", "user", target.id, **changes)
    db.commit()
    return target


def _invite_out(invite: Invite) -> dict:
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "note": invite.note,
        "max_uses": invite.max_uses,
        "uses": invite.uses,
        "status": service.invite_status(invite),
        "expires_at": as_utc(invite.expires_at),
        "created_at": as_utc(invite.created_at),
    }


@router.post("/admin/invites", response_model=InviteCreatedOut, status_code=201, tags=["admin"])
def create_invite(body: InviteIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.send_email and not body.email:
        raise AppError("Add an email address to send the invite to")
    invite, code = service.create_invite(db, admin, body.email, body.role, body.note, body.max_uses, body.expires_in_days)
    link = f"{get_settings().public_web_url.rstrip('/')}/register?invite={quote(code)}"
    if body.send_email:
        queue_email(db, emails.invite(invite.email, link, code, invite.note, admin.name), created_by=admin.id)
    db.commit()
    return {**_invite_out(invite), "code": code, "link": link, "emailed": body.send_email}


@router.get("/admin/invites", response_model=list[InviteOut], tags=["admin"])
def list_invites(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_invite_out(i) for i in db.scalars(select(Invite).order_by(Invite.created_at.desc()).limit(200)).all()]


@router.delete("/admin/invites/{invite_id}", response_model=InviteOut, tags=["admin"])
def revoke_invite(invite_id: uuid.UUID, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    invite = service.revoke_invite(db, admin, invite_id)
    db.commit()
    return _invite_out(invite)
