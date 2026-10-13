import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import as_utc, get_db
from app.core.deps import get_current_user
from app.core.errors import AppError, Conflict, NotFound
from app.modules.assessment import grading, scoring, service
from app.modules.assessment.models import Question, QuestionConcept, Test, TestItem
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Concept
from app.modules.identity.models import User
from app.modules.labs.runner import run_python
from app.modules.learning import mastery as mm
from app.modules.learning import service as learning
from app.modules.learning.models import Attempt, HintUsage, TestAttempt

router = APIRouter(tags=["practice"])


def _concepts_of(db: Session, qid: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(Concept.id, Concept.slug, Concept.title)
        .join(QuestionConcept, QuestionConcept.concept_id == Concept.id)
        .where(QuestionConcept.question_id == qid)
    ).all()
    return [{"id": str(i), "slug": s, "title": t} for i, s, t in rows]


@router.get("/practice/next")
def next_question(
    course: str | None = None,
    concept: str | None = None,
    types: str = Query("", description="comma-separated question types"),
    exclude: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    type_set = {t for t in types.split(",") if t} or None
    excluded = {uuid.UUID(x) for x in exclude.split(",") if x}
    if concept:
        c = catalog.get_concept(db, concept)
        reason = "chosen concept"
    elif course:
        c, reason = learning.choose_concept(db, user.id, catalog.get_course(db, course).id)
        if not c:
            raise NotFound(reason)
    else:
        raise AppError("Pass course or concept")
    q = learning.choose_question(db, user.id, c.id, type_set, excluded)
    db.commit()
    if not q:
        return {"question": None, "concept": {"id": str(c.id), "title": c.title}, "reason": "No questions for this concept yet"}
    m = learning.get_mastery(db, user.id, c.id)
    db.commit()
    return {
        "question": service.public_question(q, _concepts_of(db, q.id)),
        "concept": {"id": str(c.id), "slug": c.slug, "title": c.title, "mastery": m.score, "label": mm.label(m.score, m.attempts)},
        "reason": reason,
    }


@router.get("/questions/{question_id}")
def get_question(question_id: uuid.UUID, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = service.get_question(db, question_id)
    return service.public_question(q, _concepts_of(db, q.id))


@router.get("/questions/{question_id}/steps/{n}")
def solution_steps(question_id: uuid.UUID, n: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Progressive help: step 1 hint ... step 6 common mistakes. Hints used reduce mastery gain."""
    if not 1 <= n <= 6:
        raise AppError("Step must be 1-6")
    q = service.get_question(db, question_id)
    usage = db.scalar(select(HintUsage).where(HintUsage.user_id == user.id, HintUsage.question_id == q.id))
    if not usage:
        usage = HintUsage(user_id=user.id, question_id=q.id, max_step=0)
        db.add(usage)
    if usage.consumed:  # a new round of help on a question already answered
        usage.consumed, usage.max_step = False, 0
    usage.max_step = max(usage.max_step, n)
    db.commit()
    return {"question_id": str(q.id), "steps": service.steps(db, q.id, n), "total_steps": len(service.steps(db, q.id))}


class AttemptIn(BaseModel):
    question_id: uuid.UUID
    response: dict
    seconds: int = Field(default=0, ge=0, le=36000)


@router.post("/attempts")
def submit_attempt(body: AttemptIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = service.get_question(db, body.question_id)
    g = grading.grade(db, q, body.response, user.id, user.role, practice=True)
    if not g.answered:
        raise AppError("Please answer the question before submitting")
    attempt, changes = learning.record_attempt(db, user.id, q, body.response, g.score, g.is_correct, body.seconds, g.feedback)
    db.commit()
    return {
        "attempt_id": str(attempt.id),
        "score": g.score,
        "is_correct": g.is_correct,
        "correct_answer": service.correct_answer(q),
        "explanation": q.explanation,
        "feedback": g.feedback,
        "steps": service.steps(db, q.id),
        "mastery": changes,
        "hints_used": attempt.hints_used,
    }


class RunIn(BaseModel):
    question_id: uuid.UUID
    code: str = Field(max_length=20000)


@router.post("/code/run")
def run_code(body: RunIn, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run only the visible example tests (no attempt is recorded)."""
    q = service.get_question(db, body.question_id)
    if q.qtype != "coding":
        raise AppError("Not a coding question")
    visible = [t for t in q.payload["tests"] if not t.get("hidden")]
    return run_python(body.code, q.payload["function_name"], visible).public()


# --------------------------------------------------------------------------- tests


def _test_items(db: Session, test_id: uuid.UUID) -> list[tuple[TestItem, Question]]:
    return [
        (i, q)
        for i, q in db.execute(
            select(TestItem, Question).join(Question, Question.id == TestItem.question_id).where(TestItem.test_id == test_id).order_by(TestItem.position)
        ).all()
    ]


@router.get("/courses/{slug}/tests")
def course_tests(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    course = catalog.get_course(db, slug)
    tests = db.scalars(select(Test).where(Test.course_id == course.id)).all()
    out = []
    for t in tests:
        items = _test_items(db, t.id)
        last = db.scalar(
            select(TestAttempt)
            .where(TestAttempt.user_id == user.id, TestAttempt.test_id == t.id, TestAttempt.status == "submitted")
            .order_by(TestAttempt.submitted_at.desc())
            .limit(1)
        )
        out.append(
            {
                "id": str(t.id),
                "slug": t.slug,
                "title": t.title,
                "kind": t.kind,
                "duration_minutes": t.duration_minutes,
                "questions": len(items),
                "max_marks": sum(i.marks for i, _ in items),
                "last_score": last.score if last else None,
            }
        )
    return out


@router.post("/tests/{test_id}/start")
def start_test(test_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    test = db.get(Test, test_id)
    if not test:
        raise NotFound("Test not found")
    ta = db.scalar(select(TestAttempt).where(TestAttempt.user_id == user.id, TestAttempt.test_id == test.id, TestAttempt.status == "in_progress"))
    if not ta:
        ta = TestAttempt(user_id=user.id, test_id=test.id)
        db.add(ta)
        db.commit()
    items = _test_items(db, test.id)
    return {
        "test_attempt_id": str(ta.id),
        "title": test.title,
        "instructions": test.instructions,
        "duration_minutes": test.duration_minutes,
        "started_at": as_utc(ta.started_at).isoformat(),
        "ends_at": (as_utc(ta.started_at) + timedelta(minutes=test.duration_minutes)).isoformat(),
        "answers": ta.answers,
        "items": [
            {"position": i.position, "section": i.section, "marks": i.marks, "negative_marks": i.negative_marks, "question": service.public_question(q)}
            for i, q in items
        ],
    }


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    response: dict


def _own_attempt(db: Session, attempt_id: uuid.UUID, user: User) -> TestAttempt:
    ta = db.get(TestAttempt, attempt_id)
    if not ta or ta.user_id != user.id:
        raise NotFound("Test attempt not found")
    return ta


@router.put("/test-attempts/{attempt_id}/answers")
def save_answer(attempt_id: uuid.UUID, body: AnswerIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ta = _own_attempt(db, attempt_id, user)
    if ta.status != "in_progress":
        raise Conflict("Test already submitted")
    answers = dict(ta.answers or {})
    answers[str(body.question_id)] = body.response
    ta.answers = answers
    db.commit()
    return {"saved": len(answers)}


@router.post("/test-attempts/{attempt_id}/submit")
def submit_test(attempt_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ta = _own_attempt(db, attempt_id, user)
    if ta.status == "submitted":
        return ta.report
    test = db.get(Test, ta.test_id)
    items = _test_items(db, test.id)
    started = as_utc(ta.started_at)
    elapsed = int((datetime.now(UTC) - started).total_seconds())
    per_q = max(1, elapsed // max(1, len(items)))
    sections: dict[str, dict] = defaultdict(lambda: {"score": 0.0, "max": 0.0, "correct": 0, "wrong": 0, "unattempted": 0})
    review, concept_scores = [], defaultdict(list)
    total = maximum = 0.0
    for item, q in items:
        resp = (ta.answers or {}).get(str(q.id), {})
        g = grading.grade(db, q, resp, user.id, user.role, practice=False) if resp else grading.Grade(0.0, False, {"answered": False}, False)
        result = scoring.ScoreResult(g.score, g.is_correct, {"answered": g.answered})
        marks = scoring.marks_for(result, item.marks, item.negative_marks)
        sec = sections[item.section]
        sec["max"] += item.marks
        sec["score"] += marks
        maximum += item.marks
        total += marks
        if not g.answered:
            sec["unattempted"] += 1
        elif g.is_correct:
            sec["correct"] += 1
        else:
            sec["wrong"] += 1
        if g.answered:
            learning.record_attempt(db, user.id, q, resp, g.score, g.is_correct, per_q, g.feedback, test_attempt_id=ta.id)
            for c in _concepts_of(db, q.id):
                concept_scores[c["title"]].append(g.score)
        review.append(
            {
                "question": service.public_question(q),
                "response": resp,
                "marks": marks,
                "max_marks": item.marks,
                "is_correct": g.is_correct,
                "answered": g.answered,
                "correct_answer": service.correct_answer(q),
                "explanation": q.explanation,
                "feedback": g.feedback,
            }
        )
    answered = sum(1 for r in review if r["answered"])
    weak = sorted([(sum(v) / len(v), k) for k, v in concept_scores.items() if sum(v) / len(v) < 0.5])
    report = {
        "test_attempt_id": str(ta.id),
        "title": test.title,
        "score": round(total, 2),
        "max_score": maximum,
        "percent": round(100 * total / maximum, 1) if maximum else 0.0,
        "accuracy": round(sum(1 for r in review if r["is_correct"]) / answered, 3) if answered else 0.0,
        "attempted": answered,
        "questions": len(items),
        "time_taken_seconds": elapsed,
        "sections": [{"section": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}} for k, v in sections.items()],
        "weak_concepts": [k for _, k in weak],
        "review": review,
    }
    ta.status, ta.submitted_at, ta.score, ta.max_score, ta.report = "submitted", datetime.now(UTC), round(total, 2), maximum, report
    db.commit()
    return report


@router.get("/test-attempts/{attempt_id}")
def get_test_attempt(attempt_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ta = _own_attempt(db, attempt_id, user)
    return ta.report if ta.status == "submitted" else {"status": ta.status, "answers": ta.answers}


@router.get("/me/attempts")
def my_attempts(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Attempt, Question.stem, Question.qtype)
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.user_id == user.id)
        .order_by(Attempt.attempted_at.desc())
        .limit(min(limit, 100))
    ).all()
    return [
        {
            "id": str(a.id),
            "question_id": str(a.question_id),
            "stem": stem[:160],
            "qtype": qt,
            "score": a.score,
            "is_correct": a.is_correct,
            "at": as_utc(a.attempted_at).isoformat(),
        }
        for a, stem, qt in rows
    ]
