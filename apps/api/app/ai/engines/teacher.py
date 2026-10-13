"""AI Teacher: lessons at four levels, grounded in retrieved sources; tutor chat; flashcards; notes."""

import re
import uuid

from sqlalchemy.orm import Session

from app.ai import gateway, retrieval
from app.ai.schemas import FlashcardsOut, LessonOut, NotesOut, TutorReply
from app.ai.text import content_terms, extractive_summary, sentences
from app.modules.catalog.models import Concept

PROMPT_VERSION = "teacher-v1"
LEVEL_GUIDE = {
    1: "Beginner: plain words, one idea at a time, everyday analogies, no jargon without explanation.",
    2: "Intermediate: precise terms, worked examples, how it connects to related concepts.",
    3: "Advanced: edge cases, derivations or reasoning, exam-level tricky variations.",
    4: "Expert/professional: rigorous treatment, real professional practice, nuances and pitfalls experts watch for.",
}
LOCALE_GUIDE = {
    "en": "Write in clear English.",
    "te": "Write in Telugu script. Keep standard technical terms in English (in brackets) where Telugu learners expect them.",
    "hi": "Write in Hindi (Devanagari). Keep standard technical terms in English where learners expect them.",
}


def _sources_for(db: Session, concept: Concept, course_id: uuid.UUID | None, k: int = 4) -> list[dict]:
    return retrieval.search(db, f"{concept.title} {concept.summary}", course_id=course_id, k=k)


def lesson_task(db: Session, concept: Concept, level: int, locale: str, course_id=None, exam_context: str = "") -> gateway.Task:
    sources = _sources_for(db, concept, course_id)
    system = (
        "You are an expert teacher who explains for deep understanding, not memorisation. "
        f"Level: {LEVEL_GUIDE[level]} {LOCALE_GUIDE.get(locale, LOCALE_GUIDE['en'])} "
        "Include a Mermaid flowchart in `diagram` only when a picture genuinely helps (else empty). "
        "Cite the ids of sources you used in `citations`. Do not invent exam statistics."
    )
    user = (
        f"Concept: {concept.title}\nSummary: {concept.summary}\nDomain: {concept.domain}\n"
        f"Exam context: {exam_context or 'general'}\n"
        f"Write the lesson with: definition, explanation, 2-3 real-life examples, key points, common mistakes, "
        f"a memory technique, exam relevance, and 3 check questions with answers.\n\n"
        f"{gateway.fence(sources) if sources else 'No uploaded sources; rely on well-established knowledge.'}"
    )
    return gateway.Task(
        name="teacher.lesson",
        prompt_version=PROMPT_VERSION,
        tier="heavy" if level >= 3 else "standard",
        system=system,
        user=user,
        schema=LessonOut,
        offline=lambda: offline_lesson(concept, level, sources),
        max_tokens=3000,
        cacheable=True,
        cache_key_parts={"concept": str(concept.id), "level": level, "locale": locale, "sources": [s["id"] for s in sources]},
    )


def offline_lesson(concept: Concept, level: int, sources: list[dict]) -> dict:
    """Extractive draft from the concept summary and uploaded sources (no model needed).
    Clearly a draft: it goes to the review queue like any AI asset."""
    corpus = " ".join([concept.summary] + [s["text"] for s in sources])
    summary = extractive_summary(corpus, max_sentences=2 + level * 2) or [concept.summary or concept.title]
    defs = [s for s in sentences(corpus) if re.search(rf"\b{re.escape(concept.title.split()[0])}\b.*\b(is|are|means|refers)\b", s, re.I)]
    definition = defs[0] if defs else (concept.summary or f"{concept.title}.")
    key_points = [s for s in summary if s != definition][:5]
    terms = sorted(set(content_terms(concept.title + " " + concept.summary)))[:4]
    return {
        "definition": definition,
        "explanation": " ".join(summary),
        "examples": [
            {
                "title": f"From the source: {s['heading'] or s['title']}",
                "body": extractive_summary(s["text"], 2)[0] if extractive_summary(s["text"], 2) else s["text"][:300],
            }
            for s in sources[:2]
        ],
        "diagram": "",
        "key_points": key_points,
        "common_mistakes": [f"Memorising the definition of {concept.title} without being able to apply it to a new problem."],
        "memory_technique": f"Make a one-line flashcard linking {', '.join(terms) or concept.title} and recall it before re-reading.",
        "exam_relevance": "Draft generated from your uploaded material without an AI model; a reviewer should complete this section.",
        "check_questions": [{"question": f"In your own words, what is {concept.title}?", "answer": definition}],
        "citations": [s["id"] for s in sources],
    }


