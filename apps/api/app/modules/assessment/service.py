import hashlib
import re
import unicodedata
import uuid
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.assessment.models import DIFFICULTY_B, QUESTION_TYPES, STEP_KINDS, PyqSource, Question, QuestionConcept, QuestionPattern, Rubric, SolutionStep

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


def validate_item(key: str, item: dict) -> None:
    """Structural checks of a question item (seed files, imports): raises ValueError naming `key`."""
    qtype, p = item.get("qtype"), item.get("payload", {})
    if qtype not in QUESTION_TYPES:
        raise ValueError(f"{key}: unknown qtype {qtype!r}")
    if not item.get("stem", "").strip():
        raise ValueError(f"{key}: empty stem")
    if item.get("difficulty", "medium") not in DIFFICULTY_B:
        raise ValueError(f"{key}: unknown difficulty {item.get('difficulty')!r}")
    ids = [str(o["id"]).lower() for o in p.get("options", [])]
    if qtype in ("mcq", "assertion_reason", "case_study"):
        if len(ids) < 2 or len(set(ids)) != len(ids) or str(p.get("answer", "")).lower() not in ids:
            raise ValueError(f"{key}: answer {p.get('answer')!r} is not one of the options {ids}")
        texts = [o["text"] for o in p["options"]]
        if len(set(texts)) != len(texts):
            raise ValueError(f"{key}: duplicate option texts {texts}")
    elif qtype == "multi":
        answers = [str(a).lower() for a in p.get("answers", [])]
        if not answers or any(a not in ids for a in answers):
            raise ValueError(f"{key}: answers {answers} are not all options {ids}")
    elif qtype == "numerical":
        if not isinstance(p.get("answer"), (int, float)):
            raise ValueError(f"{key}: numerical answer must be a number")
    elif qtype == "coding":
        if not p.get("function_name") or not p.get("tests"):
            raise ValueError(f"{key}: coding questions need function_name and tests")
        if not any(not t.get("hidden") for t in p["tests"]):
            raise ValueError(f"{key}: coding questions need at least one visible example test")
    elif qtype in ("descriptive", "interview"):
        if not item.get("rubric"):
            raise ValueError(f"{key}: {qtype} questions need a rubric")
    elif qtype == "speaking":
        if not p.get("sentence"):
            raise ValueError(f"{key}: speaking questions need a sentence")


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
    external_key: str | None = None,
    pool: str = "practice",
    pattern_id: uuid.UUID | None = None,
    pyq_source_id: uuid.UUID | None = None,
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
        external_key=external_key,
        pool=pool,
        pattern_id=pattern_id,
        pyq_source_id=pyq_source_id,
        stem_hash=stem_hash(stem),
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


def replace_steps(db: Session, question_id: uuid.UUID, steps_map: dict | None) -> None:
    """Make the stored solution steps match `steps_map` ({kind: text})."""
    existing = {s.step_no: s for s in db.scalars(select(SolutionStep).where(SolutionStep.question_id == question_id))}
    for step_no, kind in enumerate(STEP_KINDS, start=1):
        body = (steps_map or {}).get(kind, "")
        step = existing.pop(step_no, None)
        if body and step:
            step.kind, step.body = kind, body
        elif body:
            db.add(SolutionStep(question_id=question_id, step_no=step_no, kind=kind, body=body))
        elif step:
            db.delete(step)
    for step in existing.values():
        db.delete(step)


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


# --------------------------------------------------------------------------- patterns and PYQs


def stem_hash(stem: str) -> str:
    """Fingerprint of a question stem that ignores case, spacing, punctuation and number formatting
    (1,00,000 vs 100000), so the same question imported twice or generated again is found."""
    text = unicodedata.normalize("NFKC", stem).lower()
    text = re.sub(r"(?<=\d)[,\s](?=\d)", "", text)  # digit grouping
    text = re.sub(r"[^\w]+", " ", text).strip()
    return hashlib.sha256(text.encode()).hexdigest()


def find_by_stem(db: Session, stem: str) -> Question | None:
    return db.scalar(select(Question).where(Question.stem_hash == stem_hash(stem), Question.status != "retired").order_by(Question.created_at).limit(1))


def patterns_for(db: Session, concept_ids: list[uuid.UUID], statuses=("verified",)) -> list[QuestionPattern]:
    if not concept_ids:
        return []
    return list(
        db.scalars(
            select(QuestionPattern)
            .where(QuestionPattern.concept_id.in_(concept_ids), QuestionPattern.status.in_(statuses))
            .order_by(QuestionPattern.concept_id, QuestionPattern.position)
        )
    )


def pattern_by_key(db: Session, key: str) -> QuestionPattern | None:
    return db.scalar(select(QuestionPattern).where(QuestionPattern.key == key))


def pyq_analysis(db: Session, concept_id: uuid.UUID) -> dict:
    """How often previous papers asked this concept: verified PYQs by year, tier and pattern."""
    rows = db.execute(
        select(Question.id, Question.pattern_id, Question.pyq_year, PyqSource.year, PyqSource.tier, PyqSource.exam)
        .join(QuestionConcept, QuestionConcept.question_id == Question.id)
        .outerjoin(PyqSource, PyqSource.id == Question.pyq_source_id)
        .where(QuestionConcept.concept_id == concept_id, Question.source == "pyq", Question.status == "verified")
    ).all()
    by_year: Counter = Counter()
    by_tier: Counter = Counter()
    by_pattern: Counter = Counter()
    for _qid, pattern_id, pyq_year, src_year, tier, _exam in rows:
        year = src_year or pyq_year
        if year:
            by_year[year] += 1
        if tier:
            by_tier[tier] += 1
        if pattern_id:
            by_pattern[str(pattern_id)] += 1
    years = sorted(by_year)
    return {
        "total": len(rows),
        "by_year": {str(y): by_year[y] for y in years},
        "by_tier": dict(sorted(by_tier.items())),
        "by_pattern": dict(by_pattern),
        "first_year": years[0] if years else None,
        "last_year": years[-1] if years else None,
    }


def verified_counts(db: Session, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Per concept: verified practice-pool, mock-pool and PYQ questions (for coverage)."""
    out: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"practice_questions": 0, "mock_questions": 0, "pyq_questions": 0})
    if not concept_ids:
        return out
    for cid, pool, source, n in db.execute(
        select(QuestionConcept.concept_id, Question.pool, Question.source, func.count())
        .join(Question, Question.id == QuestionConcept.question_id)
        .where(QuestionConcept.concept_id.in_(concept_ids), Question.status == "verified")
        .group_by(QuestionConcept.concept_id, Question.pool, Question.source)
    ).all():
        out[cid]["mock_questions" if pool == "mock" else "practice_questions"] += n
        if source == "pyq":
            out[cid]["pyq_questions"] += n
    for cid, n in db.execute(
        select(QuestionPattern.concept_id, func.count())
        .where(QuestionPattern.concept_id.in_(concept_ids), QuestionPattern.status == "verified")
        .group_by(QuestionPattern.concept_id)
    ).all():
        out[cid]["patterns"] = n
    return out
