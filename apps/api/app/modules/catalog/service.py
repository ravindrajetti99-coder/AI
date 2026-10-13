import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.assessment.models import Question, QuestionConcept
from app.modules.catalog.models import Concept, ConceptEdge, Course, CourseExam, CourseNode, ExamProfile, ExamStrategy, NodeConcept
from app.modules.catalog.schemas import ConceptBrief, NodeOut


def get_course(db: Session, slug_or_id: str) -> Course:
    course = db.scalar(select(Course).where(Course.slug == slug_or_id))
    if not course:
        try:
            course = db.get(Course, uuid.UUID(slug_or_id))
        except ValueError:
            course = None
    if not course:
        raise NotFound("Course not found")
    return course


def course_concepts(db: Session, course_id: uuid.UUID) -> list[tuple[Concept, float, int]]:
    """Concepts of a course in syllabus order, with their exam weight and order index."""
    nodes = db.scalars(select(CourseNode).where(CourseNode.course_id == course_id)).all()
    order = node_order(nodes)
    rows = db.execute(
        select(Concept, NodeConcept.weight, NodeConcept.node_id, NodeConcept.position)
        .join(NodeConcept, NodeConcept.concept_id == Concept.id)
        .where(NodeConcept.node_id.in_([n.id for n in nodes]))
    ).all()
    rows = sorted(rows, key=lambda r: (order.get(r[2], 10**6), r[3]))
    seen: set = set()
    out = []
    for concept, weight, _node, _pos in rows:
        if concept.id in seen:
            continue
        seen.add(concept.id)
        out.append((concept, weight, len(out)))
    return out


def node_order(nodes: list[CourseNode]) -> dict[uuid.UUID, int]:
    children = defaultdict(list)
    for n in nodes:
        children[n.parent_id].append(n)
    order: dict[uuid.UUID, int] = {}

    def walk(parent):
        for n in sorted(children[parent], key=lambda x: (x.position, x.title)):
            order[n.id] = len(order)
            walk(n.id)

    walk(None)
    return order


def build_tree(db: Session, course_id: uuid.UUID) -> list[NodeOut]:
    nodes = db.scalars(select(CourseNode).where(CourseNode.course_id == course_id)).all()
    links = db.execute(
        select(NodeConcept.node_id, NodeConcept.weight, NodeConcept.position, NodeConcept.tiers, Concept)
        .join(Concept, Concept.id == NodeConcept.concept_id)
        .where(NodeConcept.node_id.in_([n.id for n in nodes]))
    ).all()
    concepts_by_node = defaultdict(list)
    for node_id, weight, _pos, tiers, c in sorted(links, key=lambda r: r[2]):
        concepts_by_node[node_id].append(ConceptBrief(id=c.id, slug=c.slug, title=c.title, weight=weight, tiers=tiers or []))
    out = {
        n.id: NodeOut(id=n.id, key=n.key, node_type=n.node_type, title=n.title, position=n.position, tiers=n.tiers or [], concepts=concepts_by_node[n.id])
        for n in nodes
    }
    roots = []
    for n in sorted(nodes, key=lambda x: (x.position, x.title)):
        if n.parent_id and n.parent_id in out:
            out[n.parent_id].children.append(out[n.id])
        else:
            roots.append(out[n.id])
    return roots


