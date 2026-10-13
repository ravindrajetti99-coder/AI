"""Test harness: offline AI and per-test database snapshots, on SQLite or PostgreSQL.

The schema (and, for the seeded fixtures, all seed courses) is built once per session into
templates; each test starts from a fresh copy, so tests never see each other's writes.

SQLite (default) copies database files. Set EDU_TEST_POSTGRES_URL to an admin connection
(e.g. postgresql+psycopg://postgres:postgres@localhost:5432/postgres) to run the same suite
on PostgreSQL: the schema then comes from `alembic upgrade head` and each test gets a
database cloned with CREATE DATABASE ... TEMPLATE.
"""

import math
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import create_engine, make_url, pool

TMP = Path(tempfile.mkdtemp(prefix="eduverse-tests-"))
DB_FILE = TMP / "test.db"
PG_ADMIN_URL = os.environ.get("EDU_TEST_POSTGRES_URL", "")
PG_DB = "eduverse_test"
DB_URL = make_url(PG_ADMIN_URL).set(database=PG_DB).render_as_string(hide_password=False) if PG_ADMIN_URL else f"sqlite:///{DB_FILE}"
os.environ.update(
    {
        "EDU_ENV": "test",
        "EDU_DATABASE_URL": DB_URL,
        "EDU_UPLOAD_DIR": str(TMP / "uploads"),
        "EDU_ANTHROPIC_API_KEY": "",
        "EDU_OPENAI_API_KEY": "",
        "EDU_ADMIN_EMAIL": "",
        "EDU_ADMIN_PASSWORD": "",
        "EDU_CODE_RUNNER": "local",
        "EDU_BCRYPT_ROUNDS": "4",
        "EDU_REDIS_URL": "",
        "EDU_JOBS_EMBEDDED_WORKER": "false",  # tests run jobs explicitly with the `worker` fixture
    }
)

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import models  # noqa: E402, F401
from app.ai.providers import clients  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.deps import limiter  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.jobs.worker import Worker  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.assessment.models import Question  # noqa: E402
from app.modules.catalog.models import Concept  # noqa: E402
from app.modules.identity import service as identity  # noqa: E402
from app.modules.learning.models import Mastery  # noqa: E402
from app.seed.loader import load  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    return cfg


class SqliteSnapshots:
    def build_schema(self) -> None:
        engine.dispose()
        DB_FILE.unlink(missing_ok=True)
        Base.metadata.create_all(engine)

    def snapshot(self, name: str) -> None:
        engine.dispose()  # close pooled connections before touching the file
        shutil.copyfile(DB_FILE, TMP / f"{name}.db")

    def restore(self, name: str) -> None:
        engine.dispose()
        shutil.copyfile(TMP / f"{name}.db", DB_FILE)

    def cleanup(self) -> None:
        engine.dispose()


class PostgresSnapshots:
    def __init__(self) -> None:
        self.admin = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
        self.names: set[str] = set()

    def _recreate(self, target: str, template: str | None = None) -> None:
        engine.dispose()
        with self.admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)')
            c.exec_driver_sql(f'CREATE DATABASE "{target}"' + (f' TEMPLATE "{template}"' if template else ""))

    def build_schema(self) -> None:
        self._recreate(PG_DB)
        command.upgrade(alembic_config(), "head")  # the real migrations, not create_all

    def snapshot(self, name: str) -> None:
        self.names.add(f"{PG_DB}_{name}")
        self._recreate(f"{PG_DB}_{name}", template=PG_DB)

    def restore(self, name: str) -> None:
        self._recreate(PG_DB, template=f"{PG_DB}_{name}")

    def cleanup(self) -> None:
        engine.dispose()
        with self.admin.connect() as c:
            for db_name in [*self.names, PG_DB]:
                c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        self.admin.dispose()


@pytest.fixture(scope="session")
def snapshots():
    backend = PostgresSnapshots() if PG_ADMIN_URL else SqliteSnapshots()
    backend.build_schema()
    backend.snapshot("empty")
    with SessionLocal() as db:
        load(db)
    backend.snapshot("seeded")
    yield backend
    backend.cleanup()
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
def empty_db(snapshots):
    snapshots.restore("empty")
    yield
    engine.dispose()


@pytest.fixture
def seeded_db(snapshots):
    snapshots.restore("seeded")
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
def worker() -> Worker:
    """A job worker for this test; `worker.drain()` runs every due job in the calling thread."""
    w = Worker(name="test-worker")
    yield w
    w.backend.close()


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
