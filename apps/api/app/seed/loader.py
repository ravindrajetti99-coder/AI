"""Idempotent seed loader.

Upserts exam profiles, courses, the course tree, the shared concept graph, lessons,
flashcards, questions (with solution steps and rubrics) and one mock test per course.
Every item has a stable key (slug, concept + level + locale, `Question.external_key`),
so re-running updates content in place instead of duplicating it. Seeded questions that
disappear from the seed files are retired, never deleted, so learners' attempts survive.
"""

import random
from collections import Counter
from types import ModuleType

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.ai.schemas import LessonOut
from app.core.config import get_settings
from app.modules.assessment import service as qservice
from app.modules.assessment.models import (
    DIFFICULTY_B,
    QUESTION_TYPES,
    STEP_KINDS,
    Question,
    QuestionConcept,
    Rubric,
    SolutionStep,
    Test,
    TestItem,
)
from app.modules.catalog.models import DOMAINS, NODE_TYPES, Concept, ConceptEdge, Course, CourseNode, ExamProfile, NodeConcept
from app.modules.content.models import Flashcard, Lesson
from app.modules.identity import service as identity
from app.modules.identity.models import User
from app.modules.ingest import service as ingest
from app.modules.learning.models import TestAttempt
from app.seed.courses import ALL_COURSES

GENERATED_PER_CONCEPT = 12
MOCK_QUESTIONS = 20


class SeedError(Exception):
    pass


def _set(obj, stats: Counter, kind: str, **values) -> None:
    """Assign only the fields that differ, counting the object as updated when any did."""
    changed = False
    for k, v in values.items():
        if getattr(obj, k) != v:
            setattr(obj, k, v)
            changed = True
    if changed and inspect(obj).persistent:  # new rows are counted as created, not updated
        stats[f"{kind}.updated"] += 1


# --------------------------------------------------------------------------- validation


def validate_question(key: str, item: dict) -> None:
    """Structural checks so a typo in seed content fails loudly instead of shipping a broken key."""
    qtype, p = item.get("qtype"), item.get("payload", {})
    if qtype not in QUESTION_TYPES:
        raise SeedError(f"{key}: unknown qtype {qtype!r}")
    if not item.get("stem", "").strip():
        raise SeedError(f"{key}: empty stem")
    if item.get("difficulty", "medium") not in DIFFICULTY_B:
        raise SeedError(f"{key}: unknown difficulty {item.get('difficulty')!r}")
    ids = [str(o["id"]).lower() for o in p.get("options", [])]
    if qtype in ("mcq", "assertion_reason", "case_study"):
        if len(ids) < 2 or len(set(ids)) != len(ids) or str(p.get("answer", "")).lower() not in ids:
            raise SeedError(f"{key}: answer {p.get('answer')!r} is not one of the options {ids}")
        texts = [o["text"] for o in p["options"]]
        if len(set(texts)) != len(texts):
            raise SeedError(f"{key}: duplicate option texts {texts}")
    elif qtype == "multi":
        answers = [str(a).lower() for a in p.get("answers", [])]
        if not answers or any(a not in ids for a in answers):
            raise SeedError(f"{key}: answers {answers} are not all options {ids}")
    elif qtype == "numerical":
        if not isinstance(p.get("answer"), (int, float)):
            raise SeedError(f"{key}: numerical answer must be a number")
    elif qtype == "coding":
        if not p.get("function_name") or not p.get("tests"):
            raise SeedError(f"{key}: coding questions need function_name and tests")
        if not any(not t.get("hidden") for t in p["tests"]):
            raise SeedError(f"{key}: coding questions need at least one visible example test")
    elif qtype in ("descriptive", "interview"):
        if not item.get("rubric"):
            raise SeedError(f"{key}: {qtype} questions need a rubric")
    elif qtype == "speaking":
        if not p.get("sentence"):
            raise SeedError(f"{key}: speaking questions need a sentence")


def _question_items(slug: str, spec: dict) -> list[tuple[str, dict, str]]:
    """(external_key, item, source) for every question of a concept, in a stable order."""
    items: list[tuple[str, dict, str]] = []
    gen = spec.get("generator")
    if gen:
        rng = random.Random(slug)
        seen: set[str] = set()
        for item in gen(rng, spec.get("generator_count", GENERATED_PER_CONCEPT)):
            if item["stem"] in seen:  # generators draw with replacement; keep one of each
                continue
            seen.add(item["stem"])
            items.append((f"{slug}:gen:{len(seen) - 1}", item, "generator"))
    for list_name in ("questions", "extra"):
        for i, item in enumerate(spec.get(list_name, [])):
            items.append((f"{slug}:{list_name}:{i}", item, item.get("source", "manual")))
    for key, item, _ in items:
        validate_question(key, item)
    return items