def course_counts(db: Session, course_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    if not course_ids:
        return {}
    rows = db.execute(
        select(CourseNode.course_id, NodeConcept.concept_id).join(NodeConcept, NodeConcept.node_id == CourseNode.id).where(CourseNode.course_id.in_(course_ids))
    ).all()
    concepts = defaultdict(set)
    for cid, concept_id in rows:
        concepts[cid].add(concept_id)
    all_concepts = {c for s in concepts.values() for c in s}
    qcount: dict = {}
    if all_concepts:
        for concept_id, n in db.execute(
            select(QuestionConcept.concept_id, func.count(QuestionConcept.question_id))
            .join(Question, Question.id == QuestionConcept.question_id)
            .where(QuestionConcept.concept_id.in_(all_concepts), Question.status == "verified")
            .group_by(QuestionConcept.concept_id)
        ).all():
            qcount[concept_id] = n
    return {cid: (len(concepts[cid]), sum(qcount.get(c, 0) for c in concepts[cid])) for cid in course_ids}


def prerequisites(db: Session, concept_id: uuid.UUID) -> list[Concept]:
    return list(
        db.scalars(
            select(Concept)
            .join(ConceptEdge, ConceptEdge.from_concept_id == Concept.id)
            .where(ConceptEdge.to_concept_id == concept_id, ConceptEdge.kind == "prerequisite")
        ).all()
    )


def unlocks(db: Session, concept_id: uuid.UUID) -> list[Concept]:
    return list(
        db.scalars(
            select(Concept)
            .join(ConceptEdge, ConceptEdge.to_concept_id == Concept.id)
            .where(ConceptEdge.from_concept_id == concept_id, ConceptEdge.kind == "prerequisite")
        ).all()
    )


def get_concept(db: Session, concept_id_or_slug: str) -> Concept:
    concept = db.scalar(select(Concept).where(Concept.slug == concept_id_or_slug))
    if not concept:
        try:
            concept = db.get(Concept, uuid.UUID(concept_id_or_slug))
        except ValueError:
            concept = None
    if not concept:
        raise NotFound("Concept not found")
    return concept


def visible(course: Course, staff: bool) -> bool:
    """Draft courses (content still being prepared) are visible to staff only."""
    return course.status == "published" or staff


def course_exams(db: Session, course: Course) -> list[ExamProfile]:
    """The exam stages a course prepares for, main one first (falls back to its single profile)."""
    rows = list(
        db.scalars(
            select(ExamProfile)
            .join(CourseExam, CourseExam.exam_profile_id == ExamProfile.id)
            .where(CourseExam.course_id == course.id)
            .order_by(CourseExam.position)
        )
    )
    if not rows and course.exam_profile_id:
        rows = [db.get(ExamProfile, course.exam_profile_id)]
    return rows


def strategy_out(s: ExamStrategy, node: CourseNode | None = None, exam: ExamProfile | None = None) -> dict:
    return {
        "id": str(s.id),
        "key": s.key,
        "title": s.title,
        "scope": node.node_type if node else "course",
        "scope_title": node.title if node else "",
        "exam": exam.slug if exam else None,
        "status": s.status,
        **s.body,
    }


def course_strategies(db: Session, course: Course, statuses=("verified",), depth: int = 0) -> list[dict]:
    """Course-wide strategies plus those of the top `depth` levels of the tree (0 = course only)."""
    nodes = {n.id: n for n in db.scalars(select(CourseNode).where(CourseNode.course_id == course.id))}
    exams = {e.id: e for e in course_exams(db, course)}
    rows = db.scalars(select(ExamStrategy).where(ExamStrategy.course_id == course.id, ExamStrategy.status.in_(statuses)).order_by(ExamStrategy.key)).all()
    out = []
    for s in rows:
        node = nodes.get(s.node_id) if s.node_id else None
        if node is not None and _depth(node, nodes) >= depth:
            continue
        out.append(strategy_out(s, node, exams.get(s.exam_profile_id)))
    return out


def _depth(node: CourseNode, nodes: dict) -> int:
    d = 0
    while node.parent_id and node.parent_id in nodes:
        node, d = nodes[node.parent_id], d + 1
    return d


def strategies_for_concept(db: Session, concept_id: uuid.UUID, statuses=("verified",)) -> list[dict]:
    """Strategies of every node above the concept (its chapter, its subject), nearest first."""
    placed = db.scalars(select(CourseNode).join(NodeConcept, NodeConcept.node_id == CourseNode.id).where(NodeConcept.concept_id == concept_id)).all()
    chain: list[CourseNode] = []
    seen: set = set()
    for node in placed:
        current: CourseNode | None = node
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current)
            current = db.get(CourseNode, current.parent_id) if current.parent_id else None
    if not chain:
        return []
    by_node = {n.id: n for n in chain}
    exams = {e.id: e for e in db.scalars(select(ExamProfile))}
    rows = db.scalars(select(ExamStrategy).where(ExamStrategy.node_id.in_(list(by_node)), ExamStrategy.status.in_(statuses))).all()
    order = {n.id: i for i, n in enumerate(chain)}
    rows = sorted(rows, key=lambda s: (order[s.node_id], s.key))
    return [strategy_out(s, by_node[s.node_id], exams.get(s.exam_profile_id)) for s in rows]


def courses_of_concept(db: Session, concept_id: uuid.UUID) -> list[Course]:
    return list(
        db.scalars(
            select(Course)
            .join(CourseNode, CourseNode.course_id == Course.id)
            .join(NodeConcept, NodeConcept.node_id == CourseNode.id)
            .where(NodeConcept.concept_id == concept_id)
            .distinct()
        )
    )


def reviewed_only(db: Session, concept_id: uuid.UUID) -> bool:
    """True when any course using the concept serves verified content only (the stricter policy wins)."""
    return bool(
        db.scalar(
            select(func.count())
            .select_from(Course)
            .join(CourseNode, CourseNode.course_id == Course.id)
            .join(NodeConcept, NodeConcept.node_id == CourseNode.id)
            .where(NodeConcept.concept_id == concept_id, Course.content_policy == "reviewed_only")
        )
    )
