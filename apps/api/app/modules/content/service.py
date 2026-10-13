import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.ai.engines import teacher
from app.modules.assessment import service as assessment
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Concept, Course, CourseNode, ExamProfile, NodeConcept
from app.modules.content.models import Flashcard, Formula, Lesson, Shortcut


def find_lesson(db: Session, concept_id: uuid.UUID, level: int, locale: str, statuses=("verified",)) -> Lesson | None:
    return db.scalar(
        select(Lesson)
        .where(Lesson.concept_id == concept_id, Lesson.level == level, Lesson.locale == locale, Lesson.status.in_(statuses))
        .order_by(Lesson.version.desc())
        .limit(1)
    )


def exam_context_for(db: Session, concept_id: uuid.UUID) -> tuple[str, uuid.UUID | None]:
    row = db.execute(
        select(Course, ExamProfile)
        .join(CourseNode, CourseNode.course_id == Course.id)
        .join(NodeConcept, NodeConcept.node_id == CourseNode.id)
        .outerjoin(ExamProfile, ExamProfile.id == Course.exam_profile_id)
        .where(NodeConcept.concept_id == concept_id)
        .limit(1)
    ).first()
    if not row:
        return "", None
    course, ep = row
    ctx = course.title
    if ep:
        ctx += f" | {ep.name}: {ep.pattern}"
    return ctx, course.id


def generate_lesson(db: Session, concept: Concept, level: int, locale: str, user_id=None, role="learner", status="in_review") -> tuple[Lesson, gateway.Result]:
    ctx, course_id = exam_context_for(db, concept.id)
    res = gateway.run(db, teacher.lesson_task(db, concept, level, locale, course_id, ctx), user_id, role)
    version = (db.scalar(select(func.max(Lesson.version)).where(Lesson.concept_id == concept.id, Lesson.level == level, Lesson.locale == locale)) or 0) + 1
    lesson = Lesson(
        concept_id=concept.id,
        level=level,
        locale=locale,
        body=res.data.model_dump(),
        source="offline" if res.offline else "ai",
        model=res.model,
        prompt_version=teacher.PROMPT_VERSION,
        status=status,
        version=version,
    )
    db.add(lesson)
    db.flush()
    return lesson, res


def lesson_out(lesson: Lesson, note: str = "") -> dict:
    return {
        "id": str(lesson.id),
        "concept_id": str(lesson.concept_id),
        "level": lesson.level,
        "locale": lesson.locale,
        "body": lesson.body,
        "status": lesson.status,
        "source": lesson.source,
        "verified": lesson.status == "verified",
        "note": note,
    }


# --------------------------------------------------------------------------- study pack


def formula_out(f: Formula) -> dict:
    return {
        "id": str(f.id),
        "key": f.key,
        "name": f.name,
        "expression": f.expression,
        "variables": f.variables,
        "conditions": f.conditions,
        "example": f.example,
        "status": f.status,
    }


def shortcut_out(s: Shortcut, pattern_keys: dict) -> dict:
    return {
        "id": str(s.id),
        "key": s.key,
        "title": s.title,
        "kind": s.kind,
        "rule": s.rule,
        "when_to_use": s.when_to_use,
        "steps": s.steps,
        "example": s.example,
        "pitfalls": s.pitfalls,
        "pattern": pattern_keys.get(s.pattern_id),
        "status": s.status,
    }


def study_pack(db: Session, concept: Concept, preview: bool = False) -> dict:
    """Everything stored for a concept beyond its lessons: formula sheet, shortcut sheet, exam
    patterns with previous-year counts, PYQ analysis and the exam strategies of its chapter and
    subject. Built only from stored, reviewed content (staff may preview items in review), so
    every learner gets the same pack without any AI call."""
    statuses = ("verified", "in_review") if preview else ("verified",)
    formulas = db.scalars(select(Formula).where(Formula.concept_id == concept.id, Formula.status.in_(statuses)).order_by(Formula.position, Formula.key)).all()
    patterns = assessment.patterns_for(db, [concept.id], statuses)
    shortcuts = db.scalars(
        select(Shortcut).where(Shortcut.concept_id == concept.id, Shortcut.status.in_(statuses)).order_by(Shortcut.position, Shortcut.key)
    ).all()
    pyq = assessment.pyq_analysis(db, concept.id)
    pattern_keys = {p.id: p.key for p in patterns}
    levels: dict[str, list[int]] = {}
    for level, locale in db.execute(select(Lesson.level, Lesson.locale).where(Lesson.concept_id == concept.id, Lesson.status == "verified").distinct()).all():
        levels.setdefault(locale, []).append(level)
    flashcards = db.scalar(select(func.count()).select_from(Flashcard).where(Flashcard.concept_id == concept.id, Flashcard.status == "verified")) or 0
    return {
        "concept": {"id": str(concept.id), "slug": concept.slug, "title": concept.title, "summary": concept.summary},
        "lesson_levels": {k: sorted(v) for k, v in sorted(levels.items())},
        "flashcard_count": flashcards,
        "formulas": [formula_out(f) for f in formulas],
        "shortcuts": [shortcut_out(s, pattern_keys) for s in shortcuts],
        "patterns": [
            {
                "id": str(p.id),
                "key": p.key,
                "title": p.title,
                "description": p.description,
                "example_stem": p.example_stem,
                "frequency": p.frequency,
                "tiers": p.tiers,
                "difficulty": p.difficulty,
                "target_seconds": p.target_seconds,
                "pyq_count": pyq["by_pattern"].get(str(p.id), 0),
                "status": p.status,
            }
            for p in patterns
        ],
        "pyq": {k: v for k, v in pyq.items() if k != "by_pattern"},
        "strategies": catalog.strategies_for_concept(db, concept.id, statuses),
        "reviewed_only": catalog.reviewed_only(db, concept.id),
        "preview": preview,
    }


def etag(data: dict) -> str:
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:32]
    return f'W/"{digest}"'
