"""Seed loader behaviour and the integrity of the seeded content itself."""

import copy
import types
from collections import defaultdict

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.modules.assessment.models import Question, QuestionConcept, SolutionStep
from app.modules.assessment.models import Test as MockTest
from app.modules.assessment.models import TestItem as MockItem
from app.modules.catalog import service as catalog
from app.modules.catalog.models import ConceptEdge, Course
from app.modules.content.models import Flashcard, Lesson
from app.modules.identity.models import User
from app.modules.labs.runner import run_python
from app.seed.courses import ALL_COURSES, ssc_quant
from app.seed.loader import SeedError, load


def test_reload_is_a_no_op(sdb):
    stats = load(sdb)
    assert dict(stats) == {"courses.loaded": 6}


def test_only_filters_and_rejects_unknown_slugs(sdb):
    assert load(sdb, only=["python-fundamentals"], build_tests=False)["courses.loaded"] == 1
    with pytest.raises(SeedError, match="unknown course slug"):
        load(sdb, only=["nope"])


def _variant(module, mutate):
    """A copy of a seed course module with `mutate` applied to its CONCEPTS."""
    m = types.SimpleNamespace(COURSE=module.COURSE, CONCEPTS=copy.deepcopy(module.CONCEPTS))
    mutate(m.CONCEPTS)
    return m


def test_edits_update_in_place_and_removed_questions_retire(sdb):
    def edit(concepts):
        concepts["profit-loss"]["extra"][0]["explanation"] = "Edited explanation."
        concepts["compound-interest"]["extra"] = []

    others = [m for m in ALL_COURSES if m is not ssc_quant]
    stats = load(sdb, courses=[_variant(ssc_quant, edit), *others], build_tests=False)
    assert stats["questions.updated"] == 1 and stats["questions.retired"] == 1
    edited = sdb.scalar(select(Question).where(Question.external_key == "profit-loss:extra:0"))
    assert edited.explanation == "Edited explanation."
    retired = sdb.scalar(select(Question).where(Question.external_key == "compound-interest:extra:0"))
    assert retired.status == "retired"
    # Putting it back revives the same row instead of creating a duplicate.
    stats = load(sdb, build_tests=False)
    assert stats["questions.created"] == 0
    sdb.refresh(retired)
    assert retired.status == "verified"


def test_bad_answer_keys_fail_loudly(sdb):
    def break_key(concepts):
        concepts["profit-loss"]["extra"][0]["payload"]["answer"] = "z"

    with pytest.raises(SeedError, match="profit-loss:extra:0"):
        load(sdb, courses=[_variant(ssc_quant, break_key)])
    sdb.rollback()
    assert sdb.scalar(select(Question).where(Question.external_key == "profit-loss:extra:0")).payload["answer"] == "c"


def test_admin_bootstrap(sdb, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "admin_email", "Owner@EduVerse.org")
    monkeypatch.setattr(s, "admin_password", "short")
    with pytest.raises(SeedError, match="at least 12"):
        load(sdb, build_tests=False)
    monkeypatch.setattr(s, "admin_password", "a-long-admin-password")
    monkeypatch.setattr(s, "admin_email", "admin@eduverse.local")  # reserved domain: login would reject it
    with pytest.raises(SeedError, match="not a usable email"):
        load(sdb, build_tests=False)
    monkeypatch.setattr(s, "admin_email", "Owner@EduVerse.org")
    assert load(sdb, build_tests=False)["admin.created"] == 1
    user = sdb.scalar(select(User).where(User.email == "owner@eduverse.org"))
    assert user.role == "admin"
    user.role = "learner"
    sdb.commit()
    assert load(sdb, build_tests=False)["admin.promoted"] == 1


def test_mock_tests_follow_the_exam_pattern(sdb):
    test = sdb.scalar(select(MockTest).where(MockTest.slug == "ssc-cgl-quant-arithmetic-mock-1"))
    items = sdb.scalars(select(MockItem).where(MockItem.test_id == test.id)).all()
    assert len(items) == 20 and {(i.marks, i.negative_marks) for i in items} == {(2.0, 0.5)}
    assert test.duration_minutes == 12  # 0.6 minutes per question
    qtypes = set(sdb.scalars(select(Question.qtype).where(Question.id.in_([i.question_id for i in items]))).all())
    assert qtypes <= {"mcq", "multi", "assertion_reason", "case_study", "numerical"}
    assert sdb.scalar(select(func.count()).select_from(MockTest)) == 6


# --------------------------------------------------------------------------- content integrity


def test_every_concept_has_a_lesson_flashcards_and_questions(sdb):
    for course in sdb.scalars(select(Course)).all():
        for concept, _, _ in catalog.course_concepts(sdb, course.id):
            levels = set(sdb.scalars(select(Lesson.level).where(Lesson.concept_id == concept.id, Lesson.locale == "en")).all())
            assert 1 in levels, f"{concept.slug} has no level-1 English lesson"
            assert sdb.scalar(select(func.count()).select_from(Flashcard).where(Flashcard.concept_id == concept.id)), f"{concept.slug} has no flashcards"
            n = sdb.scalar(
                select(func.count())
                .select_from(QuestionConcept)
                .join(Question, Question.id == QuestionConcept.question_id)
                .where(QuestionConcept.concept_id == concept.id, Question.status == "verified")
            )
            assert n >= 2, f"{concept.slug} has only {n} questions"


def test_prerequisite_graph_is_acyclic(sdb):
    graph = defaultdict(set)
    for edge in sdb.scalars(select(ConceptEdge)).all():
        graph[edge.from_concept_id].add(edge.to_concept_id)
    state: dict = {}

    def visit(node):
        if state.get(node) == "active":
            raise AssertionError("prerequisite cycle")
        if state.get(node) == "done":
            return
        state[node] = "active"
        for nxt in graph[node]:
            visit(nxt)
        state[node] = "done"

    for node in list(graph):
        visit(node)


def test_reference_solutions_pass_their_own_tests(sdb):
    """Coding questions carry their reference solution in the 'solution' step; run it."""
    for q in sdb.scalars(select(Question).where(Question.qtype == "coding")).all():
        solution = sdb.scalar(select(SolutionStep.body).where(SolutionStep.question_id == q.id, SolutionStep.kind == "solution"))
        result = run_python(solution, q.payload["function_name"], q.payload["tests"])
        assert result.ok and result.passed == result.total, f"{q.external_key}: {result.summary()} {result.results}"


def test_starter_code_does_not_already_pass(sdb):
    for q in sdb.scalars(select(Question).where(Question.qtype == "coding")).all():
        result = run_python(q.payload["starter_code"], q.payload["function_name"], q.payload["tests"])
        assert result.passed < result.total, q.external_key


def test_objective_questions_have_full_solution_steps(sdb):
    for q in sdb.scalars(select(Question).where(Question.qtype.in_(["mcq", "numerical", "assertion_reason", "case_study", "multi"]))).all():
        kinds = set(sdb.scalars(select(SolutionStep.kind).where(SolutionStep.question_id == q.id)).all())
        assert {"hint", "concept", "approach", "solution"} <= kinds, q.external_key
