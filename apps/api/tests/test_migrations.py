"""Migrations build exactly the schema the models describe, and downgrade cleanly."""

import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import PG_ADMIN_URL, alembic_config
from sqlalchemy import create_engine, inspect, make_url, pool

from app.core.db import Base


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
