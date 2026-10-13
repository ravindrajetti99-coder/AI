"""Learner activity and the learner model (mastery, revision, plans, conversations)."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, utcnow


class Enrollment(IdMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class LessonView(IdMixin, Base):
    __tablename__ = "lesson_views"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TestAttempt(IdMixin, Base):
    __tablename__ = "test_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress | submitted
    answers: Mapped[dict] = mapped_column(JSONType, default=dict)  # question_id -> response
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    report: Mapped[dict] = mapped_column(JSONType, default=dict)


class Attempt(IdMixin, Base):
    __tablename__ = "attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    test_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("test_attempts.id", ondelete="CASCADE"), nullable=True)
    response: Mapped[dict] = mapped_column(JSONType, default=dict)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1 fraction of credit
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[dict] = mapped_column(JSONType, default=dict)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class HintUsage(IdMixin, Base):
    __tablename__ = "hint_usage"
    __table_args__ = (UniqueConstraint("user_id", "question_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("questions.id", ondelete="CASCADE"))
    max_step: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Mastery(Base):
    __tablename__ = "mastery"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True)
    theta: Mapped[float] = mapped_column(Float, default=-1.0)  # ability on the logit scale
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1, derived from theta
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewItem(IdMixin, Base):
    """Spaced revision ladder: learn (day 1) -> revise (3) -> practice (7) -> test (15) -> recall (30)."""

    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("user_id", "concept_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"))
    stage: Mapped[int] = mapped_column(Integer, default=0)  # index into the ladder
    learned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_result: Mapped[str] = mapped_column(String(20), default="")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class StudyPlanItem(IdMixin, Base):
    __tablename__ = "study_plan_items"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("courses.id", ondelete="CASCADE"))
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # review | learn | practice | weak | test
    concept_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(String(240), default="")
    minutes: Mapped[int] = mapped_column(Integer, default=15)
    status: Mapped[str] = mapped_column(String(20), default="todo")


class Evaluation(IdMixin, Base):
    __tablename__ = "evaluations"

    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("attempts.id", ondelete="CASCADE"), unique=True)
    result: Mapped[dict] = mapped_column(JSONType)
    model: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(IdMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # tutor | language | career | mentor
    context: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(IdMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
