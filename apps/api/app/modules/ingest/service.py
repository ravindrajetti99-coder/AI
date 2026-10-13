"""Admin content pipeline: parse uploads, chunk them, and run AI generation jobs."""

import io
import os
import random
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import gateway, retrieval
from app.ai.engines import questions as qengine
from app.ai.engines import teacher
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.modules.assessment import service as qservice
from app.modules.assessment.models import OBJECTIVE_TYPES, Question, QuestionConcept, Test, TestItem
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Concept, Course, ExamProfile
from app.modules.content import service as content
from app.modules.content.models import Flashcard, Note
from app.modules.identity.models import User
from app.modules.ingest.models import GenerationJob, SourceDocument

ALLOWED = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}


def extract_text(filename: str, data: bytes) -> tuple[str, int]:
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            pages.append(f"\f[page {i}]\n\n{page.extract_text() or ''}")
        return "\n\n".join(pages), len(reader.pages)
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="replace"), 1
    raise AppError(f"Unsupported file type {ext}; upload PDF, TXT or MD")


def save_upload(db: Session, user: User, filename: str, data: bytes, title: str, course_id: uuid.UUID | None, licence: str) -> SourceDocument:
    s = get_settings()
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED:
        raise AppError(f"Unsupported file type {ext}; upload PDF, TXT or MD")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise AppError(f"File larger than {s.max_upload_mb} MB")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise AppError("File is not a valid PDF")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename))[:100]
    os.makedirs(s.upload_dir, exist_ok=True)
    path = os.path.join(s.upload_dir, f"{uuid.uuid4().hex}_{safe}")
    with open(path, "wb") as f:
        f.write(data)
    doc = SourceDocument(uploaded_by=user.id, course_id=course_id, title=title or safe, filename=safe, mime=ALLOWED[ext], storage_path=path, licence=licence)
    db.add(doc)
    db.flush()
    try:
        text, pages = extract_text(filename, data)
        doc.pages = pages
        doc.status = "parsed"
        doc.chunk_count = retrieval.store_chunks(db, doc, text)
        doc.status = "chunked" if doc.chunk_count else "failed"
        if not doc.chunk_count:
            doc.error = "No extractable text (scanned PDF? OCR is needed)"
    except AppError:
        raise
    except Exception as exc:  # corrupt files must not take the API down
        doc.status, doc.error = "failed", str(exc)[:500]
    db.commit()
    return doc


def _concepts_for(db: Session, params: dict) -> list[Concept]:
    ids = params.get("concept_ids") or []
    if ids:
        return [catalog.get_concept(db, str(i)) for i in ids]
    if params.get("course_id"):
        return [c for c, _, _ in catalog.course_concepts(db, uuid.UUID(params["course_id"]))]
    return []


def run_job(job_id: uuid.UUID) -> None:
    """Executes a generation job in its own session (called from a background task or worker)."""
    db = SessionLocal()
    try:
        job = db.get(GenerationJob, job_id)
        if not job:
            return
        job.status = "running"
        db.commit()
        user = db.get(User, job.created_by)
        try:
            job.outputs = _execute(db, job, user)
            job.status = "done"
        except Exception as exc:
            db.rollback()
            job = db.get(GenerationJob, job_id)
            job.status, job.error = "failed", str(exc)[:1000]
        job.finished_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()


