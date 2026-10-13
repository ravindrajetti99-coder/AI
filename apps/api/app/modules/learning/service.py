"""Learner model service: attempts -> mastery, revision ladder, adaptive selection, plans, dashboard."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.db import as_utc
from app.modules.assessment.models import Question, QuestionConcept
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Concept, ConceptEdge, Course, CourseNode, NodeConcept
from app.modules.identity.models import LearnerProfile
from app.modules.learning import mastery as mm
from app.modules.learning.models import (
    Attempt,
    Enrollment,
    HintUsage,
    LessonView,
    Mastery,
    ReviewItem,
    StudyPlanItem,
)


def now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- mastery


def concept_ids_for_question(db: Session, question_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == question_id)).all())


def get_mastery(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID) -> Mastery:
    m = db.get(Mastery, (user_id, concept_id))
    if not m:
        m = Mastery(user_id=user_id, concept_id=concept_id, theta=-1.0, score=mm.mastery_score(-1.0), attempts=0, correct=0, seconds=0)
        db.add(m)
        db.flush()
    return m


def ensure_review_item(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, when: datetime | None = None) -> ReviewItem:
    item = db.scalar(select(ReviewItem).where(ReviewItem.user_id == user_id, ReviewItem.concept_id == concept_id))
    if not item:
        learned = when or now()
        item = ReviewItem(user_id=user_id, concept_id=concept_id, stage=0, learned_at=learned, due_at=mm.first_due(learned))
        db.add(item)
        db.flush()
    return item


def consume_hints(db: Session, user_id: uuid.UUID, question_id: uuid.UUID) -> int:
    usage = db.scalar(select(HintUsage).where(HintUsage.user_id == user_id, HintUsage.question_id == question_id))
    if not usage or usage.consumed:
        return 0
    usage.consumed = True
    return usage.max_step


def apply_result(db: Session, user_id: uuid.UUID, question: Question, score: float, hints_used: int, seconds: int) -> list[dict]:
    """Update mastery for every concept the question tests, and calibrate the question."""
    changes = []
    thetas = []
    for concept_id in concept_ids_for_question(db, question.id):
        m = get_mastery(db, user_id, concept_id)
        before = m.score
        thetas.append(m.theta)
        m.theta = mm.update_ability(m.theta, question.difficulty_b, score, hints_used, seconds, target_seconds=90)
        m.score = mm.mastery_score(m.theta)
        m.attempts += 1
        m.correct += 1 if score >= 0.999 else 0
        m.seconds += max(0, seconds)
        m.last_seen_at = now()
        ensure_review_item(db, user_id, concept_id)
        changes.append({"concept_id": str(concept_id), "before": round(before, 4), "after": m.score, "label": mm.label(m.score, m.attempts)})
    if thetas:
        avg_theta = sum(thetas) / len(thetas)
        question.difficulty_b = mm.update_difficulty(question.difficulty_b, avg_theta, score)
    question.times_answered += 1
    return changes


def record_attempt(
    db: Session,
    user_id: uuid.UUID,
    question: Question,
    response: dict,
    score: float,
    is_correct: bool,
    seconds: int,
    feedback: dict,
    test_attempt_id: uuid.UUID | None = None,
) -> tuple[Attempt, list[dict]]:
    hints = consume_hints(db, user_id, question.id)
    attempt = Attempt(
        user_id=user_id,
        question_id=question.id,
        test_attempt_id=test_attempt_id,
        response=response,
        is_correct=is_correct,
        score=score,
        hints_used=hints,
        seconds=seconds,
        feedback=feedback,
    )
    db.add(attempt)
    db.flush()
    changes = apply_result(db, user_id, question, score, hints, seconds)
    return attempt, changes


def record_lesson_view(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, lesson_id, level: int, seconds: int, completed: bool) -> LessonView:
    view = LessonView(user_id=user_id, concept_id=concept_id, lesson_id=lesson_id, level=level, seconds=seconds, completed=completed)
    db.add(view)
    if completed:
        ensure_review_item(db, user_id, concept_id)
        get_mastery(db, user_id, concept_id)
    db.flush()
    return view


# --------------------------------------------------------------------------- revision


def due_reviews(db: Session, user_id: uuid.UUID, at: datetime | None = None) -> list[tuple[ReviewItem, Concept]]:
    at = at or now()
    rows = db.execute(
        select(ReviewItem, Concept)
        .join(Concept, Concept.id == ReviewItem.concept_id)
        .where(ReviewItem.user_id == user_id, ReviewItem.completed.is_(False), ReviewItem.due_at <= at)
        .order_by(ReviewItem.due_at)
    ).all()
    return [(r, c) for r, c in rows]


def upcoming_reviews(db: Session, user_id: uuid.UUID, days: int = 7) -> list[tuple[ReviewItem, Concept]]:
    at = now()
    rows = db.execute(
        select(ReviewItem, Concept)
        .join(Concept, Concept.id == ReviewItem.concept_id)
        .where(
            ReviewItem.user_id == user_id,
            ReviewItem.completed.is_(False),
            ReviewItem.due_at > at,
            ReviewItem.due_at <= at + timedelta(days=days),
        )
        .order_by(ReviewItem.due_at)
    ).all()
    return [(r, c) for r, c in rows]


def complete_review(db: Session, item: ReviewItem, success: bool) -> ReviewItem:
    stage, learned, due, done = mm.next_review(item.stage, as_utc(item.learned_at), success, now())
    item.stage, item.learned_at, item.due_at, item.completed = stage, learned, due, done
    item.last_result = "success" if success else "missed"
    return item


def review_success_from_attempts(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, since: datetime) -> tuple[bool, int, int]:
    rows = db.execute(
        select(Attempt.score)
        .join(QuestionConcept, QuestionConcept.question_id == Attempt.question_id)
        .where(Attempt.user_id == user_id, QuestionConcept.concept_id == concept_id, Attempt.attempted_at >= since)
        .order_by(Attempt.attempted_at.desc())
        .limit(5)
    ).all()
    total = len(rows)
    correct = sum(1 for (s,) in rows if s >= 0.999)
    return (total > 0 and correct / total >= 0.67), correct, total


# --------------------------------------------------------------------------- adaptive selection


def concept_states(db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, Mastery]:
    if not concept_ids:
        return {}
    return {m.concept_id: m for m in db.scalars(select(Mastery).where(Mastery.user_id == user_id, Mastery.concept_id.in_(concept_ids))).all()}


def prerequisites_met(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, threshold: float = 0.6) -> bool:
    pre_ids = list(db.scalars(select(ConceptEdge.from_concept_id).where(ConceptEdge.to_concept_id == concept_id, ConceptEdge.kind == "prerequisite")).all())
    if not pre_ids:
        return True
    states = concept_states(db, user_id, pre_ids)
    return all(states.get(p) is not None and states[p].score >= threshold for p in pre_ids)


def weakest_prerequisite(db: Session, user_id: uuid.UUID, concept_id: uuid.UUID) -> Concept | None:
    """Walk back through prerequisites to find the real gap behind a weak concept."""
    pre_ids = list(db.scalars(select(ConceptEdge.from_concept_id).where(ConceptEdge.to_concept_id == concept_id)).all())
    if not pre_ids:
        return None
    states = concept_states(db, user_id, pre_ids)
    weak = [(states[p].score if p in states else 0.0, p) for p in pre_ids]
    weak.sort()
    score, pid = weak[0]
    return db.get(Concept, pid) if score < mm.WEAK_THRESHOLD else None


def choose_concept(db: Session, user_id: uuid.UUID, course_id: uuid.UUID) -> tuple[Concept | None, str]:
    concepts = catalog.course_concepts(db, course_id)
    ids = [c.id for c, _, _ in concepts]
    states = concept_states(db, user_id, ids)
    # 1. due revisions in this course
    for _item, concept in due_reviews(db, user_id):
        if concept.id in ids:
            return concept, "revision due"
    # 2. weak concepts (fix the prerequisite gap first)
    weak = [(states[c.id].score, c) for c, _, _ in concepts if c.id in states and mm.label(states[c.id].score, states[c.id].attempts) == "weak"]
    if weak:
        weak.sort(key=lambda x: x[0])
        concept = weak[0][1]
        gap = weakest_prerequisite(db, user_id, concept.id)
        if gap:
            return gap, f"prerequisite gap behind {concept.title}"
        return concept, "weak area"
    # 3. the learning frontier: first concept in syllabus order not yet strong, prerequisites met
    for c, _, _ in concepts:
        st = states.get(c.id)
        if (st is None or st.score < mm.STRONG_THRESHOLD) and prerequisites_met(db, user_id, c.id):
            return c, "next in syllabus" if st is None or not st.attempts else "keep building"
    # 4. everything strong: stretch on the least-recently seen
    if concepts:
        seen = sorted(concepts, key=lambda row: as_utc(states[row[0].id].last_seen_at) if row[0].id in states else datetime.min.replace(tzinfo=UTC))
        return seen[0][0], "maintenance practice"
    return None, "course has no concepts"


def choose_question(
    db: Session, user_id: uuid.UUID, concept_id: uuid.UUID, types: set[str] | None = None, exclude: set[uuid.UUID] | None = None
) -> Question | None:
    stmt = (
        select(Question)
        .join(QuestionConcept, QuestionConcept.question_id == Question.id)
        .where(QuestionConcept.concept_id == concept_id, Question.status == "verified")
    )
    if types:
        stmt = stmt.where(Question.qtype.in_(types))
    candidates = db.scalars(stmt).all()
    if exclude:
        candidates = [q for q in candidates if q.id not in exclude]
    if not candidates:
        return None
    recent = set(db.scalars(select(Attempt.question_id).where(Attempt.user_id == user_id, Attempt.attempted_at >= now() - timedelta(hours=24))).all())
    theta = get_mastery(db, user_id, concept_id).theta
    target = mm.target_difficulty(theta)
    fresh = [q for q in candidates if q.id not in recent] or candidates
    fresh.sort(key=lambda q: (abs(q.difficulty_b - target), q.times_answered))
    return fresh[0]


# --------------------------------------------------------------------------- plans and dashboard


def enrolled_courses(db: Session, user_id: uuid.UUID) -> list[Course]:
    return list(
        db.scalars(
            select(Course).join(Enrollment, Enrollment.course_id == Course.id).where(Enrollment.user_id == user_id).order_by(Enrollment.started_at)
        ).all()
    )


def course_progress(db: Session, user_id: uuid.UUID, course: Course) -> dict:
    concepts = catalog.course_concepts(db, course.id)
    states = concept_states(db, user_id, [c.id for c, _, _ in concepts])
    total_w = sum(w for _, w, _ in concepts) or 1.0
    readiness = sum(w * (states[c.id].score if c.id in states and states[c.id].attempts else 0.0) for c, w, _ in concepts) / total_w
    attempted = [c for c, _, _ in concepts if c.id in states and states[c.id].attempts > 0]
    weak, strong, rows = [], [], []
    for c, w, _ in concepts:
        st = states.get(c.id)
        score = st.score if st and st.attempts else 0.0
        lab = mm.label(st.score, st.attempts) if st and st.attempts else "not_started"
        row = {
            "concept_id": str(c.id),
            "slug": c.slug,
            "title": c.title,
            "weight": w,
            "mastery": round(score, 3),
            "attempts": st.attempts if st else 0,
            "label": lab,
        }
        rows.append(row)
        if lab == "weak":
            weak.append(row)
        elif lab == "strong":
            strong.append(row)
    return {
        "course_id": str(course.id),
        "slug": course.slug,
        "title": course.title,
        "domain": course.domain,
        "readiness": round(readiness, 3),
        "coverage": round(len(attempted) / len(concepts), 3) if concepts else 0.0,
        "concepts": rows,
        "weak": weak,
        "strong": strong,
        "modules": module_mastery(db, course, states),
    }


def module_mastery(db: Session, course: Course, states: dict) -> list[dict]:
    nodes = db.scalars(select(CourseNode).where(CourseNode.course_id == course.id)).all()
    by_parent = defaultdict(list)
    for n in nodes:
        by_parent[n.parent_id].append(n)
    links = db.execute(select(NodeConcept.node_id, NodeConcept.concept_id, NodeConcept.weight).where(NodeConcept.node_id.in_([n.id for n in nodes]))).all()
    concepts_by_node = defaultdict(list)
    for node_id, cid, w in links:
        concepts_by_node[node_id].append((cid, w))

    def collect(node_id):
        items = list(concepts_by_node[node_id])
        for child in by_parent[node_id]:
            items += collect(child.id)
        return items

    out = []
    for module in sorted(by_parent[None], key=lambda n: n.position):
        items = collect(module.id)
        tw = sum(w for _, w in items) or 1.0
        score = sum(w * (states[c].score if c in states and states[c].attempts else 0.0) for c, w in items) / tw
        out.append({"node_id": str(module.id), "title": module.title, "mastery": round(score, 3), "concepts": len(items)})
    return out


def activity_stats(db: Session, user_id: uuid.UUID, days: int = 7) -> dict:
    since = now() - timedelta(days=days)
    rows = db.execute(select(Attempt.score, Attempt.seconds, Attempt.attempted_at).where(Attempt.user_id == user_id, Attempt.attempted_at >= since)).all()
    lesson_secs = db.scalar(select(func.coalesce(func.sum(LessonView.seconds), 0)).where(LessonView.user_id == user_id, LessonView.viewed_at >= since)) or 0
    active_days = sorted({as_utc(r[2]).date() for r in rows}, reverse=True)
    streak = 0
    day = now().date()
    all_days = set(
        as_utc(d).date()
        for (d,) in db.execute(select(Attempt.attempted_at).where(Attempt.user_id == user_id, Attempt.attempted_at >= now() - timedelta(days=365))).all()
    )
    while day in all_days:
        streak += 1
        day -= timedelta(days=1)
    return {
        "attempts": len(rows),
        "accuracy": round(sum(1 for r in rows if r[0] >= 0.999) / len(rows), 3) if rows else 0.0,
        "practice_minutes": round(sum(r[1] for r in rows) / 60),
        "lesson_minutes": round(lesson_secs / 60),
        "active_days": len(active_days),
        "streak_days": streak,
        "avg_seconds_per_question": round(sum(r[1] for r in rows) / len(rows)) if rows else 0,
    }


def generate_plan(db: Session, user_id: uuid.UUID, course: Course, plan_date: date | None = None) -> list[StudyPlanItem]:
    """Deterministic daily plan within the learner's minutes goal:
    overdue revisions -> weak concepts -> next new concepts -> mixed practice -> weekly mock."""
    plan_date = plan_date or now().date()
    db.query(StudyPlanItem).filter(
        and_(StudyPlanItem.user_id == user_id, StudyPlanItem.course_id == course.id, StudyPlanItem.plan_date == plan_date, StudyPlanItem.status == "todo")
    ).delete(synchronize_session=False)
    profile = db.get(LearnerProfile, user_id)
    budget = profile.daily_minutes_goal if profile else 60
    concepts = catalog.course_concepts(db, course.id)
    ids = {c.id for c, _, _ in concepts}
    states = concept_states(db, user_id, list(ids))
    items: list[StudyPlanItem] = []

    def add(kind, concept, title, reason, minutes):
        nonlocal budget
        if budget < minutes:
            return False
        items.append(
            StudyPlanItem(
                user_id=user_id,
                course_id=course.id,
                plan_date=plan_date,
                kind=kind,
                concept_id=concept.id if concept else None,
                title=title,
                reason=reason,
                minutes=minutes,
            )
        )
        budget -= minutes
        return True

    for item, concept in due_reviews(db, user_id, at=datetime.combine(plan_date, datetime.max.time(), tzinfo=UTC)):
        if concept.id in ids:
            stage = mm.LADDER[min(item.stage, len(mm.LADDER) - 1)]["name"].replace("_", " ")
            add("review", concept, f"Revise: {concept.title}", f"Spaced revision ({stage})", 10)
    for c, _, _ in sorted(concepts, key=lambda r: states[r[0].id].score if r[0].id in states else 1.0):
        st = states.get(c.id)
        if st and st.attempts >= mm.MIN_ATTEMPTS_FOR_LABEL and st.score < mm.WEAK_THRESHOLD:
            gap = weakest_prerequisite(db, user_id, c.id)
            if gap:
                add("weak", gap, f"Fix the base: {gap.title}", f"Weak prerequisite of {c.title}", 15)
            add("weak", c, f"Strengthen: {c.title}", f"Mastery {round(st.score * 100)}% after {st.attempts} attempts", 15)
    # A mastery row with no attempts only means the learner opened the concept; it is still new.
    started = {cid: st for cid, st in states.items() if st.attempts > 0}
    new_added = 0
    for c, _, _ in concepts:
        if new_added >= 2:
            break
        if c.id not in started and prerequisites_met(db, user_id, c.id):
            if add("learn", c, f"Learn: {c.title}", "Next in your syllabus", 20):
                new_added += 1
    # Concepts already under way that are neither weak (handled above) nor strong yet.
    in_progress = [
        c
        for c, _, _ in concepts
        if c.id in started
        and started[c.id].score < mm.STRONG_THRESHOLD
        and not (started[c.id].attempts >= mm.MIN_ATTEMPTS_FOR_LABEL and started[c.id].score < mm.WEAK_THRESHOLD)
    ]
    for c in in_progress[:2]:
        st = started[c.id]
        reason = "Push mastery past 80%" if st.attempts >= mm.MIN_ATTEMPTS_FOR_LABEL else f"Keep building: {st.attempts} attempt(s) so far"
        add("practice", c, f"Practice: {c.title}", reason, 10)
    if plan_date.weekday() == 6:
        add("test", None, "Weekly mock test", "Measure exam readiness", 30)
    for it in items:
        db.add(it)
    db.flush()
    return items
