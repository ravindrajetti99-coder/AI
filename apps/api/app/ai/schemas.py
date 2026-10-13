"""Structured outputs for every AI task. Providers must return JSON matching these."""

from typing import Literal

from pydantic import BaseModel, Field


class Example(BaseModel):
    title: str
    body: str


class CheckQuestion(BaseModel):
    question: str
    answer: str


class LessonOut(BaseModel):
    definition: str
    explanation: str
    examples: list[Example] = Field(default_factory=list)
    diagram: str = ""  # Mermaid source, optional
    key_points: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    memory_technique: str = ""
    exam_relevance: str = ""
    check_questions: list[CheckQuestion] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class Option(BaseModel):
    id: str
    text: str


class Steps(BaseModel):
    hint: str
    concept: str
    approach: str
    solution: str
    shortcut: str = ""
    mistakes: str = ""


class GeneratedQuestion(BaseModel):
    qtype: Literal["mcq", "multi", "assertion_reason", "numerical", "descriptive"]
    stem: str
    options: list[Option] = Field(default_factory=list)
    answer: str = ""  # option id for mcq / assertion_reason
    answers: list[str] = Field(default_factory=list)  # option ids for multi
    numeric_answer: float | None = None
    tolerance: float = 0.0
    unit: str = ""
    explanation: str = ""
    difficulty: Literal["beginner", "easy", "medium", "hard", "expert"] = "medium"
    steps: Steps
    rubric_points: list[str] = Field(default_factory=list)  # descriptive only
    model_answer: str = ""


class QuestionsOut(BaseModel):
    questions: list[GeneratedQuestion]


class CriterionScore(BaseModel):
    criterion: str
    max_marks: float
    awarded: float
    comment: str = ""


class EvaluationOut(BaseModel):
    criteria: list[CriterionScore]
    total: float
    max_total: float
    missing_points: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    presentation_feedback: str = ""
    model_answer: str = ""


class TutorReply(BaseModel):
    reply: str
    follow_up_questions: list[str] = Field(default_factory=list)


class MistakeNote(BaseModel):
    note: str


class Finding(BaseModel):
    category: Literal["quality", "performance", "security", "correctness", "style"]
    severity: Literal["info", "warning", "error"] = "info"
    line: int | None = None
    message: str
    suggestion: str = ""


class CodeReviewOut(BaseModel):
    score: float = Field(ge=0, le=10)
    summary: str
    findings: list[Finding] = Field(default_factory=list)


class Correction(BaseModel):
    original: str
    corrected: str
    explanation: str


class VocabItem(BaseModel):
    word: str
    meaning: str


class LanguageReply(BaseModel):
    reply: str
    corrections: list[Correction] = Field(default_factory=list)
    vocabulary: list[VocabItem] = Field(default_factory=list)
    next_prompt: str = ""


class Flashcard(BaseModel):
    front: str
    back: str


class FlashcardsOut(BaseModel):
    cards: list[Flashcard]


class NotesOut(BaseModel):
    title: str
    summary: list[str]
    key_terms: list[str] = Field(default_factory=list)


class CareerPath(BaseModel):
    title: str
    why: str
    next_steps: list[str]
    course_slugs: list[str] = Field(default_factory=list)


class CareerOut(BaseModel):
    summary: str
    paths: list[CareerPath]


class MentorOut(BaseModel):
    message: str
    focus: list[str] = Field(default_factory=list)
