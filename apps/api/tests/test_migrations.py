"""Migrations build exactly the schema the models describe, and downgrade cleanly."""

import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import PG_ADMIN_URL, alembic_config
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, create_engine, inspect, make_url, pool, select

from app.core.db import Base, JSONType
from app.jobs.models import Job
from app.modules.identity.models import User


@pytest.fixture
def scratch_url():
    if PG_ADMIN_URL:
        admin = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
        with admin.connect() as c:
            c.exec_driver_sql('DROP DATABASE IF EXISTS "eduverse_migrations" WITH (FORCE)')
            c.exec_driver_sql('CREATE DATABASE "eduverse_migrations"')
        yield make_url(PG_ADMIN_URL).set(database="eduverse_migrations").render_as_string(hide_password=False)
        with admin.connect() as c:
            c.exec_driver_sql('DROP DATABASE IF EXISTS "eduverse_migrations" WITH (FORCE)')
        admin.dispose()
    else:
        path = Path(tempfile.mkdtemp()) / "migrations.db"
        yield f"sqlite:///{path}"
        os.unlink(path)


def test_upgrade_matches_models_and_downgrade_is_clean(scratch_url):
    eng = create_engine(scratch_url, poolclass=pool.NullPool)
    cfg = alembic_config()
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        assert diff == []
        assert set(inspect(conn).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    with eng.connect() as conn:
        assert set(inspect(conn).get_table_names()) == {"alembic_version"}
    eng.dispose()


def test_generation_jobs_move_into_the_job_queue_and_back(scratch_url):
    """0002 copies old generation jobs into `jobs` (unfinished ones queued again) and back on downgrade."""
    eng = create_engine(scratch_url, poolclass=pool.NullPool)
    cfg = alembic_config()

    def migrate(fn, rev):
        with eng.begin() as conn:
            cfg.attributes["connection"] = conn
            fn(cfg, rev)

    migrate(command.upgrade, "0001")
    users, jobs = User.__table__, Job.__table__
    old_jobs = Table(
        "generation_jobs",
        MetaData(),
        *(Column(name, Uuid) for name in ("id", "created_by")),
        *(Column(name, String) for name in ("kind", "status", "error")),
        *(Column(name, JSONType) for name in ("params", "outputs")),
        *(Column(name, DateTime(timezone=True)) for name in ("created_at", "finished_at")),
    )
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    with eng.begin() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email="a@example.com",
                name="A",
                password_hash="x",
                role="admin",
                status="active",
                preferred_locale="en",
                created_at=now,
                updated_at=now,
            )
        )
        for status in ("queued", "running", "done", "failed"):
            conn.execute(
                old_jobs.insert().values(
                    id=uuid.uuid4(),
                    created_by=user_id,
                    kind="lessons",
                    params={"levels": [1]},
                    status=status,
                    outputs={"created": [{"type": "lesson"}]} if status == "done" else {},
                    error="boom" if status == "failed" else "",
                    created_at=now,
                    finished_at=now if status in ("done", "failed") else None,
                )
            )
    migrate(command.upgrade, "head")
    with eng.connect() as conn:
        rows = conn.execute(select(jobs.c.kind, jobs.c.queue, jobs.c.status, jobs.c.payload, jobs.c.result, jobs.c.error, jobs.c.created_by)).all()
    assert sorted(r.status for r in rows) == ["done", "failed", "queued", "queued"]  # the interrupted job runs again
    assert {(r.kind, r.queue, r.created_by) for r in rows} == {("generate.lessons", "content", user_id)}
    done = next(r for r in rows if r.status == "done")
    assert done.payload == {"levels": [1]} and done.result == {"created": [{"type": "lesson"}]}
    migrate(command.downgrade, "0001")
    with eng.connect() as conn:
        assert sorted(conn.execute(select(old_jobs.c.kind, old_jobs.c.status)).all()) == [("lessons", s) for s in ("done", "failed", "queued", "queued")]
    eng.dispose()
