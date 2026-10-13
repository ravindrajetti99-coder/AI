import uuid

from pydantic import BaseModel, ConfigDict, Field


class ExamProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    body: str
    domain: str
    pattern: dict


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    description: str
    domain: str
    level: str
    locales: list[str]
    status: str
    color: str
    content_policy: str = "open"
    concept_count: int = 0
    question_count: int = 0


class ConceptBrief(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    weight: float = 1.0
    tiers: list[str] = []  # exam stages that test it in this course; empty = all


class NodeOut(BaseModel):
    id: uuid.UUID
    key: str | None = None
    node_type: str
    title: str
    position: int
    tiers: list[str] = []
    concepts: list[ConceptBrief] = []
    children: list["NodeOut"] = []


class CourseDetail(CourseOut):
    exam_profile: ExamProfileOut | None = None
    exams: list[ExamProfileOut] = []  # every exam stage the course prepares for, main one first
    strategies: list[dict] = []  # course- and subject-level exam strategies (verified)
    tree: list[NodeOut] = []


class ConceptOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str
    domain: str
    prerequisites: list[ConceptBrief] = []
    unlocks: list[ConceptBrief] = []
    lesson_levels: dict[str, list[int]] = {}  # locale -> levels available (verified)
    flashcard_count: int = 0
    question_count: int = 0
    courses: list[dict] = []


class CourseCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,120}$")
    title: str
    description: str = ""
    domain: str
    level: str = "beginner"
    locales: list[str] = ["en"]
    exam_profile_slug: str | None = None
    color: str = "indigo"


class NodeCreate(BaseModel):
    parent_id: uuid.UUID | None = None
    node_type: str = Field(pattern="^(module|chapter|topic|subtopic)$")
    title: str
    position: int = 0


class ConceptCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,160}$")
    title: str
    summary: str = ""
    domain: str
    node_id: uuid.UUID | None = None
    weight: float = 1.0
    prerequisite_slugs: list[str] = []


class ExamProfileCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    name: str
    body: str = ""
    domain: str
    pattern: dict = {}
