"""Learning assets attached to concepts. Every AI asset carries a review status."""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TimestampMixin

# draft -> in_review -> verified -> retired. "manual" content is authored by staff.
ASSET_STATUSES = ("draft", "in_review", "verified", "retired")
LEVELS = {1: "Beginner", 2: "Intermediate", 3: "Advanced", 4: "Expert"}


class Lesson(IdMixin, TimestampMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("concept_id", "level", "locale", "version"),)

    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(10), default="en")
    # body: definition, explanation, examples[], diagram (mermaid), key_points[],
    # common_mistakes[], memory_technique, exam_relevance, check_questions[], citations[]
    body: Mapped[dict] = mapped_column(JSONType)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai | offline
    model: Mapped[str] = mapped_column(String(80), default="")
    prompt_version: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class Flashcard(IdMixin, TimestampMixin, Base):
    __tablename__ = "flashcards"

    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(10), default="en")
    source: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)


class Note(IdMixin, TimestampMixin, Base):
    """Summaries / revision notes, for a concept or an uploaded document."""

    __tablename__ = "notes"

    concept_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=True, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)


class ContentFlag(IdMixin, TimestampMixin, Base):
    __tablename__ = "content_flags"

    asset_type: Mapped[str] = mapped_column(String(20))
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    resolved: Mapped[int] = mapped_column(Integer, default=0)


class Formula(IdMixin, TimestampMixin, Base):
    """A formula or rule of a concept (the formula sheet is built from these)."""

    __tablename__ = "formulas"

    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    expression: Mapped[str] = mapped_column(Text)  # plain text with standard notation, e.g. "A = P(1 + r/100)^n"
    variables: Mapped[list] = mapped_column(JSONType, default=list)  # [{symbol, meaning}]
    conditions: Mapped[str] = mapped_column(Text, default="")  # when it applies
    example: Mapped[dict] = mapped_column(JSONType, default=dict)  # {problem, solution}
    locale: Mapped[str] = mapped_column(String(10), default="en")
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


SHORTCUT_KINDS = ("shortcut", "alternative", "elimination", "approximation", "memory")


class Shortcut(IdMixin, TimestampMixin, Base):
    """A short trick or alternative fast method, ideally tied to the exam pattern it cracks."""

    __tablename__ = "shortcuts"

    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    pattern_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("question_patterns.id", ondelete="SET NULL"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="shortcut")  # see SHORTCUT_KINDS
    rule: Mapped[str] = mapped_column(Text)
    when_to_use: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column(JSONType, default=list)
    example: Mapped[dict] = mapped_column(JSONType, default=dict)  # {problem, standard, shortcut, seconds_saved}
    pitfalls: Mapped[list] = mapped_column(JSONType, default=list)
    locale: Mapped[str] = mapped_column(String(10), default="en")
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
