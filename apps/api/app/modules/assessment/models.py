"""Question bank, solution steps, rubrics and tests."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TimestampMixin

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
