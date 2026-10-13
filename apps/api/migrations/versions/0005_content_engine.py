"""content engine: formulas, shortcuts, question patterns, exam strategies, PYQ sources and imports

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13 12:01:06.964445

Adds the concept-level content model that exam courses (SSC CGL first) are built from, the link
from a course to the exam stages it prepares for, stable syllabus keys on course nodes, the
course content policy (existing courses stay "open") and, on questions, the practice/mock pool,
pattern, shortcut and PYQ paper links and a stem fingerprint for duplicate detection.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _empty_list() -> sa.TextClause:
    return sa.text("CAST('[]' AS JSONB)" if op.get_context().dialect.name == "postgresql" else "'[]'")


def _empty_object() -> sa.TextClause:
    return sa.text("CAST('{}' AS JSONB)" if op.get_context().dialect.name == "postgresql" else "'{}'")


def upgrade() -> None:
    op.create_table(
        "pyq_sources",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("exam", sa.String(length=60), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.String(length=10), nullable=False),
        sa.Column("shift", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("licence", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pyq_sources")),
        sa.UniqueConstraint("key", name=op.f("uq_pyq_sources_key")),
    )
    with op.batch_alter_table("pyq_sources", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pyq_sources_exam"), ["exam"], unique=False)
        batch_op.create_index(batch_op.f("ix_pyq_sources_year"), ["year"], unique=False)

    op.create_table(
        "formulas",
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("variables", JSON, nullable=False),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column("example", JSON, nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], name=op.f("fk_formulas_concept_id_concepts"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_formulas")),
        sa.UniqueConstraint("key", name=op.f("uq_formulas_key")),
    )
    with op.batch_alter_table("formulas", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_formulas_concept_id"), ["concept_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_formulas_status"), ["status"], unique=False)

    op.create_table(
        "pyq_imports",
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("summary", JSON, nullable=False),
        sa.Column("errors", JSON, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_pyq_imports_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pyq_imports")),
    )
    with op.batch_alter_table("pyq_imports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pyq_imports_created_at"), ["created_at"], unique=False)

    op.create_table(
        "question_patterns",
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("example_stem", sa.Text(), nullable=False),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("tiers", JSON, nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("target_seconds", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], name=op.f("fk_question_patterns_concept_id_concepts"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_patterns")),
        sa.UniqueConstraint("key", name=op.f("uq_question_patterns_key")),
    )
    with op.batch_alter_table("question_patterns", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_question_patterns_concept_id"), ["concept_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_question_patterns_status"), ["status"], unique=False)

    op.create_table(
        "course_exams",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("exam_profile_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name=op.f("fk_course_exams_course_id_courses"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_profile_id"], ["exam_profiles.id"], name=op.f("fk_course_exams_exam_profile_id_exam_profiles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_exams")),
        sa.UniqueConstraint("course_id", "exam_profile_id", name=op.f("uq_course_exams_course_id_exam_profile_id")),
    )
    with op.batch_alter_table("course_exams", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_course_exams_course_id"), ["course_id"], unique=False)

    op.create_table(
        "shortcuts",
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("pattern_id", sa.Uuid(), nullable=True),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("when_to_use", sa.Text(), nullable=False),
        sa.Column("steps", JSON, nullable=False),
        sa.Column("example", JSON, nullable=False),
        sa.Column("pitfalls", JSON, nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], name=op.f("fk_shortcuts_concept_id_concepts"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pattern_id"], ["question_patterns.id"], name=op.f("fk_shortcuts_pattern_id_question_patterns"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shortcuts")),
        sa.UniqueConstraint("key", name=op.f("uq_shortcuts_key")),
    )
    with op.batch_alter_table("shortcuts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shortcuts_concept_id"), ["concept_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shortcuts_pattern_id"), ["pattern_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shortcuts_status"), ["status"], unique=False)

    op.create_table(
        "exam_strategies",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("exam_profile_id", sa.Uuid(), nullable=True),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", JSON, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name=op.f("fk_exam_strategies_course_id_courses"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exam_profile_id"], ["exam_profiles.id"], name=op.f("fk_exam_strategies_exam_profile_id_exam_profiles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["node_id"], ["course_nodes.id"], name=op.f("fk_exam_strategies_node_id_course_nodes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_strategies")),
        sa.UniqueConstraint("course_id", "key", name=op.f("uq_exam_strategies_course_id_key")),
    )
    with op.batch_alter_table("exam_strategies", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_exam_strategies_course_id"), ["course_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_exam_strategies_node_id"), ["node_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_exam_strategies_status"), ["status"], unique=False)

    # The JSON defaults only fill existing rows (they are dropped below); the app always writes tiers.
    with op.batch_alter_table("course_nodes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("key", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("tiers", JSON, server_default=_empty_list(), nullable=False))
        batch_op.create_unique_constraint(batch_op.f("uq_course_nodes_course_id_key"), ["course_id", "key"])
    with op.batch_alter_table("node_concepts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tiers", JSON, server_default=_empty_list(), nullable=False))
    for table in ("course_nodes", "node_concepts"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column("tiers", server_default=None)

    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_policy", sa.String(length=20), server_default="open", nullable=False))
        batch_op.add_column(sa.Column("content_targets", JSON, server_default=_empty_object(), nullable=False))
    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.alter_column("content_targets", server_default=None)

    with op.batch_alter_table("questions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pool", sa.String(length=20), server_default="practice", nullable=False))
        batch_op.add_column(sa.Column("pattern_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("shortcut_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("pyq_source_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("stem_hash", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_questions_pattern_id"), ["pattern_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_questions_pyq_source_id"), ["pyq_source_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_questions_stem_hash"), ["stem_hash"], unique=False)
        batch_op.create_foreign_key(batch_op.f("fk_questions_pyq_source_id_pyq_sources"), "pyq_sources", ["pyq_source_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key(batch_op.f("fk_questions_shortcut_id_shortcuts"), "shortcuts", ["shortcut_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key(batch_op.f("fk_questions_pattern_id_question_patterns"), "question_patterns", ["pattern_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("questions", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_questions_pattern_id_question_patterns"), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f("fk_questions_shortcut_id_shortcuts"), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f("fk_questions_pyq_source_id_pyq_sources"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_questions_stem_hash"))
        batch_op.drop_index(batch_op.f("ix_questions_pyq_source_id"))
        batch_op.drop_index(batch_op.f("ix_questions_pattern_id"))
        batch_op.drop_column("stem_hash")
        batch_op.drop_column("pyq_source_id")
        batch_op.drop_column("shortcut_id")
        batch_op.drop_column("pattern_id")
        batch_op.drop_column("pool")

    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.drop_column("content_targets")
        batch_op.drop_column("content_policy")

    with op.batch_alter_table("node_concepts", schema=None) as batch_op:
        batch_op.drop_column("tiers")
    with op.batch_alter_table("course_nodes", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_course_nodes_course_id_key"), type_="unique")
        batch_op.drop_column("tiers")
        batch_op.drop_column("key")

    with op.batch_alter_table("exam_strategies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_exam_strategies_status"))
        batch_op.drop_index(batch_op.f("ix_exam_strategies_node_id"))
        batch_op.drop_index(batch_op.f("ix_exam_strategies_course_id"))

    op.drop_table("exam_strategies")
    with op.batch_alter_table("shortcuts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shortcuts_status"))
        batch_op.drop_index(batch_op.f("ix_shortcuts_pattern_id"))
        batch_op.drop_index(batch_op.f("ix_shortcuts_concept_id"))

    op.drop_table("shortcuts")
    with op.batch_alter_table("course_exams", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_course_exams_course_id"))

    op.drop_table("course_exams")
    with op.batch_alter_table("question_patterns", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_question_patterns_status"))
        batch_op.drop_index(batch_op.f("ix_question_patterns_concept_id"))

    op.drop_table("question_patterns")
    with op.batch_alter_table("pyq_imports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pyq_imports_created_at"))

    op.drop_table("pyq_imports")
    with op.batch_alter_table("formulas", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_formulas_status"))
        batch_op.drop_index(batch_op.f("ix_formulas_concept_id"))

    op.drop_table("formulas")
    with op.batch_alter_table("pyq_sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pyq_sources_year"))
        batch_op.drop_index(batch_op.f("ix_pyq_sources_exam"))

    op.drop_table("pyq_sources")
