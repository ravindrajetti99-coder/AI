"""AI Question Generator and the personal 'why was I wrong' note of the Solution Engine."""

import random
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.ai import gateway, retrieval
from app.ai.schemas import MistakeNote, QuestionsOut
from app.ai.text import content_terms, sentences
from app.modules.catalog.models import Concept

PROMPT_VERSION = "questions-v1"


def generate_task(
    db: Session,
    concept: Concept,
    qtype: str,
    difficulty: str,
    count: int,
    exam_context: str = "",
    lesson_body: dict | None = None,
    course_id=None,
) -> gateway.Task:
    sources = retrieval.search(db, f"{concept.title} {concept.summary}", course_id=course_id, k=4)
    lesson_text = ""
    if lesson_body:
        lesson_text = "\n".join([lesson_body.get("definition", ""), lesson_body.get("explanation", "")] + lesson_body.get("key_points", []))
    system = (
        "You are a senior exam setter. Write original, unambiguous questions with exactly one defensible answer key "
        "(or the exact set for multi-correct). Options use ids a,b,c,d. For assertion_reason use the standard four options: "
        "a) Both A and R true, R explains A; b) Both true, R does not explain A; c) A true, R false; d) A false, R true. "
        "For numerical give numeric_answer and a sensible tolerance. For descriptive give rubric_points and a model_answer. "
        "Every question needs all six solution steps: hint (no answer reveal), concept needed, approach, full solution, "
        "shortcut (or empty), and common mistakes. Distractors must reflect real misconceptions."
    )
    user = (
        f"Concept: {concept.title}\nSummary: {concept.summary}\nExam pattern: {exam_context or 'general'}\n"
        f"Type: {qtype}. Difficulty: {difficulty}. Count: {count}.\n\nLesson:\n{lesson_text[:4000]}\n\n{gateway.fence(sources)}"
    )
    corpus = " ".join([concept.summary, lesson_text] + [s["text"] for s in sources])
    return gateway.Task(
        name="questions.generate",
        prompt_version=PROMPT_VERSION,
        tier="standard" if difficulty in ("beginner", "easy", "medium") else "heavy",
        system=system,
        user=user,
        schema=QuestionsOut,
        offline=lambda: offline_cloze(concept, corpus, count, difficulty),
        max_tokens=4000,
    )


def offline_cloze(concept: Concept, corpus: str, count: int, difficulty: str) -> dict:
    """Fill-in-the-blank MCQs built from source sentences: blank a key term, use other key
    terms from the same material as distractors. Deterministic per concept."""
    rng = random.Random(str(concept.id))
    freq = Counter(t for t in content_terms(corpus) if len(t) > 3)
    key_terms = [t for t, _ in freq.most_common(30)]
    questions = []
    used = set()
    for s in sentences(corpus):
        if len(questions) >= count:
            break
        words = content_terms(s)
        candidates = [t for t in key_terms if t in words and t not in used]
        if not candidates or len(s.split()) < 7:
            continue
        term = candidates[0]
        distractors = [t for t in key_terms if t != term and t not in words][:3]
        if len(distractors) < 3:
            continue
        used.add(term)
        stem = re.sub(rf"\b{re.escape(term)}\b", "_____", s, count=1, flags=re.I)
        opts = [term] + distractors
        rng.shuffle(opts)
        ids = ["a", "b", "c", "d"]
        answer = ids[opts.index(term)]
        questions.append(
            {
                "qtype": "mcq",
                "stem": f"Fill in the blank: {stem}",
                "options": [{"id": i, "text": o} for i, o in zip(ids, opts, strict=False)],
                "answer": answer,
                "explanation": s,
                "difficulty": difficulty,
                "steps": {
                    "hint": f"The missing word is a key term of {concept.title}.",
                    "concept": concept.summary or concept.title,
                    "approach": "Read the sentence and ask which term makes it a true statement about the concept.",
                    "solution": f"The complete statement is: {s}",
                    "shortcut": "",
                    "mistakes": "Picking a term that appears in the same chapter but describes a different idea.",
                },
            }
        )
    return {"questions": questions}


def mistake_note_task(question_stem: str, correct: str, chosen: str, explanation: str, mistakes_step: str) -> gateway.Task:
    return gateway.Task(
        name="solution.mistake_note",
        prompt_version=PROMPT_VERSION,
        tier="light",
        system=(
            "In 2-3 sentences, explain to the learner the most likely misconception behind their wrong answer, "
            "and the idea that fixes it. Be kind and specific."
        ),
        user=f"Question: {question_stem}\nCorrect answer: {correct}\nLearner answered: {chosen}\nExplanation: {explanation}\nKnown mistakes: {mistakes_step}",
        schema=MistakeNote,
        offline=lambda: {"note": _offline_note(correct, chosen, mistakes_step)},
        max_tokens=300,
        cacheable=True,
        cache_key_parts={"stem": question_stem[:500], "chosen": chosen},
    )


def _offline_note(correct: str, chosen: str, mistakes: str) -> str:
    base = f"You answered {chosen}, but the correct answer is {correct}."
    return f"{base} {mistakes}" if mistakes else base
