"""Question bank, solution steps, rubrics and tests."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TimestampMixin, utcnow

# Objective types are auto-scored; descriptive/interview go to the AI examiner;
# coding runs tests in the code runner; speaking compares a transcript to a target sentence.
QUESTION_TYPES = (
    "mcq",
    "multi",
    "assertion_reason",
    "case_study",
    "numerical",
    "descriptive",
    "interview",
    "coding",
    "speaking",
)
OBJECTIVE_TYPES = {"mcq", "multi", "assertion_reason", "case_study", "numerical"}
DIFFICULTY_B = {"beginner": -2.0, "easy": -1.0, "medium": 0.0, "hard": 1.0, "expert": 2.0}
STEP_KINDS = ("hint", "concept", "approach", "solution", "shortcut", "mistakes")


class Question(IdMixin, TimestampMixin, Base):
    __tablename__ = "questions"

    qtype: Mapped[str] = mapped_column(String(20), index=True)
    stem: Mapped[str] = mapped_column(Text)
    # payload by type:
    #  mcq/assertion_reason/case_study: {options:[{id,text}], answer:"b", passage?}
    #  multi: {options:[...], answers:["a","c"]}
    #  numerical: {answer: 12.5, tolerance: 0.01, unit?}
    #  descriptive/interview: {max_marks, word_limit?}
    #  coding: {language, function_name, starter_code, tests:[{args:[...], expected:...}]}
    #  speaking: {sentence, language}
    payload: Mapped[dict] = mapped_column(JSONType)
    explanation: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    difficulty_b: Mapped[float] = mapped_column(Float, default=0.0)  # calibrated from learner data
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | pyq | ai | offline | generator
    pyq_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locale: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    times_answered: Mapped[int] = mapped_column(Integer, default=0)
    # Stable id for seeded or imported items (e.g. "profit-loss:gen:3") so loaders can upsert.
    external_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    # practice: adaptive practice and mocks; mock: held back for mock tests only.
    pool: Mapped[str] = mapped_column(String(20), default="practice", server_default="practice")
    pattern_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("question_patterns.id", ondelete="SET NULL"), nullable=True, index=True)
    shortcut_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("shortcuts.id", ondelete="SET NULL"), nullable=True)
    pyq_source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("pyq_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    # Normalised stem fingerprint: finds the same question imported twice or generated again.
    stem_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class QuestionConcept(IdMixin, Base):
    __tablename__ = "question_concepts"
    __table_args__ = (UniqueConstraint("question_id", "concept_id"),)

    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)


class SolutionStep(IdMixin, Base):
    __tablename__ = "solution_steps"
    __table_args__ = (UniqueConstraint("question_id", "step_no"),)

    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    step_no: Mapped[int] = mapped_column(Integer)  # 1..6
    kind: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)


class Rubric(IdMixin, Base):
    __tablename__ = "rubrics"

    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("questions.id", ondelete="CASCADE"), unique=True, index=True)
    # [{criterion, max_marks, expected_points:[...]}]
    criteria: Mapped[list] = mapped_column(JSONType)
    model_answer: Mapped[str] = mapped_column(Text, default="")


class Test(IdMixin, TimestampMixin, Base):
    __tablename__ = "tests"

    slug: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="mock")  # practice | sectional | mock
    course_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    instructions: Mapped[str] = mapped_column(Text, default="")


class TestItem(IdMixin, Base):
    __tablename__ = "test_items"

    test_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("questions.id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(String(80), default="General")
    marks: Mapped[float] = mapped_column(Float, default=1.0)
    negative_marks: Mapped[float] = mapped_column(Float, default=0.0)
    position: Mapped[int] = mapped_column(Integer, default=0)


PATTERN_FREQUENCIES = ("high", "medium", "low", "rare")


class QuestionPattern(IdMixin, TimestampMixin, Base):
    """A recurring way the exam asks about a concept ("successive discounts to one equivalent
    discount"). PYQs and practice questions point at it; shortcuts crack it."""

    __tablename__ = "question_patterns"

    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    example_stem: Mapped[str] = mapped_column(Text, default="")
    frequency: Mapped[str] = mapped_column(String(10), default="medium")  # expected; PYQ counts are computed
    tiers: Mapped[list] = mapped_column(JSONType, default=list)  # e.g. ["tier1", "tier2"]
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    target_seconds: Mapped[int] = mapped_column(Integer, default=60)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class PyqSource(IdMixin, Base):
    """One previous-year paper (exam, tier, date, shift) and where its questions came from."""

    __tablename__ = "pyq_sources"

    key: Mapped[str] = mapped_column(String(120), unique=True)  # e.g. ssc-cgl:tier1:2024-09-09:s1
    exam: Mapped[str] = mapped_column(String(60), index=True)
    tier: Mapped[str] = mapped_column(String(20), default="")
    year: Mapped[int] = mapped_column(Integer, index=True)
    exam_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD
    shift: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(300))  # e.g. "SSC official answer key"
    source_url: Mapped[str] = mapped_column(String(500), default="")
    licence: Mapped[str] = mapped_column(String(80))  # e.g. public-government-document, owned, licensed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PyqImport(IdMixin, Base):
    """An uploaded PYQ file and what importing it did. The file text is kept here (not on disk)
    so the worker that processes it may run on another machine."""

    __tablename__ = "pyq_imports"

    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(240))
    format: Mapped[str] = mapped_column(String(10))  # json | csv
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | done | failed
    payload: Mapped[str] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)  # created, updated, duplicates, invalid, unmapped
    errors: Mapped[list] = mapped_column(JSONType, default=list)  # [{row, error}]
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
