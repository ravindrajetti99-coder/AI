import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_admin
from app.core.errors import Conflict, NotFound
from app.modules.assessment.models import Question, QuestionConcept
from app.modules.catalog import service
from app.modules.catalog.models import (
    DOMAINS,
    Concept,
    ConceptEdge,
    Course,
    CourseNode,
    ExamProfile,
    NodeConcept,
)
from app.modules.catalog.schemas import (
    ConceptBrief,
    ConceptCreate,
    ConceptOut,
    CourseCreate,
    CourseDetail,
    CourseOut,
    ExamProfileCreate,
    ExamProfileOut,
    NodeCreate,
)
from app.modules.content.models import Flashcard, Lesson
from app.modules.identity.models import User

router = APIRouter(tags=["catalog"])


@router.get("/domains")
def domains(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Course.domain, func.count()).where(Course.status == "published").group_by(Course.domain)).all())
    return [{"code": k, "name": v, "course_count": counts.get(k, 0)} for k, v in DOMAINS.items()]


@router.get("/courses", response_model=list[CourseOut])
def list_courses(domain: str | None = None, q: str = "", db: Session = Depends(get_db)):
    stmt = select(Course).where(Course.status == "published").order_by(Course.domain, Course.title)
    if domain:
        stmt = stmt.where(Course.domain == domain)
    if q:
        stmt = stmt.where(Course.title.ilike(f"%{q}%"))
    courses = db.scalars(stmt).all()
    counts = service.course_counts(db, [c.id for c in courses])
    out = []
    for c in courses:
        item = CourseOut.model_validate(c)
        item.concept_count, item.question_count = counts.get(c.id, (0, 0))
        out.append(item)
    return out


@router.get("/courses/{slug}", response_model=CourseDetail)
def course_detail(slug: str, db: Session = Depends(get_db)):
    course = service.get_course(db, slug)
    detail = CourseDetail.model_validate(course)
    detail.concept_count, detail.question_count = service.course_counts(db, [course.id]).get(course.id, (0, 0))
    if course.exam_profile_id:
        detail.exam_profile = ExamProfileOut.model_validate(db.get(ExamProfile, course.exam_profile_id))
    detail.tree = service.build_tree(db, course.id)
    return detail


@router.get("/concepts/{concept_id}", response_model=ConceptOut)
def concept_detail(concept_id: str, db: Session = Depends(get_db)):
    c = service.get_concept(db, concept_id)
    levels: dict[str, set] = {}
    for level, locale in db.execute(select(Lesson.level, Lesson.locale).where(Lesson.concept_id == c.id, Lesson.status == "verified")).all():
        levels.setdefault(locale, set()).add(level)
    courses = db.execute(
        select(Course.slug, Course.title)
        .join(CourseNode, CourseNode.course_id == Course.id)
        .join(NodeConcept, NodeConcept.node_id == CourseNode.id)
        .where(NodeConcept.concept_id == c.id)
        .distinct()
    ).all()
    return ConceptOut(
        id=c.id,
        slug=c.slug,
        title=c.title,
        summary=c.summary,
        domain=c.domain,
        prerequisites=[ConceptBrief(id=p.id, slug=p.slug, title=p.title) for p in service.prerequisites(db, c.id)],
        unlocks=[ConceptBrief(id=p.id, slug=p.slug, title=p.title) for p in service.unlocks(db, c.id)],
        lesson_levels={k: sorted(v) for k, v in levels.items()},
        flashcard_count=db.scalar(select(func.count()).select_from(Flashcard).where(Flashcard.concept_id == c.id, Flashcard.status == "verified")) or 0,
        question_count=db.scalar(
            select(func.count())
            .select_from(QuestionConcept)
            .join(Question, Question.id == QuestionConcept.question_id)
            .where(QuestionConcept.concept_id == c.id, Question.status == "verified")
        )
        or 0,
        courses=[{"slug": s, "title": t} for s, t in courses],
    )


# ---------------------------------------------------------------- admin catalog


@router.post("/admin/exam-profiles", response_model=ExamProfileOut, status_code=201, tags=["admin"])
def create_exam_profile(body: ExamProfileCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(ExamProfile).where(ExamProfile.slug == body.slug)):
        raise Conflict("Exam profile slug exists")
    ep = ExamProfile(**body.model_dump())
    db.add(ep)
    db.commit()
    return ep


@router.post("/admin/courses", response_model=CourseOut, status_code=201, tags=["admin"])
def create_course(body: CourseCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.domain not in DOMAINS:
        raise NotFound(f"Unknown domain {body.domain}")
    if db.scalar(select(Course).where(Course.slug == body.slug)):
        raise Conflict("Course slug exists")
    data = body.model_dump(exclude={"exam_profile_slug"})
    if body.exam_profile_slug:
        ep = db.scalar(select(ExamProfile).where(ExamProfile.slug == body.exam_profile_slug))
        if not ep:
            raise NotFound("Exam profile not found")
        data["exam_profile_id"] = ep.id
    course = Course(**data)
    db.add(course)
    db.commit()
    return CourseOut.model_validate(course)


@router.post("/admin/courses/{course_id}/nodes", status_code=201, tags=["admin"])
def create_node(course_id: uuid.UUID, body: NodeCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not db.get(Course, course_id):
        raise NotFound("Course not found")
    if body.parent_id:
        parent = db.get(CourseNode, body.parent_id)
        if not parent or parent.course_id != course_id:
            raise NotFound("Parent node not in this course")
    node = CourseNode(course_id=course_id, **body.model_dump())
    db.add(node)
    db.commit()
    return {"id": node.id, "title": node.title, "node_type": node.node_type}


@router.post("/admin/concepts", status_code=201, tags=["admin"])
def create_concept(body: ConceptCreate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(Concept).where(Concept.slug == body.slug)):
        raise Conflict("Concept slug exists")
    concept = Concept(slug=body.slug, title=body.title, summary=body.summary, domain=body.domain)
    db.add(concept)
    db.flush()
    if body.node_id:
        if not db.get(CourseNode, body.node_id):
            raise NotFound("Node not found")
        db.add(NodeConcept(node_id=body.node_id, concept_id=concept.id, weight=body.weight))
    for slug in body.prerequisite_slugs:
        pre = db.scalar(select(Concept).where(Concept.slug == slug))
        if not pre:
            raise NotFound(f"Prerequisite {slug} not found")
        db.add(ConceptEdge(from_concept_id=pre.id, to_concept_id=concept.id))
    db.commit()
    return {"id": concept.id, "slug": concept.slug}
