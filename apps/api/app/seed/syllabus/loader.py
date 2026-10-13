"""Load a validated syllabus into the database, idempotently.

Upserts by stable keys: exam profiles and the course by slug, nodes by their dotted key,
concepts by slug, formulas / patterns / shortcuts by "<concept>:<key>" and strategies by key.
Re-running after an edit updates in place:

- nodes and concept placements that left the files are deleted (they hold no learner data);
  concepts themselves are never deleted, so mastery and history survive a reorganisation;
- authored items (formulas, patterns, shortcuts, strategies) that left the files are retired;
- an authored item whose text changed goes back to `authored_status` (normally in_review), so
  a reviewer sees it again; an unchanged item keeps whatever status review gave it.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessment.models import DIFFICULTY_B, QuestionPattern
from app.modules.catalog.models import Concept, ConceptEdge, Course, CourseExam, CourseNode, ExamProfile, ExamStrategy, NodeConcept
from app.modules.content.models import Formula, Shortcut
from app.seed.syllabus import profile_pattern
from app.seed.syllabus.reader import Syllabus

SOURCE = "syllabus"  # `source` of authored items, so loaders never touch generated or edited ones


def _assign(obj, values: dict) -> bool:
    changed = False
    for k, v in values.items():
        if getattr(obj, k) != v:
            setattr(obj, k, v)
            changed = True
    return changed


def upsert_profiles(db: Session, syl: Syllabus, stats: Counter) -> dict[str, ExamProfile]:
    from app.seed.loader import upsert_exam_profile

    out = {}
    for p in syl.profiles.profiles:
        out[p.slug] = upsert_exam_profile(db, {"slug": p.slug, "name": p.name, "body": p.body, "domain": p.domain, "pattern": profile_pattern(p)}, stats)
    return out


def load_syllabus(db: Session, syl: Syllabus, stats: Counter) -> Course:
    from app.seed.loader import upsert_course

    spec = syl.course
    profiles = upsert_profiles(db, syl, stats)
    course = upsert_course(
        db,
        spec.model_dump(include={"slug", "title", "description", "domain", "level", "locales", "color", "status", "content_policy"}),
        profiles[spec.exams[0]],
        stats,
    )
    targets = {"requirements": spec.content_requirements.model_dump(exclude_none=True), "mock_targets": dict(spec.mock_targets)}
    if course.content_targets != targets:
        course.content_targets = targets

    # Exam stages of the course.
    links = {link.exam_profile_id: link for link in db.scalars(select(CourseExam).where(CourseExam.course_id == course.id))}
    for pos, slug in enumerate(spec.exams):
        link = links.pop(profiles[slug].id, None)
        if link is None:
            db.add(CourseExam(course_id=course.id, exam_profile_id=profiles[slug].id, position=pos))
        else:
            link.position = pos
    for link in links.values():
        db.delete(link)

    # Concepts: defined here (owned) or reused from another course (looked up).
    slugs = list(syl.concepts)
    by_slug = {c.slug: c for c in db.scalars(select(Concept).where(Concept.slug.in_(slugs)))}
    for slug, content in syl.concepts.items():
        c = content.spec
        concept = by_slug.get(slug)
        if c is None:
            if concept is None:
                raise LookupError(f"syllabus {spec.slug}: concept {slug!r} must be loaded by its own course first")
            continue
        values = {"title": c.title, "summary": c.summary.strip(), "domain": spec.domain, "difficulty_base": DIFFICULTY_B[c.difficulty or "medium"]}
        if concept is None:
            concept = by_slug[slug] = Concept(slug=slug, **values)
            db.add(concept)
            stats["concepts.created"] += 1
        elif _assign(concept, values):
            stats["concepts.updated"] += 1
    db.flush()

    # Tree: nodes by key (parents first, which is the reader's order).
    nodes = {n.key: n for n in db.scalars(select(CourseNode).where(CourseNode.course_id == course.id, CourseNode.key.is_not(None)))}
    keep: dict[str, CourseNode] = {}
    for row in syl.nodes:
        values = {
            "parent_id": keep[row.parent_key].id if row.parent_key else None,
            "node_type": row.node_type,
            "title": row.title,
            "position": row.position,
            "tiers": row.tiers,
        }
        node = nodes.pop(row.key, None)
        if node is None:
            node = CourseNode(course_id=course.id, key=row.key, **values)
            db.add(node)
            db.flush()
            stats["nodes.created"] += 1
        elif _assign(node, values):
            stats["nodes.updated"] += 1
        keep[row.key] = node
    for node in sorted(nodes.values(), key=lambda n: -n.key.count(".")):  # children first
        db.delete(node)
        stats["nodes.deleted"] += 1
    db.flush()

    # Placements of concepts in the tree.
    node_ids = [n.id for n in keep.values()]
    placed = {(p.node_id, p.concept_id): p for p in db.scalars(select(NodeConcept).where(NodeConcept.node_id.in_(node_ids)))} if node_ids else {}
    for p in syl.placements:
        key = (keep[p.node_key].id, by_slug[p.concept].id)
        values = {"weight": p.weight, "position": p.position, "tiers": p.tiers}
        link = placed.pop(key, None)
        if link is None:
            db.add(NodeConcept(node_id=key[0], concept_id=key[1], **values))
            stats["node_concepts.created"] += 1
        elif _assign(link, values):
            stats["node_concepts.updated"] += 1
    for link in placed.values():
        db.delete(link)
        stats["node_concepts.deleted"] += 1

    # Prerequisites of the concepts defined here (edges into them are owned by this syllabus).
    owned_ids = {by_slug[s].id for s in syl.defined}
    edges: dict[tuple, ConceptEdge] = {}
    if owned_ids:
        for e in db.scalars(select(ConceptEdge).where(ConceptEdge.to_concept_id.in_(owned_ids), ConceptEdge.kind == "prerequisite")):
            edges[(e.from_concept_id, e.to_concept_id)] = e
    missing_pre = {pre for c in syl.defined.values() for pre in c.prerequisites} - set(by_slug)
    if missing_pre:
        by_slug.update({c.slug: c for c in db.scalars(select(Concept).where(Concept.slug.in_(missing_pre)))})
    for slug, c in syl.defined.items():
        for pre in c.prerequisites:
            if pre not in by_slug:
                raise LookupError(f"syllabus {spec.slug}: prerequisite {pre!r} of {slug} is not loaded")
            key = (by_slug[pre].id, by_slug[slug].id)
            if edges.pop(key, None) is None:
                db.add(ConceptEdge(from_concept_id=key[0], to_concept_id=key[1], kind="prerequisite"))
                stats["prerequisites.created"] += 1
    for e in edges.values():
        db.delete(e)
        stats["prerequisites.deleted"] += 1
    db.flush()

    _load_concept_content(db, syl, by_slug, stats)
    _load_strategies(db, syl, course, keep, profiles, stats)
    db.flush()
    return course


def _load_concept_content(db: Session, syl: Syllabus, by_slug: dict[str, Concept], stats: Counter) -> None:
    status = syl.course.authored_status
    concept_ids = [by_slug[s].id for s in syl.concepts]
    formulas = {f.key: f for f in db.scalars(select(Formula).where(Formula.concept_id.in_(concept_ids), Formula.source == SOURCE))}
    patterns = {p.key: p for p in db.scalars(select(QuestionPattern).where(QuestionPattern.concept_id.in_(concept_ids), QuestionPattern.source == SOURCE))}
    shortcuts = {s.key: s for s in db.scalars(select(Shortcut).where(Shortcut.concept_id.in_(concept_ids), Shortcut.source == SOURCE))}
    # Keys can also exist under another concept or source (moved concept, hand-made row).
    for model, existing in ((Formula, formulas), (QuestionPattern, patterns), (Shortcut, shortcuts)):
        wanted = {f"{slug}:{item.key}" for slug, c in syl.concepts.items() for item in _items(c, model)}
        missing = wanted - set(existing)
        if missing:
            existing.update({r.key: r for r in db.scalars(select(model).where(model.key.in_(missing)))})

    f_wanted, f_fixed, p_wanted, p_fixed, s_wanted, s_fixed = {}, {}, {}, {}, {}, {}
    for slug, c in syl.concepts.items():
        cid = by_slug[slug].id
        for pos, f in enumerate(c.formulas):
            key = f"{slug}:{f.key}"
            f_wanted[key] = {
                "name": f.name,
                "expression": f.expression,
                "variables": [v.model_dump() for v in f.variables],
                "conditions": f.conditions,
                "example": f.example.model_dump() if f.example else {},
            }
            f_fixed[key] = {"concept_id": cid, "position": pos}
        for pos, (p, tiers) in enumerate(c.patterns):
            key = f"{slug}:{p.key}"
            p_wanted[key] = {
                "title": p.title,
                "description": p.description,
                "example_stem": p.example_stem,
                "frequency": p.frequency,
                "tiers": tiers,
                "difficulty": p.difficulty,
                "target_seconds": p.target_seconds,
            }
            p_fixed[key] = {"concept_id": cid, "position": pos}
        for pos, s in enumerate(c.shortcuts):
            key = f"{slug}:{s.key}"
            s_wanted[key] = {
                "title": s.title,
                "kind": s.kind,
                "rule": s.rule,
                "when_to_use": s.when_to_use,
                "steps": list(s.steps),
                "example": s.example.model_dump(exclude_none=True) if s.example else {},
                "pitfalls": list(s.pitfalls),
            }
            s_fixed[key] = {"concept_id": cid, "position": pos, "_pattern": f"{slug}:{s.pattern}" if s.pattern else None}

    _sync(db, Formula, formulas, f_wanted, f_fixed, status, "formulas", stats)
    pattern_rows = _sync(db, QuestionPattern, patterns, p_wanted, p_fixed, status, "patterns", stats)
    db.flush()
    for fixed in s_fixed.values():
        ref = fixed.pop("_pattern")
        fixed["pattern_id"] = pattern_rows[ref].id if ref else None
    _sync(db, Shortcut, shortcuts, s_wanted, s_fixed, status, "shortcuts", stats)


def _items(content, model) -> list:
    if model is Formula:
        return content.formulas
    if model is Shortcut:
        return content.shortcuts
    return [p for p, _ in content.patterns]


def _sync(db: Session, model, existing: dict, wanted: dict, fixed: dict, status: str, kind: str, stats: Counter) -> dict:
    out = {}
    for key, content in wanted.items():
        row = existing.pop(key, None)
        if row is None:
            row = model(key=key, source=SOURCE, status=status, **content, **fixed[key])
            db.add(row)
            stats[f"{kind}.created"] += 1
        else:
            changed = _assign(row, content)
            if changed or row.source != SOURCE:
                row.source, row.status, row.reviewed_by = SOURCE, status, None
                stats[f"{kind}.updated"] += 1
            elif row.status == "retired" and row.reviewed_by is None:  # retired by an earlier load, back in the files
                row.status = status
                stats[f"{kind}.restored"] += 1
            _assign(row, fixed[key])
        out[key] = row
    for row in existing.values():  # no longer in the files
        if row.source == SOURCE and row.status != "retired":
            row.status = "retired"
            stats[f"{kind}.retired"] += 1
    return out


def _load_strategies(db: Session, syl: Syllabus, course: Course, nodes: dict[str, CourseNode], profiles: dict[str, ExamProfile], stats: Counter) -> None:
    existing = {s.key: s for s in db.scalars(select(ExamStrategy).where(ExamStrategy.course_id == course.id))}
    wanted, fixed = {}, {}
    for row in syl.strategies:
        wanted[row.key] = {"title": row.spec.title, "body": row.spec.body()}
        fixed[row.key] = {
            "course_id": course.id,
            "node_id": nodes[row.node_key].id if row.node_key else None,
            "exam_profile_id": profiles[row.spec.exam].id if row.spec.exam else None,
        }
    _sync(db, ExamStrategy, existing, wanted, fixed, syl.course.authored_status, "strategies", stats)
