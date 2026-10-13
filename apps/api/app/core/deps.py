"""Request dependencies: current user, role checks and rate limiting."""

import logging
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
logger = logging.getLogger(__name__)


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
    if payload.get("ver", 0) != user.token_version:
        raise Unauthorized("Your password was changed; please sign in again")
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
    """Sliding-window limiter for a single API process."""

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


# Atomic sliding window in a sorted set: drop old hits, refuse when full, else record this hit.
_SLIDING_WINDOW = """
local key, now, window, limit = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return 1
"""


class RedisRateLimiter:
    """The same sliding window shared by every API replica through Redis. If Redis is
    unreachable it falls back to per-process limiting rather than failing open."""

    def __init__(self, url: str) -> None:
        import redis

        self._errors = (redis.RedisError, OSError)
        self._redis = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._script = self._redis.register_script(_SLIDING_WINDOW)
        self._local = RateLimiter()

    def hit(self, key: str, limit: int, window: float = 60.0) -> None:
        try:
            allowed = self._script(keys=[f"rl:{key}"], args=[time.time(), window, limit, uuid.uuid4().hex])
        except self._errors:
            logger.warning("Redis unavailable; rate limiting per process", exc_info=False)
            self._local.hit(key, limit, window)
            return
        if not allowed:
            raise TooManyRequests("Rate limit exceeded, slow down a little")

    def reset(self) -> None:
        self._local.reset()
        try:
            for k in self._redis.scan_iter("rl:*"):
                self._redis.delete(k)
        except self._errors:
            pass


def make_limiter(redis_url: str) -> RateLimiter | RedisRateLimiter:
    return RedisRateLimiter(redis_url) if redis_url else RateLimiter()


limiter = make_limiter(get_settings().redis_url)


def client_ip(request: Request) -> str:
    """The caller's address (uvicorn resolves X-Forwarded-For from trusted proxies)."""
    return request.client.host if request.client else "unknown"


def rate_limit_auth(request: Request) -> None:
    limiter.hit(f"auth:{client_ip(request)}", get_settings().rate_limit_auth)


def rate_limit_ai(user: User = Depends(get_current_user)) -> User:
    limiter.hit(f"ai:{user.id}", get_settings().rate_limit_ai)
    return user