def tutor_task(db: Session, concept: Concept, lesson_body: dict | None, history: list[dict], question: str, locale: str, course_id=None) -> gateway.Task:
    sources = retrieval.search(db, f"{concept.title} {question}", course_id=course_id, k=3)
    lesson_text = ""
    if lesson_body:
        lesson_text = "\n".join([lesson_body.get("definition", ""), lesson_body.get("explanation", "")] + [f"- {p}" for p in lesson_body.get("key_points", [])])
    system = (
        "You are a patient personal tutor (Socratic when the learner is solving a problem: guide, don't hand over answers "
        "to practice questions). Answer the learner's question about the concept, short and clear, then suggest up to 2 "
        f"follow-up questions to deepen understanding. {LOCALE_GUIDE.get(locale, LOCALE_GUIDE['en'])} "
        "If the question is unrelated to learning, politely steer back."
    )
    user = f"Concept: {concept.title}\nLesson:\n{lesson_text[:4000]}\n\n{gateway.fence(sources)}\n\nLearner asks: {question}"
    return gateway.Task(
        name="tutor.chat",
        prompt_version=PROMPT_VERSION,
        tier="standard",
        system=system,
        user=user,
        schema=TutorReply,
        messages=history[-10:],
        offline=lambda: offline_tutor(concept, lesson_text, sources, question),
        max_tokens=1200,
    )


def offline_tutor(concept: Concept, lesson_text: str, sources: list[dict], question: str) -> dict:
    q_terms = set(content_terms(question))
    pool = sentences(lesson_text) + [s for src in sources for s in sentences(src["text"])]
    ranked = sorted(pool, key=lambda s: len(q_terms & set(content_terms(s))), reverse=True)
    best = [s for s in ranked[:3] if q_terms & set(content_terms(s))]
    if best:
        reply = "Here is what the lesson says that matches your question: " + " ".join(best)
    else:
        reply = (
            f"I couldn't find that in the {concept.title} material yet. Try rephrasing with key terms from the lesson, "
            "or connect an AI provider for open-ended tutoring."
        )
    return {"reply": reply, "follow_up_questions": [f"Can you give an example of {concept.title}?", f"Where is {concept.title} used in exam questions?"]}


def flashcards_task(db: Session, concept: Concept, lesson_body: dict | None, count: int = 6) -> gateway.Task:
    text = ""
    if lesson_body:
        text = "\n".join([lesson_body.get("definition", ""), lesson_body.get("explanation", "")] + lesson_body.get("key_points", []))
    return gateway.Task(
        name="teacher.flashcards",
        prompt_version=PROMPT_VERSION,
        tier="light",
        system="Create concise active-recall flashcards: a precise question on the front, a short answer on the back.",
        user=f"Concept: {concept.title}\nMaterial:\n{text[:5000]}\nCreate {count} flashcards.",
        schema=FlashcardsOut,
        offline=lambda: offline_flashcards(concept, text, count),
        cacheable=True,
        cache_key_parts={"concept": str(concept.id), "count": count, "text": text[:2000]},
    )


def offline_flashcards(concept: Concept, text: str, count: int) -> dict:
    cards = []
    for s in sentences(text or concept.summary):
        m = re.match(r"^(.{3,80}?)\s+(is|are|means|refers to)\s+(.+)$", s, re.I)
        if m:
            cards.append({"front": f"What {m.group(2).lower()} {m.group(1).strip()}?", "back": m.group(3).strip()})
        elif len(cards) < count and len(s.split()) > 6:
            cards.append({"front": f"Complete the idea about {concept.title}: {' '.join(s.split()[:6])} ...", "back": s})
        if len(cards) >= count:
            break
    if not cards:
        cards.append({"front": f"What is {concept.title}?", "back": concept.summary or concept.title})
    return {"cards": cards}


def notes_task(db: Session, title: str, text: str) -> gateway.Task:
    return gateway.Task(
        name="teacher.notes",
        prompt_version=PROMPT_VERSION,
        tier="standard",
        system="Summarise study material into crisp revision notes: 5-10 bullet points and the key terms.",
        user=f"Title: {title}\n{gateway.fence([{'id': 'doc', 'title': title, 'text': text[:12000]}])}",
        schema=NotesOut,
        offline=lambda: {"title": title, "summary": extractive_summary(text, 8), "key_terms": _key_terms(text)},
    )


def _key_terms(text: str, n: int = 10) -> list[str]:
    from collections import Counter

    return [t for t, _ in Counter(content_terms(text)).most_common(n)]
