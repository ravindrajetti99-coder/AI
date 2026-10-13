import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user, rate_limit_auth, require_admin
from app.core.errors import NotFound, Unauthorized
from app.modules.identity import service
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    AdminUserPatch,
    LoginIn,
    MeOut,
    MePatch,
    ProfileOut,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
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


@router.post("/auth/register", response_model=TokenOut, status_code=201, dependencies=[Depends(rate_limit_auth)])
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    user = service.create_user(db, body.email, body.password, body.name, locale=body.preferred_locale)
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
