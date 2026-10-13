"""Course tree and the shared concept graph.

Courses map their tree (module/chapter/topic/subtopic) onto concepts, which are shared
across courses so mastery earned once counts everywhere.
"""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TimestampMixin

DOMAINS = {
    "competitive": "Competitive exams",
    "professional": "Professional courses",
    "academic": "Academic education",
    "language": "Languages",
    "technology": "Technology & programming",
    "career": "Career skills",
}
NODE_TYPES = ("module", "chapter", "topic", "subtopic")
# Exam syllabi (app/seed/syllabus) name the top level "subject": Subject → Chapter → Topic → Sub topic → Concept.
SYLLABUS_NODE_TYPES = ("subject", "chapter", "topic", "subtopic")


class ExamProfile(IdMixin, TimestampMixin, Base):
    """An exam or skill-track pattern: sections, marking scheme, duration, levels."""

    __tablename__ = "exam_profiles"

    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(120), default="")
    domain: Mapped[str] = mapped_column(String(30))
    pattern: Mapped[dict] = mapped_column(JSONType, default=dict)


class Course(IdMixin, TimestampMixin, Base):
    __tablename__ = "courses"

    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(30), index=True)
    exam_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("exam_profiles.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(40), default="beginner")
    locales: Mapped[list] = mapped_column(JSONType, default=lambda: ["en"])
    status: Mapped[str] = mapped_column(String(20), default="published")  # published | draft (staff only)
    color: Mapped[str] = mapped_column(String(20), default="indigo")
    # "open": a learner may ask the AI for a missing lesson (saved as a draft others see too).
    # "reviewed_only" (exam courses): learners see verified content only; everything is generated
    # once by staff, reviewed, then served to every learner. The stricter policy of any course
    # that uses a concept applies to that concept.
    content_policy: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    # What "complete" means for this course: {"requirements": {default, subjects, chapters},
    # "mock_targets": {exam slug: mocks}} (from the syllabus files; read by the coverage report).
    content_targets: Mapped[dict] = mapped_column(JSONType, default=dict)


class CourseNode(IdMixin, Base):
    __tablename__ = "course_nodes"
    __table_args__ = (UniqueConstraint("course_id", "key"),)

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("course_nodes.id", ondelete="CASCADE"), nullable=True, index=True)
    node_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Stable id from the syllabus files (unique within a course), so titles can change safely.
    key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Exam stages this part of the syllabus belongs to (e.g. ["tier1", "tier2"]); empty = all.
    tiers: Mapped[list] = mapped_column(JSONType, default=list)


class Concept(IdMixin, TimestampMixin, Base):
    __tablename__ = "concepts"

    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(30))
    difficulty_base: Mapped[float] = mapped_column(Float, default=0.0)


class ConceptEdge(IdMixin, Base):
    __tablename__ = "concept_edges"
    __table_args__ = (UniqueConstraint("from_concept_id", "to_concept_id", "kind"),)

    from_concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    to_concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    # "prerequisite": from_concept must be learned before to_concept.
    kind: Mapped[str] = mapped_column(String(20), default="prerequisite")


class NodeConcept(IdMixin, Base):
    __tablename__ = "node_concepts"
    __table_args__ = (UniqueConstraint("node_id", "concept_id"),)

    node_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("course_nodes.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    # Exam importance (from previous-year analysis); drives readiness weighting.
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    tiers: Mapped[list] = mapped_column(JSONType, default=list)  # exam stages that test it here; empty = all


class CourseExam(IdMixin, Base):
    """The exam stages a course prepares for (e.g. SSC CGL Tier 1 and Tier 2)."""

    __tablename__ = "course_exams"
    __table_args__ = (UniqueConstraint("course_id", "exam_profile_id"),)

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    exam_profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("exam_profiles.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)


class ExamStrategy(IdMixin, TimestampMixin, Base):
    """How to approach the exam, a tier, a subject or a chapter: time split, attempt order,
    accuracy targets and tactics. Authored in the syllabus files or generated and reviewed."""

    __tablename__ = "exam_strategies"
    __table_args__ = (UniqueConstraint("course_id", "key"),)

    course_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("course_nodes.id", ondelete="CASCADE"), nullable=True, index=True)
    exam_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("exam_profiles.id", ondelete="SET NULL"), nullable=True)
    key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    # {time_allocation: {minutes, seconds_per_question}, attempt_order: [...], accuracy_target,
    #  target_attempts, tactics: [...], avoid: [...]}
    body: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
