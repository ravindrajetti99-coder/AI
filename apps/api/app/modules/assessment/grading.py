"""Grades any question type: objective rules, speaking match, code tests, or the AI examiner."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.ai.engines import code_review, examiner
from app.ai.engines import questions as qengine
from app.core.errors import AppError
from app.modules.assessment import scoring
from app.modules.assessment.models import OBJECTIVE_TYPES, Question, Rubric, SolutionStep
from app.modules.labs.runner import run_python


@dataclass
class Grade:
    score: float
    is_correct: bool
    feedback: dict = field(default_factory=dict)
    answered: bool = True


def _option_text(payload: dict, oid) -> str:
    for o in payload.get("options", []):
        if str(o["id"]).lower() == str(oid).lower():
            return f"({o['id']}) {o['text']}"
    return str(oid)


def grade(db: Session, q: Question, response: dict, user_id=None, role="learner", practice: bool = True) -> Grade:
    if q.qtype in OBJECTIVE_TYPES:
        r = scoring.score_objective(q.qtype, q.payload, response)
        fb = {**r.detail, "explanation": q.explanation}
        if practice and r.detail.get("answered") and not r.is_correct and q.qtype in ("mcq", "assertion_reason", "case_study"):
            mistakes = db.scalar(select(SolutionStep.body).where(SolutionStep.question_id == q.id, SolutionStep.kind == "mistakes")) or ""
            task = qengine.mistake_note_task(
                q.stem, _option_text(q.payload, q.payload["answer"]), _option_text(q.payload, response.get("choice")), q.explanation, mistakes
            )
            res = gateway.run(db, task, user_id, role)
            fb["mistake_note"] = res.data.note
        return Grade(r.score, r.is_correct, fb, r.detail.get("answered", False))

    if q.qtype == "speaking":
        r = scoring.score_speaking(q.payload["sentence"], response.get("transcript", ""))
        return Grade(r.score, r.is_correct, {**r.detail, "target": q.payload["sentence"]}, r.detail.get("answered", False))

    if q.qtype == "coding":
        code = response.get("code", "")
        if not code.strip():
            return Grade(0.0, False, {"answered": False}, False)
        run = run_python(code, q.payload["function_name"], q.payload["tests"])
        score = run.passed / run.total if run.total else 0.0
        fb = {"answered": True, "run": run.public()}
        if practice:
            review = gateway.run(db, code_review.review_task(code, q.payload.get("language", "python"), q.stem, run.summary()), user_id, role)
            fb["review"] = review.data.model_dump()
            fb["review_source"] = review.provider
        return Grade(round(score, 4), run.ok and run.passed == run.total and run.total > 0, fb)

    if q.qtype in ("descriptive", "interview"):
        answer = response.get("text", "")
        if not answer.strip():
            return Grade(0.0, False, {"answered": False}, False)
        rubric = db.scalar(select(Rubric).where(Rubric.question_id == q.id))
        if not rubric:
            raise AppError("This question has no rubric yet")
        task = examiner.evaluate_task(q.stem, rubric.criteria, rubric.model_answer, answer, q.payload.get("word_limit"))
        res = gateway.run(db, task, user_id, role)
        ev = res.data.model_dump()
        frac = ev["total"] / ev["max_total"] if ev["max_total"] else 0.0
        frac = max(0.0, min(1.0, frac))
        return Grade(round(frac, 4), frac >= 0.6, {"answered": True, "evaluation": ev, "evaluated_by": res.provider, "note": res.note})

    raise AppError(f"Unsupported question type {q.qtype}")
