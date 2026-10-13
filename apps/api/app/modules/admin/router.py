import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ai import check as ai_check
from app.ai import gateway
from app.core.config import get_settings
from app.core.db import as_utc, get_db
from app.core.deps import limiter, require_admin, require_staff
from app.core.errors import AppError, NotFound
from app.jobs import service as jobs
from app.modules.assessment import service as qservice
from app.modules.assessment.models import QUESTION_TYPES, Question, QuestionConcept, QuestionPattern, Rubric
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Concept, Course, ExamStrategy
from app.modules.content import coverage
from app.modules.content.models import ContentFlag, Flashcard, Formula, Lesson, Note, Shortcut
from app.modules.identity.models import User
from app.modules.identity.service import audit
from app.modules.ingest import service
from app.modules.ingest.models import LlmCall, SourceDocument
from app.modules.learning.models import Attempt, Enrollment

router = APIRouter(prefix="/admin", tags=["admin"])

ASSETS = {
    "lesson": Lesson,
    "question": Question,
    "flashcard": Flashcard,
    "note": Note,
    "formula": Formula,
    "shortcut": Shortcut,
    "pattern": QuestionPattern,
    "strategy": ExamStrategy,
}
# Concept-level content of exam courses: written in the syllabus files or generated, reviewed here.
AUTHORED = {"formula", "shortcut", "pattern", "strategy"}


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
def generate(body: GenerateIn, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    if body.kind in ("lessons", "questions", "flashcards") and not (body.course_id or body.concept_ids):
        raise AppError("Choose a course or concepts")
    if body.kind == "notes" and not body.document_id:
        raise AppError("Choose a document")
    if body.kind == "mock_test" and not body.course_id:
        raise AppError("Choose a course")
    if any(not 1 <= lv <= 4 for lv in body.levels):
        raise AppError("Levels are 1-4")
    job = service.enqueue_generation(db, user, body.kind, body.model_dump(mode="json", exclude={"kind"}))
    audit(db, user.id, "generate", "job", job.id, kind=body.kind)
    db.commit()  # the job and its audit entry become visible to workers together
    return {"job_id": str(job.id), "status": job.status}


@router.get("/jobs")
def list_jobs(
    status: str | None = Query(None, pattern="^(queued|running|done|failed|cancelled)$"),
    queue: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return [jobs.row(j) for j in jobs.list_jobs(db, status=status, queue=queue, kind=kind, limit=limit)]


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return jobs.row(jobs.get(db, job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    job = jobs.cancel(db, job_id)
    audit(db, user.id, "job_cancel", "job", job.id, kind=job.kind)
    db.commit()
    return jobs.row(job)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: uuid.UUID, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    job = jobs.retry(db, job_id)
    audit(db, user.id, "job_retry", "job", job.id, kind=job.kind)
    db.commit()
    return jobs.row(job)


def _concept_title(db: Session, cid) -> str:
    c = db.get(Concept, cid) if cid else None
    return c.title if c else ""


def _authored_content(asset_type: str, x) -> dict:
    if asset_type == "formula":
        return {"name": x.name, "expression": x.expression, "variables": x.variables, "conditions": x.conditions, "example": x.example}
    if asset_type == "shortcut":
        return {"title": x.title, "kind": x.kind, "rule": x.rule, "when_to_use": x.when_to_use, "steps": x.steps, "example": x.example, "pitfalls": x.pitfalls}
    if asset_type == "pattern":
        return {
            "title": x.title,
            "description": x.description,
            "example_stem": x.example_stem,
            "frequency": x.frequency,
            "tiers": x.tiers,
            "difficulty": x.difficulty,
            "target_seconds": x.target_seconds,
        }
    return {"title": x.title, **x.body}


@router.get("/review-queue")
def review_queue(asset_type: str | None = None, limit: int = Query(100, ge=1, le=500), _: User = Depends(require_staff), db: Session = Depends(get_db)):
    out = []
    for kind in sorted(AUTHORED):
        if asset_type not in (None, kind):
            continue
        model = ASSETS[kind]
        for x in db.scalars(select(model).where(model.status == "in_review").order_by(model.created_at, model.key).limit(limit)).all():
            if kind == "strategy":
                course = db.get(Course, x.course_id)
                where = course.title if course else ""
            else:
                where = _concept_title(db, x.concept_id)
            out.append({"asset_type": kind, "id": str(x.id), "key": x.key, "concept": where, "source": x.source, "content": _authored_content(kind, x)})
    if asset_type in (None, "lesson"):
        for x in db.scalars(select(Lesson).where(Lesson.status == "in_review").order_by(Lesson.created_at).limit(limit)).all():
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
        for x in db.scalars(select(Question).where(Question.status == "in_review").order_by(Question.created_at).limit(limit)).all():
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
        for x in db.scalars(select(Flashcard).where(Flashcard.status == "in_review").limit(limit)).all():
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
        for x in db.scalars(select(Note).where(Note.status == "in_review").limit(limit)).all():
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
        if asset_type in AUTHORED and asset.source == "syllabus":
            raise AppError("This item comes from the syllabus files; change it there (the edit is then reviewed again).", status=422)
        try:
            _apply_edits(asset_type, asset, body.edits)
        except ValidationError as exc:
            raise AppError(f"Invalid edits: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}", status=422) from exc
    asset.status = "verified" if body.decision == "approve" else "retired"
    if asset_type in AUTHORED:
        asset.reviewed_by = user.id  # also marks a rejection, so a re-seed does not resurrect it
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


class FormulaEdits(BaseModel, extra="forbid"):
    name: str | None = Field(default=None, min_length=1)
    expression: str | None = Field(default=None, min_length=1)
    variables: list[dict] | None = None
    conditions: str | None = None
    example: dict | None = None


class ShortcutEdits(BaseModel, extra="forbid"):
    title: str | None = Field(default=None, min_length=1)
    rule: str | None = Field(default=None, min_length=1)
    when_to_use: str | None = None
    steps: list[str] | None = None
    example: dict | None = None
    pitfalls: list[str] | None = None


class PatternEdits(BaseModel, extra="forbid"):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    example_stem: str | None = None
    frequency: str | None = Field(default=None, pattern="^(high|medium|low|rare)$")
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    target_seconds: int | None = Field(default=None, ge=10, le=600)


class StrategyEdits(BaseModel, extra="forbid"):
    title: str | None = Field(default=None, min_length=1)
    body: dict | None = None


AUTHORED_EDITS = {"formula": FormulaEdits, "shortcut": ShortcutEdits, "pattern": PatternEdits, "strategy": StrategyEdits}


def _apply_edits(asset_type: str, asset, edits: dict) -> None:
    if asset_type in AUTHORED_EDITS:
        for k, v in AUTHORED_EDITS[asset_type].model_validate(edits).model_dump(exclude_none=True).items():
            setattr(asset, k, v)
    elif asset_type == "lesson":
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


@router.post("/flags/{flag_id}/resolve")
def resolve_flag(flag_id: uuid.UUID, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    flag = db.get(ContentFlag, flag_id)
    if not flag:
        raise NotFound("Flag not found")
    flag.resolved = 1
    audit(db, user.id, "flag_resolve", "flag", flag.id)
    db.commit()
    return {"id": str(flag.id), "resolved": True}


# ---------------------------------------------------------------- courses and coverage


@router.get("/courses")
def all_courses(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Every course, drafts included (the public list shows published courses only)."""
    rows = db.scalars(select(Course).order_by(Course.domain, Course.title)).all()
    return [
        {
            "id": str(c.id),
            "slug": c.slug,
            "title": c.title,
            "domain": c.domain,
            "status": c.status,
            "content_policy": c.content_policy,
            "has_targets": bool(c.content_targets),
        }
        for c in rows
    ]


@router.get("/courses/{slug}/coverage")
def course_coverage(slug: str, scope: str | None = None, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Verified content against the course's requirements, per subject and chapter; `scope`
    ("subject" or "subject.chapter") also lists that part's concepts and their gaps."""
    return coverage.course_coverage(db, catalog.get_course(db, slug), scope)


@router.get("/ai/status")
def ai_status(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """AI configuration (no secrets) and the last 24 hours: spend against the cap, cache
    efficiency, errors, refusals and server-side fallbacks."""
    s = get_settings()
    since = datetime.now(UTC) - timedelta(hours=24)

    def count_if(cond):
        return func.sum(case((cond, 1), else_=0))

    row = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(LlmCall.cost_usd), 0.0),
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_read_tokens), 0),
            func.coalesce(func.sum(LlmCall.cache_write_tokens), 0),
            count_if(LlmCall.status == "error"),
            count_if(LlmCall.status == "refusal"),
            count_if((LlmCall.requested_model != "") & (LlmCall.model != LlmCall.requested_model)),
            count_if(LlmCall.provider == "offline"),
            count_if(LlmCall.cache_hit.is_(True)),
        ).where(LlmCall.created_at >= since)
    ).one()
    calls, cost, inp, out, cread, cwrite, errors, refusals, fallbacks, offline, stored = (row[0], float(row[1]), *(int(x or 0) for x in row[2:]))
    prompt = inp + cread + cwrite
    config = ai_check.configuration()
    if user.role != "admin":
        config.pop("keys")
    cap = s.ai_daily_spend_cap_usd
    return {
        "mode": gateway.ai_status()["mode"],
        "providers": gateway.ai_status()["providers"],
        "config": config,
        "last_24h": {
            "calls": calls,
            "cost_usd": round(cost, 4),
            "spend_cap_usd": cap,
            "cap_used": round(cost / cap, 3) if cap else None,
            "cap_reached": bool(cap) and cost >= cap,
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_tokens": cread,
            "cache_write_tokens": cwrite,
            "prompt_cache_hit_ratio": round(cread / prompt, 3) if prompt else None,
            "stored_answers_served": stored,
            "errors": errors,
            "refusals": refusals,
            "fallbacks": fallbacks,
            "offline_answers": offline,
        },
    }


@router.post("/ai/check")
def ai_check_now(live: bool = False, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Smoke-check every configured provider and tier (free calls; `live` sends tiny real ones)."""
    limiter.hit(f"ai-check:{user.id}", 5)
    results = ai_check.run_checks(live=live)
    audit(db, user.id, "ai_check", "ai", "", live=live, ok=all(r["ok"] is not False for r in results))
    db.commit()
    return {"ok": all(r["ok"] is not False for r in results), "configured": any(r["ok"] is not None for r in results), "results": results}


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
            func.sum(LlmCall.cache_read_tokens),
            func.sum(LlmCall.cache_write_tokens),
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
                "cache_read_tokens": int(cr or 0),
                "cache_write_tokens": int(cw or 0),
            }
            for f, p, n, i, o, c, lat, h, cr, cw in rows
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
        + count(Note, Note.status == "in_review")
        + sum(count(ASSETS[k], ASSETS[k].status == "in_review") for k in AUTHORED),
        "enrollments": count(Enrollment),
        "attempts_7d": count(Attempt, Attempt.attempted_at >= datetime.now(UTC) - timedelta(days=7)),
        "documents": count(SourceDocument),
    }
