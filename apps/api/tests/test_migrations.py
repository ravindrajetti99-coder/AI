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
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, Uuid, create_engine, inspect, make_url, pool, select

from app.core.db import Base, JSONType
from app.jobs.models import Job


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
    jobs = Job.__table__
    # Tables as they were at 0001 (the models describe head, which has more columns).
    users = Table(
        "users",
        MetaData(),
        Column("id", Uuid),
        *(Column(name, String) for name in ("email", "name", "password_hash", "role", "status", "preferred_locale")),
        *(Column(name, DateTime(timezone=True)) for name in ("created_at", "updated_at")),
    )
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


def test_content_engine_columns_backfill_existing_rows(scratch_url):
    """0005 gives existing courses the open policy and no targets, and existing nodes and links
    no tiers (meaning every exam stage)."""
    eng = create_engine(scratch_url, poolclass=pool.NullPool)
    cfg = alembic_config()

    def migrate(fn, rev):
        with eng.begin() as conn:
            cfg.attributes["connection"] = conn
            fn(cfg, rev)

    migrate(command.upgrade, "0004")
    meta = MetaData()
    courses = Table(
        "courses",
        meta,
        Column("id", Uuid),
        *(Column(n, String) for n in ("slug", "title", "description", "domain", "level", "status", "color")),
        Column("locales", JSONType),
        *(Column(n, DateTime(timezone=True)) for n in ("created_at", "updated_at")),
    )
    nodes = Table(
        "course_nodes",
        meta,
        *(Column(n, Uuid) for n in ("id", "course_id", "parent_id")),
        Column("node_type", String),
        Column("title", String),
        Column("position", Integer),
    )
    concepts = Table(
        "concepts",
        meta,
        Column("id", Uuid),
        *(Column(n, String) for n in ("slug", "title", "summary", "domain")),
        Column("difficulty_base", Float),
        *(Column(n, DateTime(timezone=True)) for n in ("created_at", "updated_at")),
    )
    links = Table("node_concepts", meta, *(Column(n, Uuid) for n in ("id", "node_id", "concept_id")), Column("weight", Float), Column("position", Integer))
    now = datetime.now(UTC)
    ids = {k: uuid.uuid4() for k in ("course", "node", "concept", "link")}
    with eng.begin() as conn:
        conn.execute(
            courses.insert().values(
                id=ids["course"],
                slug="c",
                title="C",
                description="",
                domain="academic",
                level="x",
                status="published",
                color="x",
                locales=["en"],
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(nodes.insert().values(id=ids["node"], course_id=ids["course"], parent_id=None, node_type="module", title="M", position=0))
        conn.execute(
            concepts.insert().values(id=ids["concept"], slug="k", title="K", summary="", domain="academic", difficulty_base=0.0, created_at=now, updated_at=now)
        )
        conn.execute(links.insert().values(id=ids["link"], node_id=ids["node"], concept_id=ids["concept"], weight=1.0, position=0))
    migrate(command.upgrade, "head")
    head = MetaData()
    with eng.connect() as conn:
        c = Table("courses", head, autoload_with=conn)
        n = Table("course_nodes", head, autoload_with=conn)
        nc = Table("node_concepts", head, autoload_with=conn)
        row = conn.execute(select(c.c.content_policy, c.c.content_targets)).one()
        assert (row.content_policy, _json(row.content_targets)) == ("open", {})
        assert [(r.key, _json(r.tiers)) for r in conn.execute(select(n.c.key, n.c.tiers))] == [(None, [])]
        assert [_json(r.tiers) for r in conn.execute(select(nc.c.tiers))] == [[]]
    migrate(command.downgrade, "0004")
    eng.dispose()


def _json(value):
    """Reflected JSON columns come back decoded on PostgreSQL and as text on SQLite."""
    import json

    return json.loads(value) if isinstance(value, str) else value
