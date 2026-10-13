"""The syllabus file format, validated strictly (unknown fields are errors).

A syllabus is one directory per exam course:

    course.yaml            the course, the exam stages it prepares for, what "complete" means
                           for each concept (content requirements), mock targets and the
                           course-level exam strategies
    exam_profiles.yaml     the exam stages (sections, marking, duration), dated with `as_of`
    <subject>/subject.yaml one directory per subject: title, tiers, strategies, chapter order
    <subject>/<chapter>.yaml
                           chapter → topics → (sub topics) → concepts; each concept may carry
                           formulas, exam question patterns and shortcuts

Nodes have keys unique among their siblings; the stored node key is the dotted path
("quant.percentage.successive-change"). Concept slugs are global (the concept graph is shared
by every course, so mastery earned once counts everywhere): reuse a concept defined elsewhere
with `ref:` instead of defining it again. Formula, pattern and shortcut keys are local to their
concept and stored as "<concept slug>:<key>".

The syllabus says what the exam covers and the facts an author is sure of (summaries,
prerequisites, formulas, patterns, shortcuts). Lessons, questions and flashcards are generated
once by the content engine, reviewed, stored and then served to every learner.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.modules.content.models import SHORTCUT_KINDS

Key = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=40)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Stage = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+$", max_length=20)]  # e.g. tier1
Difficulty = Literal["easy", "medium", "hard"]
Frequency = Literal["high", "medium", "low", "rare"]
ShortcutKind = Literal[SHORTCUT_KINDS]  # type: ignore[valid-type]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _unique(items: list, attr: str, where: str) -> None:
    seen: set[str] = set()
    for item in items:
        value = getattr(item, attr)
        if value in seen:
            raise ValueError(f"duplicate {attr} {value!r} in {where}")
        seen.add(value)


# --------------------------------------------------------------------------- exam profiles


class SectionSpec(Strict):
    name: Text
    subject: Key | None = None  # the subject directory this section draws questions from
    questions: int = Field(ge=1)
    marks: float = Field(gt=0)
    marks_per_question: float | None = Field(default=None, gt=0)  # default: the pattern's
    negative_marks: float | None = Field(default=None, ge=0)
    duration_minutes: float | None = Field(default=None, gt=0)  # for sections timed on their own
    qualifying: bool = False  # must be passed, not counted in the merit
    session: str = ""  # Tier 2: "Session I"
    group: str = ""  # Tier 2: "Section I" (its modules share one timer)
    module: str = ""  # Tier 2: "Module I"


class ComponentSpec(Strict):
    """A part of the exam that is not a question paper (e.g. the data entry speed test)."""

    name: Text
    duration_minutes: float = Field(gt=0)
    qualifying: bool = True
    session: str = ""
    description: str = ""


class PatternSpec(Strict):
    sections: list[SectionSpec] = Field(min_length=1)
    marks_per_question: float = Field(gt=0)
    negative_marks: float = Field(ge=0)
    duration_minutes: float = Field(gt=0)
    minutes_per_question: float = Field(gt=0)  # what a mock built from this pattern allows
    default_section: Text
    mode: str = "Computer-based test"
    qualifying: bool = False  # the whole stage only has to be passed (merit comes from a later stage)
    components: list[ComponentSpec] = []
    notes: list[str] = []

    @model_validator(mode="after")
    def _consistent(self):
        for s in self.sections:
            per = s.marks_per_question or self.marks_per_question
            if abs(s.questions * per - s.marks) > 1e-9:
                raise ValueError(f"section {s.name!r}: {s.questions} questions × {per} marks is not {s.marks}")
        if self.default_section not in {s.name for s in self.sections}:
            raise ValueError(f"default_section {self.default_section!r} is not one of the sections")
        _unique(self.sections, "name", "sections")
        return self


class ExamProfileSpec(Strict):
    slug: Slug
    name: Text
    body: str = ""
    domain: str = "competitive"
    stage: Stage  # what syllabus `tiers` refer to
    pattern: PatternSpec


class ExamProfilesFile(Strict):
    as_of: Text  # the notice the pattern was taken from
    source: Text
    verify: Text  # what to re-check before each exam cycle
    profiles: list[ExamProfileSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _keys(self):
        _unique(self.profiles, "slug", "exam_profiles.yaml")
        _unique(self.profiles, "stage", "exam_profiles.yaml")
        return self


# --------------------------------------------------------------------------- concept content


class Variable(Strict):
    symbol: Text
    meaning: Text


class Example(Strict):
    problem: Text
    solution: Text


class FormulaSpec(Strict):
    key: Key
    name: Text
    expression: Text  # plain text, standard notation: "A = P(1 + R/100)^T"
    variables: list[Variable] = []
    conditions: str = ""
    example: Example | None = None


class PatternQSpec(Strict):
    """A recurring way the exam asks about the concept."""

    key: Key
    title: Text
    description: str = ""
    example_stem: str = ""
    frequency: Frequency = "medium"  # the author's estimate; PYQ counts are computed separately
    tiers: list[Stage] = []  # default: the concept's
    difficulty: Difficulty = "medium"
    target_seconds: int = Field(default=60, ge=10, le=600)


class ShortcutExample(Strict):
    problem: Text
    standard: str = ""  # the long way, for contrast
    shortcut: Text
    seconds_saved: int | None = Field(default=None, ge=0, le=600)


class ShortcutSpec(Strict):
    key: Key
    title: Text
    kind: ShortcutKind = "shortcut"
    rule: Text
    when_to_use: str = ""
    steps: list[str] = []
    example: ShortcutExample | None = None
    pitfalls: list[str] = []
    pattern: Key | None = None  # a pattern key of the same concept that this cracks


class ConceptSpec(Strict):
    """A concept defined here (slug + title + summary) or one defined elsewhere (`ref`).

    A `ref` entry places an existing concept in this syllabus; it may add formulas, patterns
    and shortcuts (they belong to the concept, so every course sees them), but its title,
    summary and prerequisites stay with the course that defines it."""

    slug: Slug | None = None
    ref: Slug | None = None
    title: str = ""
    summary: str = ""
    difficulty: Difficulty | None = None
    weight: float = Field(default=1.0, ge=0.1, le=5.0)  # exam importance within its topic
    tiers: list[Stage] = []  # default: the node's
    prerequisites: list[Slug] = []
    formulas: list[FormulaSpec] = []
    patterns: list[PatternQSpec] = []
    shortcuts: list[ShortcutSpec] = []

    @property
    def id(self) -> str:
        return self.slug or self.ref or ""

    @model_validator(mode="after")
    def _shape(self):
        if bool(self.slug) == bool(self.ref):
            raise ValueError("a concept needs exactly one of slug (define it here) or ref (reuse it)")
        if self.slug and not (self.title.strip() and self.summary.strip()):
            raise ValueError(f"concept {self.slug}: title and summary are required")
        if self.ref and (self.title or self.summary or self.difficulty or self.prerequisites):
            raise ValueError(f"concept ref {self.ref}: title, summary, difficulty and prerequisites belong to the defining course")
        if self.id in self.prerequisites:
            raise ValueError(f"concept {self.id} lists itself as a prerequisite")
        for attr in ("formulas", "patterns", "shortcuts"):
            _unique(getattr(self, attr), "key", f"concept {self.id} {attr}")
        patterns = {p.key for p in self.patterns}
        for s in self.shortcuts:
            if s.pattern and s.pattern not in patterns:
                raise ValueError(f"concept {self.id}: shortcut {s.key} points at unknown pattern {s.pattern!r}")
        return self


# --------------------------------------------------------------------------- strategies


class StrategySpec(Strict):
    """How to approach an exam stage, a subject or a chapter."""

    key: Key
    title: Text
    exam: Slug | None = None  # the exam profile it is for; default: every stage of the course
    summary: str = ""
    minutes: float | None = Field(default=None, gt=0)  # time to budget
    seconds_per_question: int | None = Field(default=None, gt=0, le=600)
    target_attempts: int | None = Field(default=None, ge=1)
    accuracy_target: float | None = Field(default=None, ge=0.5, le=1.0)
    attempt_order: list[str] = []
    tactics: list[Text] = Field(min_length=1)
    avoid: list[str] = []

    def body(self) -> dict:
        return self.model_dump(exclude={"key", "title", "exam"}, exclude_none=True)


# --------------------------------------------------------------------------- tree


class SubtopicSpec(Strict):
    key: Key
    title: Text
    tiers: list[Stage] = []
    concepts: list[ConceptSpec] = Field(min_length=1)


class TopicSpec(Strict):
    key: Key
    title: Text
    tiers: list[Stage] = []
    concepts: list[ConceptSpec] = []
    subtopics: list[SubtopicSpec] = []

    @model_validator(mode="after")
    def _children(self):
        if not self.concepts and not self.subtopics:
            raise ValueError(f"topic {self.key}: needs concepts or subtopics")
        _unique(self.subtopics, "key", f"topic {self.key}")
        return self


class ChapterSpec(Strict):
    key: Key
    title: Text
    tiers: list[Stage] = []
    strategies: list[StrategySpec] = []
    topics: list[TopicSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _children(self):
        _unique(self.topics, "key", f"chapter {self.key}")
        _unique(self.strategies, "key", f"chapter {self.key} strategies")
        return self


class SubjectSpec(Strict):
    key: Key
    title: Text
    description: str = ""
    tiers: list[Stage] = Field(min_length=1)
    strategies: list[StrategySpec] = []
    chapters: list[Key] = Field(min_length=1)  # chapter files in this directory, in order

    @field_validator("chapters")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("chapters listed twice")
        return v


# --------------------------------------------------------------------------- course


class Requirements(Strict):
    """Verified content each concept needs before the course counts it as complete."""

    lesson_levels: list[int] | None = None  # 1 beginner … 4 expert
    locales: list[str] | None = None
    formulas: int | None = Field(default=None, ge=0)
    shortcuts: int | None = Field(default=None, ge=0)
    patterns: int | None = Field(default=None, ge=0)
    practice_questions: int | None = Field(default=None, ge=0)
    mock_questions: int | None = Field(default=None, ge=0)
    flashcards: int | None = Field(default=None, ge=0)

    @field_validator("lesson_levels")
    @classmethod
    def _levels(cls, v):
        if v is not None and any(not 1 <= lv <= 4 for lv in v):
            raise ValueError("lesson levels are 1 (beginner) to 4 (expert)")
        return v

    def merged(self, override: "Requirements | None") -> "Requirements":
        if not override:
            return self
        return self.model_copy(update=override.model_dump(exclude_none=True))


class ContentRequirements(Strict):
    default: Requirements
    subjects: dict[Key, Requirements] = {}
    chapters: dict[str, Requirements] = {}  # "subject.chapter"

    @model_validator(mode="after")
    def _complete_default(self):
        missing = [k for k, v in self.default.model_dump().items() if v is None]
        if missing:
            raise ValueError(f"content_requirements.default must set {missing}")
        return self

    def for_node(self, subject: str, chapter: str) -> Requirements:
        return self.default.merged(self.subjects.get(subject)).merged(self.chapters.get(f"{subject}.{chapter}"))


class CourseFile(Strict):
    slug: Slug
    title: Text
    description: str = ""
    domain: str = "competitive"
    level: str = "beginner to exam level"
    locales: list[str] = ["en"]
    color: str = "indigo"
    status: Literal["published", "draft"] = "draft"
    content_policy: Literal["open", "reviewed_only"] = "reviewed_only"
    # Status of formulas, patterns, shortcuts and strategies written in these files when they are
    # new or changed. "in_review" sends them through the review queue like generated content.
    authored_status: Literal["in_review", "verified"] = "in_review"
    exams: list[Slug] = Field(min_length=1)  # exam profile slugs; the first is the course's main one
    subjects: list[Key] = Field(min_length=1)  # subject directories, in order
    content_requirements: ContentRequirements
    mock_targets: dict[Slug, int] = {}  # full mocks wanted per exam stage
    strategies: list[StrategySpec] = []

    @model_validator(mode="after")
    def _keys(self):
        if len(set(self.exams)) != len(self.exams) or len(set(self.subjects)) != len(self.subjects):
            raise ValueError("exams and subjects must not repeat")
        _unique(self.strategies, "key", "course strategies")
        return self
