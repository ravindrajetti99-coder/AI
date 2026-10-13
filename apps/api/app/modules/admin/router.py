import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.core.db import as_utc, get_db
from app.core.deps import require_staff
from app.core.errors import AppError, NotFound
from app.modules.assessment import service as qservice
from app.modules.assessment.models import QUESTION_TYPES, Question, QuestionConcept, Rubric
from app.modules.catalog.models import Concept, Course
from app.modules.content.models import ContentFlag, Flashcard, Lesson, Note
from app.modules.identity.models import User
from app.modules.identity.service import audit
from app.modules.ingest import service
from app.modules.ingest.models import GenerationJob, LlmCall, SourceDocument
from app.modules.learning.models import Attempt, Enrollment

router = APIRouter(prefix="/admin", tags=["admin"])

ASSETS = {"lesson": Lesson, "question": Question, "flashcard": Flashcard, "note": Note}


@router.post("/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    course_id: uuid.UUID | None = Form(None),
    licence: str = Form("owned"),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if course_id and not db.get(Course, course_id):
        raise NotFound("Course not found")
    doc = service.save_upload(db, user, file.filename or "upload.txt", data, title, course_id, licence)
    audit(db, user.id, "document_upload", "document", doc.id, filename=doc.filename)
    db.commit()
    return _doc_row(doc)


def _doc_row(d: SourceDocument) -> dict:
    return {
        "id": str(d.id),
        "title": d.title,
        "filename": d.filename,
        "status": d.status,
        "pages": d.pages,
        "chunks": d.chunk_count,
        "error": d.error,
        "course_id": str(d.course_id) if d.course_id else None,
        "licence": d.licence,
        "created_at": as_utc(d.created_at).isoformat(),
    }


@router.get("/documents")
def list_documents(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return [_doc_row(d) for d in db.scalars(select(SourceDocument).order_by(SourceDocument.created_at.desc()).limit(200)).all()]


class GenerateIn(BaseModel):
    kind: str = Field(pattern="^(lessons|questions|flashcards|notes|mock_test)$")
    course_id: uuid.UUID | None = None
    concept_ids: list[uuid.UUID] = []
    document_id: uuid.UUID | None = None
    levels: list[int] = [1, 2]
    locale: str = "en"
    qtype: str = Field(default="mcq", pattern="^(mcq|multi|assertion_reason|numerical|descriptive)$")
    difficulty: str = Field(default="medium", pattern="^(beginner|easy|medium|hard|expert)$")
    count: int = Field(default=5, ge=1, le=50)
    title: str | None = None


@router.post("/generate", status_code=202)
def generate(body: GenerateIn, background: BackgroundTasks, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    if body.kind in ("lessons", "questions", "flashcards") and not (body.course_id or body.concept_ids):
        raise AppError("Choose a course or concepts")
    if body.kind == "notes" and not body.document_id:
        raise AppError("Choose a document")
    if body.kind == "mock_test" and not body.course_id:
        raise AppError("Choose a course")
    if any(not 1 <= lv <= 4 for lv in body.levels):
        raise AppError("Levels are 1-4")
    params = body.model_dump(mode="json", exclude={"kind"})
    job = GenerationJob(created_by=user.id, kind=body.kind, params=params)
    db.add(job)
    audit(db, user.id, "generate", "job", job.id, kind=body.kind)
    db.commit()
    background.add_task(service.run_job, job.id)
    return {"job_id": str(job.id), "status": job.status}


def _job_row(j: GenerationJob) -> dict:
    return {
        "id": str(j.id),
        "kind": j.kind,
        "status": j.status,
        "params": j.params,
        "outputs": j.outputs,
        "error": j.error,
        "created_at": as_utc(j.created_at).isoformat(),
        "finished_at": as_utc(j.finished_at).isoformat() if j.finished_at else None,
    }


@router.get("/jobs")
def jobs(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return [_job_row(j) for j in db.scalars(select(GenerationJob).order_by(GenerationJob.created_at.desc()).limit(50)).all()]


@router.get("/jobs/{job_id}")
def job(job_id: uuid.UUID, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    j = db.get(GenerationJob, job_id)
    if not j:
        raise NotFound("Job not found")
    return _job_row(j)


def _concept_title(db: Session, cid) -> str:
    c = db.get(Concept, cid) if cid else None
    return c.title if c else ""


@router.get("/review-queue")
def review_queue(asset_type: str | None = None, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    out = []
    if asset_type in (None, "lesson"):
        for x in db.scalars(select(Lesson).where(Lesson.status == "in_review").order_by(Lesson.created_at).limit(100)).all():
            out.append(
                {
                    "asset_type": "lesson",
                    "id": str(x.id),
                    "concept": _concept_title(db, x.concept_id),
                    "level": x.level,
                    "locale": x.locale,
                    "source": x.source,
                    "content": x.body,
                }
            )
    if asset_type in (None, "question"):
        for x in db.scalars(select(Question).where(Question.status == "in_review").order_by(Question.created_at).limit(100)).all():
            cid = db.scalar(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == x.id))
            rubric = db.scalar(select(Rubric).where(Rubric.question_id == x.id))
            out.append(
                {
                    "asset_type": "question",
                    "id": str(x.id),
                    "concept": _concept_title(db, cid),
                    "qtype": x.qtype,
                    "source": x.source,
                    "content": {
                        "stem": x.stem,
                        "payload": x.payload,
                        "explanation": x.explanation,
                        "difficulty": x.difficulty,
                        "steps": qservice.steps(db, x.id),
                        "rubric": rubric.criteria if rubric else None,
                    },
                }
            )
    if asset_type in (None, "flashcard"):
        for x in db.scalars(select(Flashcard).where(Flashcard.status == "in_review").limit(100)).all():
            out.append(
                {
                    "asset_type": "flashcard",
                    "id": str(x.id),
                    "concept": _concept_title(db, x.concept_id),
                    "source": x.source,
                    "content": {"front": x.front, "back": x.back},
                }
            )
    if asset_type in (None, "note"):
        for x in db.scalars(select(Note).where(Note.status == "in_review").limit(100)).all():
            out.append(
                {
                    "asset_type": "note",
                    "id": str(x.id),
                    "concept": _concept_title(db, x.concept_id),
                    "source": x.source,
                    "content": {"title": x.title, "body": x.body},
                }
            )
    return out


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    edits: dict | None = None  # optional corrected content (lesson body / question fields / card / note)


@router.post("/assets/{asset_type}/{asset_id}/decision")
def decide(asset_type: str, asset_id: uuid.UUID, body: DecisionIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    model = ASSETS.get(asset_type)
    if not model:
        raise NotFound("Unknown asset type")
    asset = db.get(model, asset_id)
    if not asset:
        raise NotFound("Asset not found")
    if body.edits:
        _apply_edits(asset_type, asset, body.edits)
    asset.status = "verified" if body.decision == "approve" else "retired"
    if asset_type == "lesson" and body.decision == "approve":
        asset.reviewed_by = user.id
        # one verified lesson per concept/level/locale: retire older verified versions
        for old in db.scalars(
            select(Lesson).where(
                Lesson.concept_id == asset.concept_id,
                Lesson.level == asset.level,
                Lesson.locale == asset.locale,
                Lesson.status == "verified",
                Lesson.id != asset.id,
            )
        ).all():
            old.status = "retired"
    audit(db, user.id, f"asset_{body.decision}", asset_type, asset.id)
    db.commit()
    return {"id": str(asset.id), "status": asset.status}


def _apply_edits(asset_type: str, asset, edits: dict) -> None:
    if asset_type == "lesson":
        from app.ai.schemas import LessonOut

        asset.body = LessonOut.model_validate({**asset.body, **edits}).model_dump()
    elif asset_type == "question":
        for k in ("stem", "explanation", "difficulty"):
            if k in edits:
                setattr(asset, k, edits[k])
        if "payload" in edits:
            asset.payload = {**asset.payload, **edits["payload"]}
    elif asset_type == "flashcard":
        asset.front = edits.get("front", asset.front)
        asset.back = edits.get("back", asset.back)
    elif asset_type == "note":
        asset.title = edits.get("title", asset.title)
        asset.body = edits.get("body", asset.body)


class QuestionCreate(BaseModel):
    concept_ids: list[uuid.UUID] = Field(min_length=1)
    qtype: str
    stem: str = Field(min_length=3)
    payload: dict
    explanation: str = ""
    difficulty: str = Field(default="medium", pattern="^(beginner|easy|medium|hard|expert)$")
    steps: dict = {}
    rubric: list[dict] | None = None
    model_answer: str = ""
    pyq_year: int | None = None


@router.post("/questions", status_code=201)
def create_question(body: QuestionCreate, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    if body.qtype not in QUESTION_TYPES:
        raise AppError("Unknown question type")
    for cid in body.concept_ids:
        if not db.get(Concept, cid):
            raise NotFound(f"Concept {cid} not found")
    if body.qtype in ("descriptive", "interview") and not body.rubric:
        raise AppError("Descriptive questions need a rubric")
    q = qservice.add_question(
        db,
        qtype=body.qtype,
        stem=body.stem,
        payload=body.payload,
        concept_ids=body.concept_ids,
        explanation=body.explanation,
        difficulty=body.difficulty,
        steps_map=body.steps,
        rubric=body.rubric,
        model_answer=body.model_answer,
        source="pyq" if body.pyq_year else "manual",
        pyq_year=body.pyq_year,
    )
    audit(db, user.id, "question_create", "question", q.id)
    db.commit()
    return {"id": str(q.id)}


@router.get("/flags")
def flags(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return [
        {"id": str(f.id), "asset_type": f.asset_type, "asset_id": str(f.asset_id), "reason": f.reason, "created_at": as_utc(f.created_at).isoformat()}
        for f in db.scalars(select(ContentFlag).where(ContentFlag.resolved == 0).order_by(ContentFlag.created_at.desc())).all()
    ]


@router.get("/ai-usage")
def ai_usage(days: int = 30, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(
            LlmCall.feature,
            LlmCall.provider,
            func.count(),
            func.sum(LlmCall.input_tokens),
            func.sum(LlmCall.output_tokens),
            func.sum(LlmCall.cost_usd),
            func.avg(LlmCall.latency_ms),
            func.sum(case((LlmCall.cache_hit.is_(True), 1), else_=0)),
        )
        .where(LlmCall.created_at >= since)
        .group_by(LlmCall.feature, LlmCall.provider)
    ).all()
    return {
        "status": gateway.ai_status(),
        "since": since.isoformat(),
        "rows": [
            {
                "feature": f,
                "provider": p,
                "calls": n,
                "input_tokens": int(i or 0),
                "output_tokens": int(o or 0),
                "cost_usd": round(float(c or 0), 4),
                "avg_latency_ms": round(float(lat or 0)),
                "cache_hits": int(h or 0),
            }
            for f, p, n, i, o, c, lat, h in rows
        ],
    }


@router.get("/stats")
def stats(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    return {
        "users": count(User),
        "courses": count(Course),
        "concepts": count(Concept),
        "questions_verified": count(Question, Question.status == "verified"),
        "lessons_verified": count(Lesson, Lesson.status == "verified"),
        "in_review": count(Lesson, Lesson.status == "in_review")
        + count(Question, Question.status == "in_review")
        + count(Flashcard, Flashcard.status == "in_review")
        + count(Note, Note.status == "in_review"),
        "enrollments": count(Enrollment),
        "attempts_7d": count(Attempt, Attempt.attempted_at >= datetime.now(UTC) - timedelta(days=7)),
        "documents": count(SourceDocument),
    }
