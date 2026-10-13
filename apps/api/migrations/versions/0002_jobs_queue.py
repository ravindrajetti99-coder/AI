"""jobs queue: replace generation_jobs with the persistent jobs table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 10:07:41.665590

Existing generation jobs are copied with their ids (audit entries keep pointing at them) as
`generate.<kind>` jobs on the `content` queue. Jobs that were queued or running when the old
in-process runner stopped are queued again, so a worker finishes them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _empty_json() -> str:
    return "CAST('{}' AS JSONB)" if op.get_context().dialect.name == "postgresql" else "'{}'"


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("queue", sa.String(length=40), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("lease", sa.String(length=32), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("result", JSON, nullable=False),
        sa.Column("checkpoint", JSON, nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_jobs_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_jobs_dedupe_key")),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "queue", "run_at"], unique=False)
    op.create_index(op.f("ix_jobs_created_at"), "jobs", ["created_at"], unique=False)

    op.execute(
        f"""
        INSERT INTO jobs (id, kind, queue, payload, status, priority, run_at, attempts, max_attempts,
                          cancel_requested, result, checkpoint, error, created_by, created_at, finished_at, updated_at)
        SELECT id, 'generate.' || kind, 'content', params,
               CASE WHEN status IN ('queued', 'running') THEN 'queued' ELSE status END,
               0, created_at, 0, 3, FALSE, outputs, {_empty_json()}, error, created_by, created_at, finished_at,
               COALESCE(finished_at, created_at)
        FROM generation_jobs
        """
    )
    op.drop_table("generation_jobs")


def downgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("params", JSON, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("outputs", JSON, nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_generation_jobs_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_jobs")),
    )
    # Only generation jobs started by a person fit the old table (created_by was required there).
    op.execute(
        """
        INSERT INTO generation_jobs (id, created_by, kind, params, status, outputs, error, created_at, finished_at)
        SELECT id, created_by, SUBSTR(kind, 10), payload,
               CASE WHEN status = 'cancelled' THEN 'failed' ELSE status END,
               result, error, created_at, finished_at
        FROM jobs
        WHERE kind LIKE 'generate.%' AND created_by IS NOT NULL
        """
    )
    op.drop_index(op.f("ix_jobs_created_at"), table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