def _execute(db: Session, job: GenerationJob, user: User) -> dict:
    p = job.params
    out: dict = {"created": [], "skipped": 0, "providers": set()}
    if job.kind == "lessons":
        for concept in _concepts_for(db, p):
            for level in p.get("levels", [1, 2]):
                lesson, res = content.generate_lesson(db, concept, int(level), p.get("locale", "en"), user.id, user.role)
                out["created"].append({"type": "lesson", "id": str(lesson.id), "concept": concept.title, "level": level})
                out["providers"].add(res.provider)
            db.commit()
    elif job.kind == "questions":
        for concept in _concepts_for(db, p):
            ctx, course_id = content.exam_context_for(db, concept.id)
            lesson = content.find_lesson(db, concept.id, 2, "en") or content.find_lesson(db, concept.id, 1, "en")
            task = qengine.generate_task(
                db, concept, p.get("qtype", "mcq"), p.get("difficulty", "medium"), int(p.get("count", 5)), ctx, lesson.body if lesson else None, course_id
            )
            res = gateway.run(db, task, user.id, user.role)
            out["providers"].add(res.provider)
            for gq in res.data.questions:
                q = qservice.save_generated(db, gq, concept.id, "offline" if res.offline else "ai")
                if q:
                    out["created"].append({"type": "question", "id": str(q.id), "concept": concept.title})
                else:
                    out["skipped"] += 1
            db.commit()
    elif job.kind == "flashcards":
        for concept in _concepts_for(db, p):
            lesson = content.find_lesson(db, concept.id, 2, "en") or content.find_lesson(db, concept.id, 1, "en")
            res = gateway.run(db, teacher.flashcards_task(db, concept, lesson.body if lesson else None, int(p.get("count", 6))), user.id, user.role)
            out["providers"].add(res.provider)
            for card in res.data.cards:
                fc = Flashcard(concept_id=concept.id, front=card.front, back=card.back, source="offline" if res.offline else "ai", status="in_review")
                db.add(fc)
                db.flush()
                out["created"].append({"type": "flashcard", "id": str(fc.id), "concept": concept.title})
            db.commit()
    elif job.kind == "notes":
        doc = db.get(SourceDocument, uuid.UUID(p["document_id"]))
        if not doc:
            raise AppError("Document not found")
        concept_ids = p.get("concept_ids") or []
        res = gateway.run(db, teacher.notes_task(db, doc.title, _doc_text(db, doc)), user.id, user.role)
        out["providers"].add(res.provider)
        note = Note(
            document_id=doc.id,
            concept_id=uuid.UUID(str(concept_ids[0])) if concept_ids else None,
            title=res.data.title,
            body="\n".join(f"- {s}" for s in res.data.summary) + ("\n\nKey terms: " + ", ".join(res.data.key_terms) if res.data.key_terms else ""),
            source="offline" if res.offline else "ai",
            status="in_review",
        )
        db.add(note)
        db.flush()
        out["created"].append({"type": "note", "id": str(note.id)})
        db.commit()
    elif job.kind == "mock_test":
        test = build_mock_test(db, uuid.UUID(p["course_id"]), int(p.get("count", 20)), p.get("title"))
        out["created"].append({"type": "test", "id": str(test.id), "title": test.title})
        db.commit()
    else:
        raise AppError(f"Unknown job kind {job.kind}")
    out["providers"] = sorted(out["providers"])
    return out


def _doc_text(db: Session, doc: SourceDocument) -> str:
    from app.modules.ingest.models import Chunk

    return "\n\n".join(db.scalars(select(Chunk.text).where(Chunk.document_id == doc.id).order_by(Chunk.ordinal)).all())


def exam_pattern(db: Session, course: Course) -> dict:
    if not course.exam_profile_id:
        return {}
    return db.get(ExamProfile, course.exam_profile_id).pattern or {}


def pick_mock_questions(db: Session, course: Course, count: int) -> list[Question]:
    """Blueprint: verified objective questions spread across concepts in proportion to exam weight.
    Deterministic per course, so rebuilding a mock with the same pool picks the same questions."""
    concepts = catalog.course_concepts(db, course.id)
    total_w = sum(w for _, w, _ in concepts) or 1
    rng = random.Random(f"{course.id}-{count}")
    chosen: list[Question] = []
    for concept, w, _ in concepts:
        want = max(1, round(count * w / total_w))
        pool = db.scalars(
            select(Question)
            .join(QuestionConcept, QuestionConcept.question_id == Question.id)
            .where(QuestionConcept.concept_id == concept.id, Question.status == "verified", Question.qtype.in_(OBJECTIVE_TYPES))
            .order_by(Question.id)  # stable input order, so the seeded shuffle is reproducible
        ).all()
        pool = [q for q in pool if q not in chosen]
        rng.shuffle(pool)
        chosen += pool[:want]
    return chosen[:count]


def build_mock_test(db: Session, course_id: uuid.UUID, count: int, title: str | None = None, slug: str | None = None) -> Test:
    """Blueprint-driven mock with the marking scheme from the course's exam profile."""
    course = db.get(Course, course_id)
    if not course:
        raise AppError("Course not found")
    pattern = exam_pattern(db, course)
    marks = float(pattern.get("marks_per_question", 1))
    negative = float(pattern.get("negative_marks", 0))
    chosen = pick_mock_questions(db, course, count)
    if not chosen:
        raise AppError("No verified objective questions in this course yet")
    test = Test(
        slug=slug or f"{course.slug}-mock-{uuid.uuid4().hex[:6]}",
        title=title or f"{course.title}: Mock test",
        kind="mock",
        course_id=course.id,
        duration_minutes=max(10, round(len(chosen) * float(pattern.get("minutes_per_question", 1.0)))),
        instructions=f"{marks:g} mark(s) per question; {negative:g} deducted for each wrong answer."
        if negative
        else f"{marks:g} mark(s) per question; no negative marking.",
    )
    db.add(test)
    db.flush()
    for i, q in enumerate(chosen):
        db.add(TestItem(test_id=test.id, question_id=q.id, section=pattern.get("default_section", "General"), marks=marks, negative_marks=negative, position=i))
    return test
