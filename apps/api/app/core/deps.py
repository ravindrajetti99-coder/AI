"""Request dependencies: current user, role checks and rate limiting."""

import threading
import time
import uuid
from collections import defaultdict, deque

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import Forbidden, TooManyRequests, Unauthorized
from app.core.security import decode_access_token
from app.modules.identity.models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise Unauthorized("Missing bearer token")
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid or expired token") from exc
    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or user.status != "active":
        raise Unauthorized("User not found or inactive")
    return user


def require_roles(*roles: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise Forbidden(f"Requires role: {', '.join(roles)}")
        return user

    return _check


require_staff = require_roles("reviewer", "admin")
require_admin = require_roles("admin")


class RateLimiter:
    """Sliding-window limiter. In-process; swap for Redis when running several API replicas."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise TooManyRequests("Rate limit exceeded, slow down a little")
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit_auth(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    limiter.hit(f"auth:{ip}", get_settings().rate_limit_auth)


def rate_limit_ai(user: User = Depends(get_current_user)) -> User:
    limiter.hit(f"ai:{user.id}", get_settings().rate_limit_ai)
    return user
