"""Coverage: how much of a course's required content exists, verified, per concept.

Requirements come from the course's `content_targets` (the syllabus files' content_requirements):
a default for every concept, overridden per subject and per chapter. The report answers "is the
course ready to publish?", shows reviewers and the generation engine where the gaps are, and
checks whether the mock-only question pool can fill the planned full mocks of each exam stage.
"""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessment import service as assessment
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Course, CourseNode, NodeConcept
from app.modules.content.models import Flashcard, Formula, Lesson, Shortcut

COUNTED = ("formulas", "shortcuts", "patterns", "practice_questions", "mock_questions", "flashcards")
# Courses without syllabus targets (the Python seed courses) are judged by this.
DEFAULT_REQUIREMENTS = {
    "lesson_levels": [1],
    "locales": ["en"],
    "formulas": 0,
    "shortcuts": 0,
    "patterns": 0,
    "practice_questions": 5,
    "mock_questions": 0,
    "flashcards": 0,
}


def requirement(targets: dict, subject: str, chapter: str) -> dict:
    req = targets.get("requirements") or {}
    merged = {**DEFAULT_REQUIREMENTS, **req.get("default", {})}
    merged.update(req.get("subjects", {}).get(subject, {}))
    merged.update(req.get("chapters", {}).get(f"{subject}.{chapter}", {}))
    return merged


def _placements(db: Session, course: Course) -> list[dict]:
    """Each concept once, in syllabus order, with the subject and chapter it is first placed under."""
    nodes = {n.id: n for n in db.scalars(select(CourseNode).where(CourseNode.course_id == course.id))}
    order = catalog.node_order(list(nodes.values()))

    def path(node: CourseNode) -> list[CourseNode]:
        chain = [node]
        while chain[-1].parent_id and chain[-1].parent_id in nodes:
            chain.append(nodes[chain[-1].parent_id])
        return list(reversed(chain))

    rows = db.execute(select(NodeConcept).where(NodeConcept.node_id.in_(list(nodes)))).scalars().all() if nodes else []
    rows = sorted(rows, key=lambda r: (order.get(r.node_id, 10**6), r.position))
    seen: set = set()
    out = []
    for link in rows:
        if link.concept_id in seen:
            continue
        seen.add(link.concept_id)
        chain = path(nodes[link.node_id])
        subject, chapter = chain[0], chain[1] if len(chain) > 1 else chain[0]
        out.append(
            {
                "concept_id": link.concept_id,
                "subject": subject.key or subject.title,
                "subject_title": subject.title,
                "chapter": (chapter.key or chapter.title).split(".")[-1],
                "chapter_title": chapter.title,
                "tiers": link.tiers or [],
            }
        )
    return out


