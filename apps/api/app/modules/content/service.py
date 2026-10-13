import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.ai.engines import teacher
from app.modules.catalog.models import Concept, Course, CourseNode, ExamProfile, NodeConcept
from app.modules.content.models import Lesson


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