# --------------------------------------------------------------------------- upserts


def upsert_exam_profile(db: Session, spec: dict, stats: Counter) -> ExamProfile:
    ep = db.scalar(select(ExamProfile).where(ExamProfile.slug == spec["slug"]))
    if not ep:
        ep = ExamProfile(slug=spec["slug"], name=spec["name"], domain=spec["domain"])
        db.add(ep)
        stats["exam_profiles.created"] += 1
    _set(ep, stats, "exam_profiles", name=spec["name"], body=spec.get("body", ""), domain=spec["domain"], pattern=spec.get("pattern", {}))
    db.flush()
    return ep


def upsert_course(db: Session, spec: dict, exam: ExamProfile | None, stats: Counter) -> Course:
    if spec["domain"] not in DOMAINS:
        raise SeedError(f"course {spec['slug']}: unknown domain {spec['domain']!r}")
    course = db.scalar(select(Course).where(Course.slug == spec["slug"]))
    if not course:
        course = Course(slug=spec["slug"], title=spec["title"], domain=spec["domain"])
        db.add(course)
        stats["courses.created"] += 1
    _set(
        course,
        stats,
        "courses",
        title=spec["title"],
        description=spec.get("description", ""),
        domain=spec["domain"],
        level=spec.get("level", "beginner"),
        locales=list(spec.get("locales", ["en"])),
        color=spec.get("color", "indigo"),
        exam_profile_id=exam.id if exam else None,
        status=spec.get("status", "published"),
    )
    db.flush()
    return course


def upsert_concept(db: Session, slug: str, spec: dict, domain: str, stats: Counter) -> Concept:
    concept = db.scalar(select(Concept).where(Concept.slug == slug))
    if not concept:
        concept = Concept(slug=slug, title=spec["title"], domain=domain)
        db.add(concept)
        stats["concepts.created"] += 1
    _set(concept, stats, "concepts", title=spec["title"], summary=spec.get("summary", ""), domain=domain)
    db.flush()
    return concept


def upsert_tree(db: Session, course: Course, tree: list, concepts: dict[str, Concept], specs: dict, stats: Counter) -> None:
    """tree: [(title, children)] where children are nested (title, children) nodes or concept slugs.
    Depth sets the node type: module > chapter > topic > subtopic."""

    def walk(items: list, parent_id, depth: int) -> None:
        if depth >= len(NODE_TYPES):
            raise SeedError(f"course {course.slug}: tree deeper than {len(NODE_TYPES)} levels")
        for pos, (title, children) in enumerate(items):
            parent_filter = CourseNode.parent_id.is_(None) if parent_id is None else CourseNode.parent_id == parent_id
            node = db.scalar(select(CourseNode).where(CourseNode.course_id == course.id, CourseNode.title == title, parent_filter))
            if not node:
                node = CourseNode(course_id=course.id, parent_id=parent_id, node_type=NODE_TYPES[depth], title=title, position=pos)
                db.add(node)
                db.flush()
                stats["nodes.created"] += 1
            _set(node, stats, "nodes", node_type=NODE_TYPES[depth], position=pos)
            slugs = [c for c in children if isinstance(c, str)]
            for cpos, slug in enumerate(slugs):
                # A tree may reuse a concept owned by another course; it must already be loaded.
                concept = concepts.get(slug) or db.scalar(select(Concept).where(Concept.slug == slug))
                if not concept:
                    raise SeedError(f"course {course.slug}: tree references unknown concept {slug!r}")
                weight = float(specs.get(slug, {}).get("weight", 1.0))
                link = db.scalar(select(NodeConcept).where(NodeConcept.node_id == node.id, NodeConcept.concept_id == concept.id))
                if not link:
                    db.add(NodeConcept(node_id=node.id, concept_id=concept.id, weight=weight, position=cpos))
                    stats["node_concepts.created"] += 1
                else:
                    _set(link, stats, "node_concepts", weight=weight, position=cpos)
            walk([c for c in children if not isinstance(c, str)], node.id, depth + 1)

    walk(tree, None, 0)
    db.flush()


def upsert_prerequisites(db: Session, concept: Concept, prereq_slugs: list[str], concepts: dict[str, Concept], stats: Counter) -> None:
    for slug in prereq_slugs:
        pre = concepts.get(slug) or db.scalar(select(Concept).where(Concept.slug == slug))
        if not pre:
            raise SeedError(f"concept {concept.slug}: unknown prerequisite {slug!r}")
        if pre.id == concept.id:
            raise SeedError(f"concept {concept.slug} lists itself as a prerequisite")
        exists = db.scalar(
            select(ConceptEdge).where(ConceptEdge.from_concept_id == pre.id, ConceptEdge.to_concept_id == concept.id, ConceptEdge.kind == "prerequisite")
        )
        if not exists:
            db.add(ConceptEdge(from_concept_id=pre.id, to_concept_id=concept.id, kind="prerequisite"))
            stats["prerequisites.created"] += 1


