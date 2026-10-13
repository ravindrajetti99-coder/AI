"""Previous-year question (PYQ) import: one paper per file, JSON or CSV.

Every paper names its source and the licence it is used under; a file without them is refused.
Rows are validated like seed questions, fingerprinted (`stem_hash`) so a question already in the
bank is reported as a duplicate instead of stored twice, keyed `pyq:<paper>:<number>` so
re-importing a corrected file updates in place, and saved as `in_review`: nothing reaches
learners until a reviewer approves it. Rows without a concept are imported unmapped and listed
for staff to map. The upload is parsed and checked for syntax at once; the rows are processed by
the `pyq.import` job, so a large paper never ties up a request.

JSON: {"paper": {...}, "questions": [{"number": 1, "stem": "...", "options": [{"id": "a",
"text": "..."}], "answer": "b", "concepts": ["percentage-basics"], "pattern":
"percentage-basics:find-whole", ...}]}

CSV: one row per question with the columns in `CSV_COLUMNS` (option_a … option_e; concepts
separated by ";"); the paper is sent alongside the file.
"""

import csv
import io
import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError
from app.modules.assessment import service
from app.modules.assessment.models import DIFFICULTY_B, STEP_KINDS, PyqImport, PyqSource, Question, QuestionConcept
from app.modules.catalog.models import Concept

LICENCES = ("public-government-document", "owned", "licensed", "permission-granted")
CSV_COLUMNS = (
    "number",
    "section",
    "qtype",
    "stem",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "option_e",
    "answer",
    "explanation",
    "concepts",
    "pattern",
    "difficulty",
    "pool",
    *STEP_KINDS,
)
MAX_ERRORS = 500  # errors kept on an import row


class PaperIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9:._-]{2,119}$")  # e.g. ssc-cgl:tier1:2024-09-09:s1
    exam: str = Field(min_length=2, max_length=60)
    tier: str = Field(default="", max_length=20)
    year: int = Field(ge=1990, le=2100)
    exam_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    shift: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=200)
    source: str = Field(min_length=3, max_length=300)  # where the questions were taken from
    source_url: str = Field(default="", max_length=500)
    licence: Literal[LICENCES]  # type: ignore[valid-type]


class OptionIn(BaseModel):
    id: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1)


class RowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1, le=10_000)
    section: str = ""
    qtype: Literal["mcq", "multi", "numerical"] = "mcq"
    stem: str = Field(min_length=3)
    options: list[OptionIn] = []
    answer: str | float | list[str] | None = None
    tolerance: float = 0.0
    unit: str = ""
    explanation: str = ""
    concepts: list[str] = []
    pattern: str | None = None  # "<concept slug>:<pattern key>"
    difficulty: Literal["beginner", "easy", "medium", "hard", "expert"] = "medium"
    pool: Literal["practice", "mock"] = "practice"
    steps: dict[str, str] = {}
    locale: str = "en"

    @field_validator("steps")
    @classmethod
    def _steps(cls, v: dict) -> dict:
        unknown = set(v) - set(STEP_KINDS)
        if unknown:
            raise ValueError(f"unknown solution steps {sorted(unknown)}; use {list(STEP_KINDS)}")
        return {k: s for k, s in v.items() if s and s.strip()}

    def item(self) -> dict:
        """The seed-style item `validate_item` and `add_question` understand."""
        options = [o.model_dump() for o in self.options]
        if self.qtype == "mcq":
            payload = {"options": options, "answer": str(self.answer or "").lower()}
        elif self.qtype == "multi":
            answers = self.answer if isinstance(self.answer, list) else str(self.answer or "").replace(",", ";").split(";")
            payload = {"options": options, "answers": sorted({a.strip().lower() for a in answers if a.strip()})}
        else:
            try:
                answer = float(self.answer) if self.answer is not None and self.answer != "" else None
            except (TypeError, ValueError):
                answer = None
            payload = {"answer": answer, "tolerance": self.tolerance, "unit": self.unit}
        for o in payload.get("options", []):
            o["id"] = o["id"].lower()
        return {
            "qtype": self.qtype,
            "stem": self.stem.strip(),
            "payload": payload,
            "explanation": self.explanation,
            "difficulty": self.difficulty,
            "steps": self.steps,
        }


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=240)
    format: Literal["json", "csv"]
    content: str = Field(min_length=2)
    paper: PaperIn | None = None  # required for CSV; overrides the file's paper for JSON
    dry_run: bool = False


