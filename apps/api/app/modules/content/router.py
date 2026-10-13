import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.ai.engines import teacher
from app.core.db import get_db
from app.core.deps import get_current_user, rate_limit_ai
from app.core.errors import NotFound
from app.modules.catalog import service as catalog
from app.modules.content import service
from app.modules.content.models import ContentFlag, Flashcard, Note
from app.modules.identity.models import User
from app.modules.learning.models import Conversation, Message

router = APIRouter(tags=["learn"])


@router.get("/concepts/{concept_id}/lesson")
def get_lesson(
    concept_id: str,
    level: int = Query(1, ge=1, le=4),
    locale: str = "en",
    generate: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    concept = catalog.get_concept(db, concept_id)
    lesson = service.find_lesson(db, concept.id, level, locale)
    if lesson:
        return service.lesson_out(lesson)
    draft = service.find_lesson(db, concept.id, level, locale, statuses=("in_review",))
    if draft:
        return service.lesson_out(draft, "AI draft: not yet verified by a reviewer.")
    if not generate:
        fallback = service.find_lesson(db, concept.id, level, "en") if locale != "en" else None
        if fallback:
            return service.lesson_out(fallback, f"Not yet available in '{locale}'; showing English.")
        return {"id": None, "concept_id": str(concept.id), "level": level, "locale": locale, "body": None, "status": "missing", "can_generate": True}
    rate_limit_ai(user)
    lesson, res = service.generate_lesson(db, concept, level, locale, user.id, user.role)
    db.commit()
    note = "AI draft: not yet verified by a reviewer." if not res.offline else "Draft built from course material without an AI model."
    return service.lesson_out(lesson, (res.note + " " + note).strip())


@router.get("/concepts/{concept_id}/flashcards")
def flashcards(concept_id: str, locale: str = "en", _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    concept = catalog.get_concept(db, concept_id)
    cards = db.scalars(select(Flashcard).where(Flashcard.concept_id == concept.id, Flashcard.locale == locale, Flashcard.status == "verified")).all()
    return [{"id": str(c.id), "front": c.front, "back": c.back} for c in cards]


@router.get("/concepts/{concept_id}/notes")
def notes(concept_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    concept = catalog.get_concept(db, concept_id)
    rows = db.scalars(select(Note).where(Note.concept_id == concept.id, Note.status == "verified")).all()
    return [{"id": str(n.id), "title": n.title, "body": n.body} for n in rows]


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    locale: str = "en"


@router.post("/concepts/{concept_id}/ask")
def ask_tutor(concept_id: str, body: AskIn, user: User = Depends(rate_limit_ai), db: Session = Depends(get_db)):
    concept = catalog.get_concept(db, concept_id)
    conv = None
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if not conv or conv.user_id != user.id:
            raise NotFound("Conversation not found")
    if not conv:
        conv = Conversation(user_id=user.id, kind="tutor", context={"concept_id": str(concept.id)})
        db.add(conv)
        db.flush()
    history = [
        {"role": m.role, "content": m.content} for m in db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)).all()
    ]
    lesson = (
        service.find_lesson(db, concept.id, 2, body.locale)
        or service.find_lesson(db, concept.id, 1, body.locale)
        or service.find_lesson(db, concept.id, 1, "en")
    )
    _, course_id = service.exam_context_for(db, concept.id)
    res = gateway.run(db, teacher.tutor_task(db, concept, lesson.body if lesson else None, history, body.question, body.locale, course_id), user.id, user.role)
    db.add(Message(conversation_id=conv.id, role="user", content=body.question))
    db.add(Message(conversation_id=conv.id, role="assistant", content=res.data.reply, meta={"provider": res.provider}))
    db.commit()
    return {"conversation_id": str(conv.id), **res.data.model_dump(), "provider": res.provider, "note": res.note}


class FlagIn(BaseModel):
    asset_type: str = Field(pattern="^(lesson|question|flashcard|note)$")
    asset_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/content/flags", status_code=201)
def flag(body: FlagIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.add(ContentFlag(asset_type=body.asset_type, asset_id=body.asset_id, user_id=user.id, reason=body.reason))
    db.commit()
    return {"ok": True}