def upsert_lessons(db: Session, concept: Concept, lessons: dict, stats: Counter) -> None:
    for (level, locale), body in lessons.items():
        if not 1 <= level <= 4:
            raise SeedError(f"concept {concept.slug}: lesson level {level} out of range")
        body = LessonOut.model_validate(body).model_dump()
        lesson = db.scalar(
            select(Lesson)
            .where(Lesson.concept_id == concept.id, Lesson.level == level, Lesson.locale == locale, Lesson.source == "manual")
            .order_by(Lesson.version.desc())
            .limit(1)
        )
        if lesson:
            _set(lesson, stats, "lessons", body=body)
            continue
        version = (db.scalar(select(func.max(Lesson.version)).where(Lesson.concept_id == concept.id, Lesson.level == level, Lesson.locale == locale)) or 0) + 1
        db.add(
            Lesson(
                concept_id=concept.id,
                level=level,
                locale=locale,
                body=body,
                source="manual",
                prompt_version="seed",
                status="verified",
                version=version,
            )
        )
        stats["lessons.created"] += 1


def upsert_flashcards(db: Session, concept: Concept, cards: list, stats: Counter) -> None:
    for card in cards:
        front, back, locale = (*card, "en")[:3]
        fc = db.scalar(
            select(Flashcard).where(Flashcard.concept_id == concept.id, Flashcard.front == front, Flashcard.locale == locale, Flashcard.source == "manual")
        )
        if not fc:
            db.add(Flashcard(concept_id=concept.id, front=front, back=back, locale=locale, source="manual", status="verified"))
            stats["flashcards.created"] += 1
        else:
            _set(fc, stats, "flashcards", back=back)


def _sync_steps(db: Session, q: Question, steps_map: dict) -> None:
    existing = {s.step_no: s for s in db.scalars(select(SolutionStep).where(SolutionStep.question_id == q.id)).all()}
    for step_no, kind in enumerate(STEP_KINDS, start=1):
        body = (steps_map or {}).get(kind, "")
        step = existing.pop(step_no, None)
        if body and step:
            step.kind, step.body = kind, body
        elif body:
            db.add(SolutionStep(question_id=q.id, step_no=step_no, kind=kind, body=body))
        elif step:
            db.delete(step)
    for step in existing.values():
        db.delete(step)


def _sync_rubric(db: Session, q: Question, criteria: list | None, model_answer: str) -> None:
    rubric = db.scalar(select(Rubric).where(Rubric.question_id == q.id))
    if criteria is None:
        if rubric:
            db.delete(rubric)
        return
    if rubric:
        rubric.criteria, rubric.model_answer = criteria, model_answer
    else:
        db.add(Rubric(question_id=q.id, criteria=criteria, model_answer=model_answer))


def upsert_questions(db: Session, slug: str, concept: Concept, spec: dict, stats: Counter) -> None:
    keys = set()
    for key, item, source in _question_items(slug, spec):
        keys.add(key)
        difficulty = item.get("difficulty", "medium")
        q = db.scalar(select(Question).where(Question.external_key == key))
        if not q:
            qservice.add_question(
                db,
                qtype=item["qtype"],
                stem=item["stem"],
                payload=item["payload"],
                concept_ids=[concept.id],
                explanation=item.get("explanation", ""),
                difficulty=difficulty,
                steps_map=item.get("steps"),
                rubric=item.get("rubric"),
                model_answer=item.get("model_answer", ""),
                source=source,
                pyq_year=item.get("pyq_year"),
                locale=item.get("locale", "en"),
                external_key=key,
            )
            stats["questions.created"] += 1
            continue
        if q.difficulty != difficulty:
            q.difficulty_b = DIFFICULTY_B[difficulty]  # a new label resets the calibrated difficulty
        _set(
            q,
            stats,
            "questions",
            qtype=item["qtype"],
            stem=item["stem"],
            payload=item["payload"],
            explanation=item.get("explanation", ""),
            difficulty=difficulty,
            source=source,
            pyq_year=item.get("pyq_year"),
            locale=item.get("locale", "en"),
        )
        if q.status == "retired" and q.external_key:  # retired by an earlier load, back in the seed
            q.status = "verified"
        _sync_steps(db, q, item.get("steps"))
        _sync_rubric(db, q, item.get("rubric"), item.get("model_answer", ""))
        if not db.scalar(select(QuestionConcept).where(QuestionConcept.question_id == q.id, QuestionConcept.concept_id == concept.id)):
            db.add(QuestionConcept(question_id=q.id, concept_id=concept.id))
    db.flush()
    stale = db.scalars(
        select(Question).where(Question.external_key.startswith(f"{slug}:", autoescape=True), Question.status != "retired", Question.external_key.not_in(keys))
    ).all()
    for q in stale:
        q.status = "retired"
        stats["questions.retired"] += 1


