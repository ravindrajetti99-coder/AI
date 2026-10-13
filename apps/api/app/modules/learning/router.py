import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.ai.engines import language, mentor
from app.core.db import as_utc, get_db
from app.core.deps import get_current_user, is_staff, rate_limit_ai
from app.core.errors import AppError, NotFound
from app.modules.assessment import service as qservice
from app.modules.assessment.models import Question
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Course
from app.modules.identity.models import LearnerProfile, User
from app.modules.learning import mastery as mm
from app.modules.learning import service
from app.modules.learning.models import Conversation, Enrollment, Message, ReviewItem, StudyPlanItem

router = APIRouter(tags=["me"])


@router.post("/courses/{slug}/enroll", status_code=201)
def enroll(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    course = catalog.get_course(db, slug)
    if not catalog.visible(course, is_staff(user)):
        raise NotFound("Course not found")
    existing = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id))
    if not existing:
        db.add(Enrollment(user_id=user.id, course_id=course.id))
        db.commit()
    return {"enrolled": True, "course": course.slug}


@router.delete("/courses/{slug}/enroll", status_code=204)
def unenroll(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    course = catalog.get_course(db, slug)
    db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.course_id == course.id).delete()
    db.commit()


@router.get("/me/enrollments")
def enrollments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"slug": c.slug, "title": c.title, "domain": c.domain, "color": c.color} for c in service.enrolled_courses(db, user.id)]


