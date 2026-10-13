import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.assessment.models import DIFFICULTY_B, STEP_KINDS, Question, QuestionConcept, Rubric, SolutionStep

PUBLIC_PAYLOAD_KEYS = {
    "mcq": ("options", "passage"),
    "assertion_reason": ("options", "assertion", "reason"),
    "case_study": ("options", "passage"),
    "multi": ("options",),
    "numerical": ("unit",),
    "descriptive": ("max_marks", "word_limit"),
    "interview": ("max_marks", "word_limit"),
    "coding": ("language", "function_name", "starter_code"),
    "speaking": ("sentence", "language", "translation"),
}


def public_question(q: Question, concepts: list[dict] | None = None) -> dict:
    """Question as shown to a learner: no answer keys, hidden tests stay hidden."""
    payload = {k: q.payload[k] for k in PUBLIC_PAYLOAD_KEYS.get(q.qtype, ()) if k in q.payload}
    if q.qtype == "coding":
        payload["examples"] = [t for t in q.payload.get("tests", []) if not t.get("hidden")][:3]
    if q.qtype == "multi":
        payload["select_count_hint"] = "Select all that apply"
    return {
        "id": str(q.id),
        "qtype": q.qtype,
        "stem": q.stem,
        "payload": payload,
        "difficulty": q.difficulty,
        "source": q.source,
        "pyq_year": q.pyq_year,
        "concepts": concepts or [],
    }


def correct_answer(q: Question):
    p = q.payload
    return {
        "mcq": p.get("answer"),
        "assertion_reason": p.get("answer"),
        "case_study": p.get("answer"),
        "multi": p.get("answers"),
        "numerical": p.get("answer"),
    }.get(q.qtype)


def get_question(db: Session, qid: uuid.UUID, include_unverified: bool = False) -> Question:
    q = db.get(Question, qid)
    if not q or (not include_unverified and q.status not in ("verified",)):
        raise NotFound("Question not found")
    return q


def steps(db: Session, qid: uuid.UUID, upto: int = 6) -> list[dict]:
    rows = db.scalars(select(SolutionStep).where(SolutionStep.question_id == qid, SolutionStep.step_no <= upto).order_by(SolutionStep.step_no)).all()
    return [{"step": s.step_no, "kind": s.kind, "body": s.body} for s in rows if s.body]


def add_question(
    db: Session,
    *,
    qtype: str,
    stem: str,
    payload: dict,
    concept_ids: list[uuid.UUID],
    explanation: str = "",
    difficulty: str = "medium",
    steps_map: dict | None = None,
    rubric: list[dict] | None = None,
    model_answer: str = "",
    source: str = "manual",
    status: str = "verified",
    pyq_year: int | None = None,
    locale: str = "en",
) -> Question:
    q = Question(
        qtype=qtype,
        stem=stem,
        payload=payload,
        explanation=explanation,
        difficulty=difficulty,
        difficulty_b=DIFFICULTY_B.get(difficulty, 0.0),
        source=source,
        status=status,
        pyq_year=pyq_year,
        locale=locale,
    )
    db.add(q)
    db.flush()
    for cid in concept_ids:
        db.add(QuestionConcept(question_id=q.id, concept_id=cid))
    for i, kind in enumerate(STEP_KINDS, start=1):
        body = (steps_map or {}).get(kind, "")
        if body:
            db.add(SolutionStep(question_id=q.id, step_no=i, kind=kind, body=body))
    if rubric is not None:
        db.add(Rubric(question_id=q.id, criteria=rubric, model_answer=model_answer))
    return q


def save_generated(db: Session, gq, concept_id: uuid.UUID, source: str, status: str = "in_review") -> Question | None:
    """Persist an AI-generated question after structural checks; returns None when invalid."""
    payload: dict
    if gq.qtype in ("mcq", "assertion_reason"):
        ids = [o.id.lower() for o in gq.options]
        if len(ids) < 2 or gq.answer.lower() not in ids or len(set(ids)) != len(ids):
            return None
        payload = {"options": [o.model_dump() for o in gq.options], "answer": gq.answer.lower()}
    elif gq.qtype == "multi":
        ids = [o.id.lower() for o in gq.options]
        answers = [a.lower() for a in gq.answers]
        if not answers or any(a not in ids for a in answers):
            return None
        payload = {"options": [o.model_dump() for o in gq.options], "answers": sorted(set(answers))}
    elif gq.qtype == "numerical":
        if gq.numeric_answer is None:
            return None
        payload = {"answer": gq.numeric_answer, "tolerance": max(0.0, gq.tolerance), "unit": gq.unit}
    elif gq.qtype == "descriptive":
        if not gq.rubric_points:
            return None
        payload = {"max_marks": 10}
    else:
        return None
    rubric = None
    if gq.qtype == "descriptive":
        per = round(10 / len(gq.rubric_points), 2)
        rubric = [{"criterion": p[:120], "max_marks": per, "expected_points": [p]} for p in gq.rubric_points]
    return add_question(
        db,
        qtype=gq.qtype,
        stem=gq.stem,
        payload=payload,
        concept_ids=[concept_id],
        explanation=gq.explanation,
        difficulty=gq.difficulty,
        steps_map=gq.steps.model_dump(),
        rubric=rubric,
        model_answer=gq.model_answer,
        source=source,
        status=status,
    )
