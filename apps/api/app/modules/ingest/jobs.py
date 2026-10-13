"""Content-studio generation handlers: lessons, questions, flashcards, notes and mock tests.

Each AI call's output is saved (`ctx.save()`) together with a checkpoint in one transaction, so a
retried job resumes after the last saved unit instead of generating, and paying for, the same
drafts twice. Everything lands in the review queue; nothing reaches learners unapproved.
"""

import uuid

from app.ai import gateway
from app.ai.engines import questions as qengine
from app.ai.engines import teacher
from app.core.errors import AppError
from app.jobs.context import JobContext
from app.jobs.registry import handler
from app.modules.assessment import service as qservice
from app.modules.catalog.models import Concept
from app.modules.content import service as content
from app.modules.content.models import Flashcard, Note
from app.modules.identity.models import User
from app.modules.ingest import service
from app.modules.ingest.models import SourceDocument

QUEUE = "content"


def _actor(ctx: JobContext) -> tuple[uuid.UUID | None, str]:
    """AI budgets and metering are charged to the staff member who started the job."""
    user = ctx.db.get(User, ctx.created_by) if ctx.created_by else None
    return (user.id, user.role) if user else (None, "admin")


def _outputs(ctx: JobContext) -> dict:
    for key, empty in (("created", []), ("skipped", 0), ("providers", [])):
        ctx.result.setdefault(key, empty)
    return ctx.result


def _used(ctx: JobContext, provider: str) -> None:
    ctx.result["providers"] = sorted({*ctx.result["providers"], provider})


def _lesson_for(ctx: JobContext, concept: Concept):
    return content.find_lesson(ctx.db, concept.id, 2, "en") or content.find_lesson(ctx.db, concept.id, 1, "en")


@handler("generate.lessons", queue=QUEUE)
def generate_lessons(ctx: JobContext) -> None:
    user_id, role = _actor(ctx)
    out, p = _outputs(ctx), ctx.payload
    for concept in service.concepts_for(ctx.db, p):
        for level in p.get("levels", [1, 2]):
            key = f"{concept.id}:{level}"
            if ctx.is_done(key):
                continue
            lesson, res = content.generate_lesson(ctx.db, concept, int(level), p.get("locale", "en"), user_id, role)
            out["created"].append({"type": "lesson", "id": str(lesson.id), "concept": concept.title, "level": level})
            _used(ctx, res.provider)
            ctx.mark_done(key)
            ctx.save()


@handler("generate.questions", queue=QUEUE)
def generate_questions(ctx: JobContext) -> None:
    user_id, role = _actor(ctx)
    out, p = _outputs(ctx), ctx.payload
    for concept in service.concepts_for(ctx.db, p):
        if ctx.is_done(str(concept.id)):
            continue
        exam, course_id = content.exam_context_for(ctx.db, concept.id)
        lesson = _lesson_for(ctx, concept)
        task = qengine.generate_task(
            ctx.db, concept, p.get("qtype", "mcq"), p.get("difficulty", "medium"), int(p.get("count", 5)), exam, lesson.body if lesson else None, course_id
        )
        res = gateway.run(ctx.db, task, user_id, role)
        _used(ctx, res.provider)
        for generated in res.data.questions:
            q = qservice.save_generated(ctx.db, generated, concept.id, "offline" if res.offline else "ai")
            if q:
                out["created"].append({"type": "question", "id": str(q.id), "concept": concept.title})
            else:
                out["skipped"] += 1
        ctx.mark_done(str(concept.id))
        ctx.save()


@handler("generate.flashcards", queue=QUEUE)
def generate_flashcards(ctx: JobContext) -> None:
    user_id, role = _actor(ctx)
    out, p = _outputs(ctx), ctx.payload
    for concept in service.concepts_for(ctx.db, p):
        if ctx.is_done(str(concept.id)):
            continue
        lesson = _lesson_for(ctx, concept)
        res = gateway.run(ctx.db, teacher.flashcards_task(ctx.db, concept, lesson.body if lesson else None, int(p.get("count", 6))), user_id, role)
        _used(ctx, res.provider)
        for card in res.data.cards:
            fc = Flashcard(concept_id=concept.id, front=card.front, back=card.back, source="offline" if res.offline else "ai", status="in_review")
            ctx.db.add(fc)
            ctx.db.flush()
            out["created"].append({"type": "flashcard", "id": str(fc.id), "concept": concept.title})
        ctx.mark_done(str(concept.id))
        ctx.save()


@handler("generate.notes", queue=QUEUE)
def generate_notes(ctx: JobContext) -> None:
    user_id, role = _actor(ctx)
    out, p = _outputs(ctx), ctx.payload
    doc = ctx.db.get(SourceDocument, uuid.UUID(p["document_id"]))
    if not doc:
        raise AppError("Document not found")
    concept_ids = p.get("concept_ids") or []
    res = gateway.run(ctx.db, teacher.notes_task(ctx.db, doc.title, service.doc_text(ctx.db, doc)), user_id, role)
    _used(ctx, res.provider)
    note = Note(
        document_id=doc.id,
        concept_id=uuid.UUID(str(concept_ids[0])) if concept_ids else None,
        title=res.data.title,
        body="\n".join(f"- {s}" for s in res.data.summary) + ("\n\nKey terms: " + ", ".join(res.data.key_terms) if res.data.key_terms else ""),
        source="offline" if res.offline else "ai",
        status="in_review",
    )
    ctx.db.add(note)
    ctx.db.flush()
    out["created"].append({"type": "note", "id": str(note.id)})


@handler("generate.mock_test", queue=QUEUE)
def generate_mock_test(ctx: JobContext) -> None:
    out, p = _outputs(ctx), ctx.payload
    test = service.build_mock_test(ctx.db, uuid.UUID(p["course_id"]), int(p.get("count", 20)), p.get("title"))
    out["created"].append({"type": "test", "id": str(test.id), "title": test.title})