def ensure_mock_test(db: Session, course: Course, stats: Counter) -> Test | None:
    """One full mock per course. It is rebuilt when its question set changes, unless learners
    have already taken it (their reports point at its items)."""
    pattern = ingest.exam_pattern(db, course)
    count = int(pattern.get("mock_questions", MOCK_QUESTIONS))
    slug = f"{course.slug}-mock-1"
    test = db.scalar(select(Test).where(Test.slug == slug))
    wanted = [q.id for q in ingest.pick_mock_questions(db, course, count)]
    if not wanted:
        stats["tests.skipped_no_questions"] += 1
        return None
    if test:
        current = list(db.scalars(select(TestItem.question_id).where(TestItem.test_id == test.id).order_by(TestItem.position)).all())
        taken = db.scalar(select(func.count()).select_from(TestAttempt).where(TestAttempt.test_id == test.id))
        if current == wanted or taken:
            return test
        db.delete(test)
        db.flush()
        stats["tests.rebuilt"] += 1
    else:
        stats["tests.created"] += 1
    return ingest.build_mock_test(db, course.id, count, title=f"{course.title}: Full mock test", slug=slug)


def bootstrap_admin(db: Session, stats: Counter) -> User | None:
    """Create (or promote) the first admin from EDU_ADMIN_EMAIL / EDU_ADMIN_PASSWORD.
    An existing account keeps its password: the seed never resets credentials."""
    s = get_settings()
    if not (s.admin_email and s.admin_password):
        return None
    if len(s.admin_password) < 12:
        raise SeedError("EDU_ADMIN_PASSWORD must be at least 12 characters")
    try:  # the same check sign-in applies, so the account can actually log in
        email = TypeAdapter(EmailStr).validate_python(s.admin_email.strip()).lower()
    except ValidationError as exc:
        raise SeedError(f"EDU_ADMIN_EMAIL is not a usable email address: {exc.errors()[0]['msg']}") from exc
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = identity.create_user(db, email, s.admin_password, "Administrator", role="admin")
        stats["admin.created"] += 1
    elif user.role != "admin":
        user.role = "admin"
        identity.audit(db, None, "seed_promote_admin", "user", user.id)
        db.commit()
        stats["admin.promoted"] += 1
    return user


# --------------------------------------------------------------------------- entry point


def load(db: Session, courses: list[ModuleType] | None = None, only: list[str] | None = None, build_tests: bool = True) -> Counter:
    """Load seed courses in one transaction. `only` filters by course slug."""
    stats: Counter = Counter()
    bootstrap_admin(db, stats)
    every = courses or ALL_COURSES
    modules = [m for m in every if not only or m.COURSE["slug"] in only]
    if only and len(modules) != len(set(only)):
        raise SeedError(f"unknown course slug in {only}; known: {sorted(m.COURSE['slug'] for m in every)}")
    # Specs come from every course, even with `only`, so a reused concept keeps the weight its
    # owning course gives it and partial loads never disagree with full ones.
    specs: dict[str, dict] = {}
    for m in every:
        for slug, spec in m.CONCEPTS.items():
            if slug in specs:
                raise SeedError(f"concept {slug!r} is defined in more than one seed course")
            specs[slug] = spec
    try:
        # Pass 1: every concept of the selected courses, so prerequisites may point across courses.
        concepts: dict[str, Concept] = {}
        for m in modules:
            for slug, spec in m.CONCEPTS.items():
                concepts[slug] = upsert_concept(db, slug, spec, m.COURSE["domain"], stats)
        # Pass 2: courses, trees, graph edges and learning assets.
        loaded: list[Course] = []
        for m in modules:
            exam_spec = m.COURSE.get("exam")
            exam = upsert_exam_profile(db, exam_spec, stats) if exam_spec else None
            course = upsert_course(db, m.COURSE, exam, stats)
            upsert_tree(db, course, m.COURSE["tree"], concepts, specs, stats)
            for slug, spec in m.CONCEPTS.items():
                concept = concepts[slug]
                upsert_prerequisites(db, concept, spec.get("prereqs", []), concepts, stats)
                upsert_lessons(db, concept, spec.get("lessons", {}), stats)
                upsert_flashcards(db, concept, spec.get("flashcards", []), stats)
                upsert_questions(db, slug, concept, spec, stats)
            loaded.append(course)
        db.flush()
        if build_tests:
            for course in loaded:
                ensure_mock_test(db, course, stats)
        db.commit()
    except Exception:
        db.rollback()
        raise
    stats["courses.loaded"] = len(loaded)
    return stats
