import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.assessment.models import Question, QuestionConcept
from app.modules.catalog.models import Concept, ConceptEdge, Course, CourseNode, NodeConcept
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
    order = _node_order(nodes)
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


def _node_order(nodes: list[CourseNode]) -> dict[uuid.UUID, int]:
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
        select(NodeConcept.node_id, NodeConcept.weight, NodeConcept.position, Concept)
        .join(Concept, Concept.id == NodeConcept.concept_id)
        .where(NodeConcept.node_id.in_([n.id for n in nodes]))
    ).all()
    concepts_by_node = defaultdict(list)
    for node_id, weight, _pos, c in sorted(links, key=lambda r: r[2]):
        concepts_by_node[node_id].append(ConceptBrief(id=c.id, slug=c.slug, title=c.title, weight=weight))
    out = {n.id: NodeOut(id=n.id, node_type=n.node_type, title=n.title, position=n.position, concepts=concepts_by_node[n.id]) for n in nodes}
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