def _have(db: Session, concept_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    have: dict[uuid.UUID, dict] = {cid: {k: 0 for k in COUNTED} | {"lessons": set(), "pyq_questions": 0} for cid in concept_ids}
    if not concept_ids:
        return have
    for cid, level, locale in db.execute(
        select(Lesson.concept_id, Lesson.level, Lesson.locale).where(Lesson.concept_id.in_(concept_ids), Lesson.status == "verified").distinct()
    ):
        have[cid]["lessons"].add((level, locale))
    for model, name in ((Formula, "formulas"), (Shortcut, "shortcuts"), (Flashcard, "flashcards")):
        for cid, n in db.execute(
            select(model.concept_id, func.count()).where(model.concept_id.in_(concept_ids), model.status == "verified").group_by(model.concept_id)
        ):
            have[cid][name] = n
    for cid, counts in assessment.verified_counts(db, concept_ids).items():
        have[cid].update(counts)
    return have


def _missing(req: dict, got: dict) -> dict:
    missing: dict = {}
    lessons = [f"{lv}/{loc}" for loc in req["locales"] for lv in req["lesson_levels"] if (lv, loc) not in got["lessons"]]
    if lessons:
        missing["lessons"] = lessons
    for k in COUNTED:
        need = int(req.get(k, 0))
        if got.get(k, 0) < need:
            missing[k] = need - got.get(k, 0)
    return missing


def concept_gaps(db: Session, course: Course) -> list[dict]:
    """Per concept: what is required, what exists (verified) and what is missing."""
    placements = _placements(db, course)
    concepts = {c.id: c for c, _w, _i in catalog.course_concepts(db, course.id)}
    have = _have(db, [p["concept_id"] for p in placements])
    out = []
    for p in placements:
        req = requirement(course.content_targets or {}, p["subject"], p["chapter"])
        got = have[p["concept_id"]]
        concept = concepts.get(p["concept_id"])
        out.append(
            {
                **p,
                "concept_id": str(p["concept_id"]),
                "slug": concept.slug if concept else "",
                "title": concept.title if concept else "",
                "have": {**{k: got.get(k, 0) for k in (*COUNTED, "pyq_questions")}, "lessons": sorted(f"{lv}/{loc}" for lv, loc in got["lessons"])},
                "missing": _missing(req, got),
            }
        )
    return out


def course_coverage(db: Session, course: Course, scope: str | None = None) -> dict:
    """Totals per subject and chapter; `scope` ("subject" or "subject.chapter") adds its concepts."""
    gaps = concept_gaps(db, course)
    subjects: dict[str, dict] = {}
    totals = _bucket("Course")
    for g in gaps:
        s = subjects.setdefault(g["subject"], _bucket(g["subject_title"]) | {"chapters": {}})
        ch = s["chapters"].setdefault(g["chapter"], _bucket(g["chapter_title"]))
        for bucket in (totals, s, ch):
            _add(bucket, g)
    report = {
        "course": {"slug": course.slug, "title": course.title, "status": course.status, "content_policy": course.content_policy},
        "totals": _finish(totals),
        "subjects": [{"key": key, **_finish(s), "chapters": [{"key": ck, **_finish(c)} for ck, c in s["chapters"].items()]} for key, s in subjects.items()],
        "mocks": mock_readiness(db, course, gaps),
        "ready": totals["concepts"] > 0 and totals["complete"] == totals["concepts"],
    }
    if scope:
        report["concepts"] = [g for g in gaps if scope in (g["subject"], f"{g['subject']}.{g['chapter']}")]
    return report


def _bucket(title: str) -> dict:
    return {"title": title, "concepts": 0, "complete": 0, "missing": defaultdict(int)}


def _add(bucket: dict, gap: dict) -> None:
    bucket["concepts"] += 1
    bucket["complete"] += 0 if gap["missing"] else 1
    for k, v in gap["missing"].items():
        bucket["missing"][k] += len(v) if isinstance(v, list) else v


def _finish(bucket: dict) -> dict:
    n = bucket["concepts"]
    return {
        "title": bucket["title"],
        "concepts": n,
        "complete": bucket["complete"],
        "percent": round(100 * bucket["complete"] / n, 1) if n else 0.0,
        "missing": dict(bucket["missing"]),
    }


def mock_readiness(db: Session, course: Course, gaps: list[dict]) -> list[dict]:
    """Per exam stage and section: verified mock-pool questions available vs needed for the planned mocks."""
    targets = (course.content_targets or {}).get("mock_targets", {})
    out = []
    for exam in catalog.course_exams(db, course):
        mocks = int(targets.get(exam.slug, 0))
        stage = (exam.pattern or {}).get("stage")
        sections = []
        for sec in (exam.pattern or {}).get("sections", []):
            subject = sec.get("subject")
            have = sum(g["have"]["mock_questions"] for g in gaps if g["subject"] == subject and (not g["tiers"] or stage in g["tiers"]))
            need = mocks * int(sec.get("questions", 0))
            sections.append({"name": sec.get("name"), "subject": subject, "questions_per_mock": sec.get("questions", 0), "needed": need, "available": have})
        out.append(
            {"exam": exam.slug, "name": exam.name, "mocks_planned": mocks, "sections": sections, "ready": all(s["available"] >= s["needed"] for s in sections)}
        )
    return out