def _error(exc: ValidationError) -> str:
    e = exc.errors()[0]
    return f"{'.'.join(str(p) for p in e['loc']) or 'value'}: {e['msg']}"


def parse(body: ImportIn) -> dict:
    """Parse the upload into {"paper": {...}, "questions": [raw rows]}; raises AppError (422) for
    anything that makes the whole file unusable. Rows are validated one by one by the job."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    if len(body.content.encode()) > limit:
        raise AppError(f"File larger than {get_settings().max_upload_mb} MB", status=413)
    if body.format == "json":
        try:
            data = json.loads(body.content)
        except json.JSONDecodeError as exc:
            raise AppError(f"Not valid JSON: {exc}", status=422) from exc
        if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
            raise AppError('JSON must be an object with a "questions" list (and a "paper")', status=422)
        rows = data["questions"]
        paper = body.paper.model_dump() if body.paper else data.get("paper")
    else:
        if not body.paper:
            raise AppError("A CSV import needs the paper details (exam, year, source, licence)", status=422)
        reader = csv.DictReader(io.StringIO(body.content.lstrip("﻿")))
        unknown = set(reader.fieldnames or []) - set(CSV_COLUMNS)
        if not reader.fieldnames or unknown:
            raise AppError(f"Unknown CSV columns {sorted(unknown)}; allowed: {', '.join(CSV_COLUMNS)}", status=422)
        if not {"number", "stem"} <= set(reader.fieldnames):
            raise AppError("CSV needs at least the columns number and stem", status=422)
        rows = [_csv_row(r) for r in reader]
        paper = body.paper.model_dump()
    try:
        paper = PaperIn.model_validate(paper or {}).model_dump()
    except ValidationError as exc:
        raise AppError(f"Paper details: {_error(exc)}", status=422) from exc
    if not rows:
        raise AppError("The file has no questions", status=422)
    return {"paper": paper, "questions": rows}


def _csv_row(r: dict) -> dict:
    row: dict = {k: (v or "").strip() for k, v in r.items() if k}
    options = [{"id": letter, "text": row.pop(f"option_{letter}")} for letter in "abcde" if row.get(f"option_{letter}")]
    for letter in "abcde":
        row.pop(f"option_{letter}", None)
    steps = {k: row.pop(k) for k in STEP_KINDS if k in row}
    out = {k: v for k, v in row.items() if v != ""}
    out["options"] = options
    out["steps"] = steps
    if "concepts" in out:
        out["concepts"] = [c.strip() for c in out["concepts"].split(";") if c.strip()]
    return out


def submit(db: Session, user_id: uuid.UUID | None, body: ImportIn) -> PyqImport:
    """Store the parsed upload and enqueue its processing in the same transaction."""
    from app.jobs import service as jobs

    parsed = parse(body)
    imp = PyqImport(
        created_by=user_id,
        filename=body.filename,
        format=body.format,
        dry_run=body.dry_run,
        status="queued",
        payload=json.dumps(parsed, ensure_ascii=False),
        summary={"paper": parsed["paper"]["key"], "rows": len(parsed["questions"])},
    )
    db.add(imp)
    db.flush()
    job = jobs.enqueue(db, "pyq.import", {"import_id": str(imp.id)}, created_by=user_id)
    imp.job_id = job.id
    return imp


# --------------------------------------------------------------------------- processing (job)


def upsert_source(db: Session, paper: dict) -> PyqSource:
    src = db.scalar(select(PyqSource).where(PyqSource.key == paper["key"]))
    if src is None:
        src = PyqSource(**paper)
        db.add(src)
        db.flush()
    else:
        for k, v in paper.items():
            setattr(src, k, v)
    return src


class RowResult:
    CREATED, UPDATED, UNCHANGED, DUPLICATE, INVALID = "created", "updated", "unchanged", "duplicate", "invalid"


def import_row(db: Session, paper: dict, source: PyqSource | None, raw: dict, seen: set[str], dry_run: bool) -> tuple[str, str, bool]:
    """Process one row; returns (outcome, message, unmapped). `seen` holds the stem hashes of
    earlier rows of this file. With dry_run nothing is written."""
    try:
        row = RowIn.model_validate(raw)
    except ValidationError as exc:
        return RowResult.INVALID, _error(exc), False
    key = f"pyq:{paper['key']}:{row.number}"
    item = row.item()
    try:
        service.validate_item(f"question {row.number}", item)
    except ValueError as exc:
        return RowResult.INVALID, str(exc), False
    concepts = []
    for slug in row.concepts:
        c = db.scalar(select(Concept).where(Concept.slug == slug))
        if not c:
            return RowResult.INVALID, f"question {row.number}: unknown concept {slug!r}", False
        concepts.append(c)
    pattern = None
    if row.pattern:
        pattern = service.pattern_by_key(db, row.pattern)
        if not pattern:
            return RowResult.INVALID, f"question {row.number}: unknown pattern {row.pattern!r} (use <concept slug>:<pattern key>)", False
        if pattern.concept_id not in {c.id for c in concepts}:
            concepts.append(db.get(Concept, pattern.concept_id))  # a pattern implies its concept
    digest = service.stem_hash(item["stem"])
    if digest in seen:
        return RowResult.DUPLICATE, f"question {row.number}: repeats an earlier question of this file", False
    seen.add(digest)
    unmapped = not concepts
    existing = db.scalar(select(Question).where(Question.external_key == key))
    if existing is None:
        twin = db.scalar(select(Question).where(Question.stem_hash == digest, Question.status != "retired").limit(1))
        if twin is not None:
            return RowResult.DUPLICATE, f"question {row.number}: already in the bank as {twin.id} ({twin.source})", False
        if not dry_run:
            service.add_question(
                db,
                qtype=item["qtype"],
                stem=item["stem"],
                payload=item["payload"],
                concept_ids=[c.id for c in concepts],
                explanation=item["explanation"],
                difficulty=item["difficulty"],
                steps_map=item["steps"],
                source="pyq",
                status="in_review",
                pyq_year=paper["year"],
                locale=row.locale,
                external_key=key,
                pool=row.pool,
                pattern_id=pattern.id if pattern else None,
                pyq_source_id=source.id if source else None,
            )
        return RowResult.CREATED, "", unmapped
    values = {
        "qtype": item["qtype"],
        "stem": item["stem"],
        "payload": item["payload"],
        "explanation": item["explanation"],
        "difficulty": item["difficulty"],
        "pool": row.pool,
        "pattern_id": pattern.id if pattern else existing.pattern_id,
        "pyq_year": paper["year"],
        "locale": row.locale,
    }
    changed = any(getattr(existing, k) != v for k, v in values.items())
    if not changed:
        return RowResult.UNCHANGED, "", unmapped and not _has_concepts(db, existing)
    if not dry_run:
        for k, v in values.items():
            setattr(existing, k, v)
        existing.stem_hash = digest
        existing.difficulty_b = DIFFICULTY_B.get(item["difficulty"], existing.difficulty_b)
        existing.status = "in_review"  # a corrected question is reviewed again
        existing.pyq_source_id = source.id if source else existing.pyq_source_id
        service.replace_steps(db, existing.id, item["steps"])
        if concepts:
            set_concepts(db, existing, [c.id for c in concepts])
    return RowResult.UPDATED, "", unmapped and not _has_concepts(db, existing)


def _has_concepts(db: Session, q: Question) -> bool:
    return db.scalar(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == q.id).limit(1)) is not None


def set_concepts(db: Session, q: Question, concept_ids: list[uuid.UUID]) -> None:
    current = {link.concept_id: link for link in db.scalars(select(QuestionConcept).where(QuestionConcept.question_id == q.id))}
    for cid in concept_ids:
        if cid not in current:
            db.add(QuestionConcept(question_id=q.id, concept_id=cid))
    for cid, link in current.items():
        if cid not in concept_ids:
            db.delete(link)


def finish(imp: PyqImport, status: str, summary: dict, errors: list) -> None:
    imp.status, imp.summary, imp.errors, imp.finished_at = status, summary, errors[:MAX_ERRORS], utcnow()


# --------------------------------------------------------------------------- views


def import_row_out(imp: PyqImport, full: bool = False) -> dict:
    out = {
        "id": str(imp.id),
        "filename": imp.filename,
        "format": imp.format,
        "dry_run": imp.dry_run,
        "status": imp.status,
        "summary": imp.summary,
        "error_count": len(imp.errors or []),
        "job_id": str(imp.job_id) if imp.job_id else None,
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
        "finished_at": imp.finished_at.isoformat() if imp.finished_at else None,
    }
    if full:
        out["errors"] = imp.errors
    return out
