"""Staff endpoints for previous-year questions: imports, papers, unmapped questions, mapping."""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_staff
from app.core.errors import AppError, NotFound
from app.jobs.models import Job
from app.modules.assessment import pyq, service
from app.modules.assessment.models import PyqImport, PyqSource, Question, QuestionConcept
from app.modules.catalog.models import Concept
from app.modules.identity.models import User
from app.modules.identity.service import audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/pyq/imports", status_code=202)
def create_import(body: pyq.ImportIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Upload one paper (JSON or CSV text). Returns at once; the `pyq.import` job does the rows."""
    imp = pyq.submit(db, user.id, body)
    audit(db, user.id, "pyq_import", "pyq_import", imp.id)
    db.commit()
    return pyq.import_row_out(imp)


def _with_job(db: Session, out: dict) -> dict:
    job = db.get(Job, uuid.UUID(out["job_id"])) if out.get("job_id") else None
    out["job_status"] = job.status if job else None
    out["job_error"] = job.error if job and job.status == "failed" else ""
    return out


@router.get("/pyq/imports")
def list_imports(limit: int = Query(50, ge=1, le=200), _: User = Depends(require_staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(PyqImport).order_by(PyqImport.created_at.desc()).limit(limit)).all()
    return [_with_job(db, pyq.import_row_out(r)) for r in rows]


@router.get("/pyq/imports/{import_id}")
def get_import(import_id: uuid.UUID, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    imp = db.get(PyqImport, import_id)
    if not imp:
        raise NotFound("Import not found")
    return _with_job(db, pyq.import_row_out(imp, full=True))


@router.get("/pyq/sources")
def list_sources(exam: str | None = None, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(Question.pyq_source_id, func.count())
            .where(Question.pyq_source_id.is_not(None), Question.status != "retired")
            .group_by(Question.pyq_source_id)
        ).all()
    )
    stmt = select(PyqSource).order_by(PyqSource.year.desc(), PyqSource.exam_date.desc(), PyqSource.key)
    if exam:
        stmt = stmt.where(PyqSource.exam == exam)
    return [
        {
            "id": str(s.id),
            "key": s.key,
            "exam": s.exam,
            "tier": s.tier,
            "year": s.year,
            "exam_date": s.exam_date,
            "shift": s.shift,
            "title": s.title,
            "source": s.source,
            "source_url": s.source_url,
            "licence": s.licence,
            "questions": counts.get(s.id, 0),
        }
        for s in db.scalars(stmt)
    ]


@router.get("/pyq/unmapped")
def unmapped(limit: int = Query(100, ge=1, le=500), _: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Imported PYQs not yet linked to any concept (they cannot be practised until mapped)."""
    mapped = select(QuestionConcept.question_id)
    rows = db.scalars(
        select(Question).where(Question.source == "pyq", Question.status != "retired", Question.id.not_in(mapped)).order_by(Question.created_at).limit(limit)
    ).all()
    return [{"id": str(q.id), "external_key": q.external_key, "stem": q.stem, "qtype": q.qtype, "pyq_year": q.pyq_year, "status": q.status} for q in rows]


class MappingIn(BaseModel):
    concepts: list[str] = Field(min_length=1)  # concept slugs
    pattern: str | None = None  # "<concept slug>:<pattern key>"
    pool: str | None = Field(default=None, pattern="^(practice|mock)$")


@router.post("/questions/{question_id}/mapping")
def map_question(question_id: uuid.UUID, body: MappingIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Link a question (typically an imported PYQ) to its concepts, exam pattern and pool."""
    q = db.get(Question, question_id)
    if not q:
        raise NotFound("Question not found")
    concepts = []
    for slug in body.concepts:
        c = db.scalar(select(Concept).where(Concept.slug == slug))
        if not c:
            raise NotFound(f"Unknown concept {slug!r}")
        concepts.append(c)
    if body.pattern:
        pattern = service.pattern_by_key(db, body.pattern)
        if not pattern:
            raise NotFound(f"Unknown pattern {body.pattern!r}")
        if pattern.concept_id not in {c.id for c in concepts}:
            raise AppError("The pattern belongs to a concept that is not in the mapping", status=422)
        q.pattern_id = pattern.id
    if body.pool:
        q.pool = body.pool
    pyq.set_concepts(db, q, [c.id for c in concepts])
    audit(db, user.id, "question_mapping", "question", q.id)
    db.commit()
    return {"id": str(q.id), "concepts": [c.slug for c in concepts], "pattern_id": str(q.pattern_id) if q.pattern_id else None, "pool": q.pool}