@router.get("/me/courses/{slug}/progress")
def progress(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.course_progress(db, user.id, catalog.get_course(db, slug))


def _review_row(item: ReviewItem, concept) -> dict:
    stage = mm.LADDER[min(item.stage, len(mm.LADDER) - 1)]
    return {
        "id": str(item.id),
        "concept": {"id": str(concept.id), "slug": concept.slug, "title": concept.title},
        "stage": item.stage,
        "stage_name": stage["name"],
        "stage_day": stage["day"],
        "due_at": as_utc(item.due_at).isoformat(),
        "last_result": item.last_result,
    }


@router.get("/me/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    courses = service.enrolled_courses(db, user.id)
    progress_rows = [service.course_progress(db, user.id, c) for c in courses]
    today = datetime.now(UTC).date()
    plan = db.scalars(select(StudyPlanItem).where(StudyPlanItem.user_id == user.id, StudyPlanItem.plan_date == today)).all()
    if not plan and courses:
        for c in courses:
            service.generate_plan(db, user.id, c, today)
        db.commit()
        plan = db.scalars(select(StudyPlanItem).where(StudyPlanItem.user_id == user.id, StudyPlanItem.plan_date == today)).all()
    due = service.due_reviews(db, user.id)
    return {
        "user": {"name": user.name, "role": user.role},
        "courses": progress_rows,
        "stats": service.activity_stats(db, user.id),
        "due_reviews": [_review_row(i, c) for i, c in due],
        "upcoming_reviews": [_review_row(i, c) for i, c in service.upcoming_reviews(db, user.id)],
        "plan": [_plan_row(p) for p in plan],
        "ai": gateway.ai_status(),
    }


def _plan_row(p: StudyPlanItem) -> dict:
    return {
        "id": str(p.id),
        "course_id": str(p.course_id),
        "kind": p.kind,
        "concept_id": str(p.concept_id) if p.concept_id else None,
        "title": p.title,
        "reason": p.reason,
        "minutes": p.minutes,
        "status": p.status,
        "date": p.plan_date.isoformat(),
    }


@router.get("/me/plan")
def get_plan(course: str, day: date | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = catalog.get_course(db, course)
    day = day or datetime.now(UTC).date()
    items = db.scalars(select(StudyPlanItem).where(StudyPlanItem.user_id == user.id, StudyPlanItem.course_id == c.id, StudyPlanItem.plan_date == day)).all()
    if not items:
        items = service.generate_plan(db, user.id, c, day)
        db.commit()
    return [_plan_row(p) for p in items]


@router.post("/me/plan/regenerate")
def regenerate_plan(course: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = catalog.get_course(db, course)
    items = service.generate_plan(db, user.id, c)
    db.commit()
    return [_plan_row(p) for p in items]


@router.get("/me/plan/week")
def week_plan(course: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A 7-day outlook: today's plan plus the revisions already scheduled for the week."""
    c = catalog.get_course(db, course)
    today = datetime.now(UTC).date()
    ids = {x.id for x, _, _ in catalog.course_concepts(db, c.id)}
    days = []
    for offset in range(7):
        d = today + timedelta(days=offset)
        start = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
        reviews = (
            db.execute(
                select(ReviewItem).where(
                    ReviewItem.user_id == user.id, ReviewItem.completed.is_(False), ReviewItem.due_at >= start, ReviewItem.due_at < start + timedelta(days=1)
                )
            )
            .scalars()
            .all()
        )
        days.append({"date": d.isoformat(), "reviews": sum(1 for r in reviews if r.concept_id in ids)})
    return days


class PlanStatusIn(BaseModel):
    status: str = Field(pattern="^(todo|done|skipped)$")


@router.patch("/me/plan/{item_id}")
def update_plan_item(item_id: uuid.UUID, body: PlanStatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(StudyPlanItem, item_id)
    if not item or item.user_id != user.id:
        raise NotFound("Plan item not found")
    item.status = body.status
    db.commit()
    return _plan_row(item)


@router.get("/me/mentor")
def mentor_note(course: str, user: User = Depends(rate_limit_ai), db: Session = Depends(get_db)):
    c = catalog.get_course(db, course)
    prog = service.course_progress(db, user.id, c)
    plan = get_plan(course, None, user, db)
    res = gateway.run(db, mentor.mentor_task(user.name, prog, plan, service.activity_stats(db, user.id)), user.id, user.role)
    db.commit()
    return {**res.data.model_dump(), "provider": res.provider}


# --------------------------------------------------------------------------- revision


@router.get("/me/reviews")
def reviews(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "due": [_review_row(i, c) for i, c in service.due_reviews(db, user.id)],
        "upcoming": [_review_row(i, c) for i, c in service.upcoming_reviews(db, user.id, days=30)],
        "ladder": mm.LADDER,
    }


@router.get("/me/reviews/{item_id}/questions")
def review_questions(item_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(ReviewItem, item_id)
    if not item or item.user_id != user.id:
        raise NotFound("Review item not found")
    picked, exclude = [], set()
    types = {"mcq", "multi", "assertion_reason", "numerical", "case_study"}
    for _ in range(3):
        q = service.choose_question(db, user.id, item.concept_id, types, exclude)
        if not q:
            break
        exclude.add(q.id)
        picked.append(qservice.public_question(q))
    db.commit()
    return {"review_id": str(item.id), "started_at": datetime.now(UTC).isoformat(), "questions": picked}


class ReviewDoneIn(BaseModel):
    started_at: datetime | None = None
    self_rating: str | None = Field(default=None, pattern="^(remembered|forgot)$")


@router.post("/me/reviews/{item_id}/complete")
def complete_review(item_id: uuid.UUID, body: ReviewDoneIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(ReviewItem, item_id)
    if not item or item.user_id != user.id:
        raise NotFound("Review item not found")
    if body.self_rating:
        success, correct, total = body.self_rating == "remembered", None, None
    else:
        since = as_utc(body.started_at) if body.started_at else datetime.now(UTC) - timedelta(hours=2)
        success, correct, total = service.review_success_from_attempts(db, user.id, item.concept_id, since)
        if not total:
            raise AppError("Answer the review questions first, or rate your recall")
    service.complete_review(db, item, success)
    db.commit()
    concept = item.concept_id
    return {
        "success": success,
        "correct": correct,
        "total": total,
        "completed": item.completed,
        "next_due": as_utc(item.due_at).isoformat(),
        "stage": item.stage,
        "concept_id": str(concept),
    }


# --------------------------------------------------------------------------- lessons, language, career


class LessonProgressIn(BaseModel):
    concept_id: uuid.UUID
    lesson_id: uuid.UUID | None = None
    level: int = Field(default=1, ge=1, le=4)
    seconds: int = Field(default=0, ge=0, le=36000)
    completed: bool = False


@router.post("/me/lessons/progress")
def lesson_progress(body: LessonProgressIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    catalog.get_concept(db, str(body.concept_id))
    service.record_lesson_view(db, user.id, body.concept_id, body.lesson_id, body.level, body.seconds, body.completed)
    db.commit()
    return {"ok": True}


class LanguageChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    target_language: str = "English"
    level: str = Field(default="A2", pattern="^(A1|A2|B1|B2|C1|C2)$")
    scenario: str = Field(default="", max_length=200)
    conversation_id: uuid.UUID | None = None


@router.post("/language/chat")
def language_chat(body: LanguageChatIn, user: User = Depends(rate_limit_ai), db: Session = Depends(get_db)):
    conv = db.get(Conversation, body.conversation_id) if body.conversation_id else None
    if conv and conv.user_id != user.id:
        raise NotFound("Conversation not found")
    if not conv:
        conv = Conversation(user_id=user.id, kind="language", context={"language": body.target_language, "level": body.level, "scenario": body.scenario})
        db.add(conv)
        db.flush()
    history = [
        {"role": m.role, "content": m.content} for m in db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)).all()
    ]
    helper = user.preferred_locale
    res = gateway.run(db, language.chat_task(body.target_language, body.level, body.scenario, history, body.message, helper), user.id, user.role)
    db.add(Message(conversation_id=conv.id, role="user", content=body.message))
    db.add(Message(conversation_id=conv.id, role="assistant", content=res.data.reply, meta={"corrections": [c.model_dump() for c in res.data.corrections]}))
    db.commit()
    return {"conversation_id": str(conv.id), **res.data.model_dump(), "provider": res.provider, "note": res.note}


@router.get("/language/speaking")
def speaking_items(language: str = "en-US", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    qs = db.scalars(select(Question).where(Question.qtype == "speaking", Question.status == "verified")).all()
    return [qservice.public_question(q) for q in qs if q.payload.get("language", "en-US").split("-")[0] == language.split("-")[0]]


class CareerIn(BaseModel):
    goal: str | None = Field(default=None, max_length=300)


@router.post("/career/guide")
def career_guide(body: CareerIn, user: User = Depends(rate_limit_ai), db: Session = Depends(get_db)):
    profile = db.get(LearnerProfile, user.id)
    goal = body.goal or (profile.career_goal if profile else "")
    if not goal:
        raise AppError("Tell us your career goal (or save it in your profile)")
    if profile and body.goal:
        profile.career_goal = body.goal
    courses = db.scalars(select(Course).where(Course.status == "published")).all()
    catalog_rows = [{"slug": c.slug, "title": c.title, "domain": c.domain} for c in courses]
    mastery_summary = []
    for c in service.enrolled_courses(db, user.id):
        p = service.course_progress(db, user.id, c)
        mastery_summary.append({"course": c.slug, "readiness": p["readiness"], "weak": [w["title"] for w in p["weak"]][:3]})
    res = gateway.run(db, mentor.career_task(goal, profile.education_level if profile else "", mastery_summary, catalog_rows), user.id, user.role)
    valid = {c.slug for c in courses}
    data = res.data.model_dump()
    for p in data["paths"]:
        p["course_slugs"] = [s for s in p["course_slugs"] if s in valid]
    db.commit()
    return {**data, "provider": res.provider}
