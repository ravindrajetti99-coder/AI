"""Test harness: SQLite, offline AI, and per-test database snapshots.

The schema (and, for `seeded`, all seed courses) is built once per session into template
files; each test starts from a fresh copy, so tests never see each other's writes.
"""

import math
import os
import shutil
import tempfile
import uuid
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="eduverse-tests-"))
DB_FILE = TMP / "test.db"
os.environ.update(
    {
        "EDU_ENV": "test",
        "EDU_DATABASE_URL": f"sqlite:///{DB_FILE}",
        "EDU_UPLOAD_DIR": str(TMP / "uploads"),
        "EDU_ANTHROPIC_API_KEY": "",
        "EDU_OPENAI_API_KEY": "",
        "EDU_ADMIN_EMAIL": "",
        "EDU_ADMIN_PASSWORD": "",
        "EDU_CODE_RUNNER": "local",
        "EDU_BCRYPT_ROUNDS": "4",
    }
)

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import models  # noqa: E402, F401
from app.ai.providers import clients  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.deps import limiter  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.assessment.models import Question  # noqa: E402
from app.modules.catalog.models import Concept  # noqa: E402
from app.modules.identity import service as identity  # noqa: E402
from app.modules.learning.models import Mastery  # noqa: E402
from app.seed.loader import load  # noqa: E402


def _snapshot(target: Path) -> None:
    engine.dispose()  # close pooled connections before touching the file
    shutil.copyfile(DB_FILE, target)


def _restore(source: Path) -> None:
    engine.dispose()
    shutil.copyfile(source, DB_FILE)


@pytest.fixture(scope="session")
def templates() -> dict[str, Path]:
    engine.dispose()
    DB_FILE.unlink(missing_ok=True)
    Base.metadata.create_all(engine)
    _snapshot(TMP / "empty.db")
    with SessionLocal() as db:
        load(db)
    _snapshot(TMP / "seeded.db")
    yield {"empty": TMP / "empty.db", "seeded": TMP / "seeded.db"}
    engine.dispose()
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    """Fresh rate limits, default settings and the real provider registry for every test."""
    limiter.reset()
    settings = get_settings()
    for name in ("ai_primary", "ai_fallback", "anthropic_api_key", "openai_api_key", "code_runner", "admin_email", "admin_password"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(clients, "_REGISTRY", dict(clients._REGISTRY))
    yield


@pytest.fixture
def empty_db(templates):
    _restore(templates["empty"])
    yield
    engine.dispose()


@pytest.fixture
def seeded_db(templates):
    _restore(templates["seeded"])
    yield
    engine.dispose()


@pytest.fixture
def db(empty_db):
    with SessionLocal() as session:
        yield session


@pytest.fixture
def sdb(seeded_db):
    """A session on the seeded database."""
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client(empty_db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sclient(seeded_db):
    """A client on the seeded database."""
    with TestClient(app) as c:
        yield c


class Actor:
    """A signed-in user for API calls."""

    def __init__(self, client: TestClient, user_id: uuid.UUID, role: str, email: str):
        self.client, self.id, self.role, self.email = client, user_id, role, email
        self.headers = {"Authorization": f"Bearer {create_access_token(user_id, role)}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self.headers, **kw)

    def put(self, url, **kw):
        return self.client.put(url, headers=self.headers, **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self.headers, **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self.headers, **kw)


def make_actor(client: TestClient, role: str = "learner", email: str | None = None, name: str = "Test User") -> Actor:
    email = email or f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        user = identity.create_user(db, email, "password-123", name, role=role)
    return Actor(client, user.id, role, email)


@pytest.fixture
def learner(sclient) -> Actor:
    return make_actor(sclient, "learner", name="Ravi")


@pytest.fixture
def admin(sclient) -> Actor:
    return make_actor(sclient, "admin", name="Admin")


API = "/api/v1"


# --------------------------------------------------------------------------- content helpers


def concept_id(slug: str):
    with SessionLocal() as db:
        return db.scalar(select(Concept.id).where(Concept.slug == slug))


def answer_for(question_id: str) -> dict:
    """The correct response for a seeded objective question (tests peek at the key)."""
    with SessionLocal() as db:
        q = db.get(Question, uuid.UUID(question_id))
        if q.qtype == "multi":
            return {"choices": q.payload["answers"]}
        if q.qtype == "numerical":
            return {"value": q.payload["answer"]}
        return {"choice": q.payload["answer"]}


def wrong_for(question_id: str) -> dict:
    with SessionLocal() as db:
        q = db.get(Question, uuid.UUID(question_id))
        if q.qtype == "numerical":
            return {"value": q.payload["answer"] + 1000}
        if q.qtype == "multi":
            return {"choices": [o["id"] for o in q.payload["options"] if o["id"] not in q.payload["answers"]][:1]}
        return {"choice": next(o["id"] for o in q.payload["options"] if o["id"] != q.payload["answer"])}


def set_mastery(user_id, slug: str, score: float, attempts: int, theta: float | None = None):
    with SessionLocal() as db:
        m = db.get(Mastery, (user_id, concept_id(slug))) or Mastery(user_id=user_id, concept_id=concept_id(slug))
        m.score, m.attempts, m.correct, m.seconds = score, attempts, 0, 0
        m.theta = theta if theta is not None else math.log(score / (1 - score))
        m.last_seen_at = datetime.now(UTC)
        db.merge(m)
        db.commit()
