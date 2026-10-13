"""The SSC CGL content engine foundation: the loaded syllabus, the reviewed-only policy, study
packs, coverage, review of formulas/shortcuts/patterns/strategies and the mock pool."""

from collections import Counter

import pytest
from conftest import API, concept_id
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.assessment import service as qservice
from app.modules.assessment.models import Question, QuestionPattern
from app.modules.catalog.models import Concept, Course, CourseExam, CourseNode, ExamStrategy, NodeConcept
from app.modules.content.models import Formula, Lesson, Shortcut
from app.modules.identity import service as identity
from app.modules.learning import service as learning
from app.seed.syllabus import load_syllabus_file
from app.seed.syllabus.loader import load_syllabus

SLUG = "ssc-cgl"


def _course(db) -> Course:
    return db.scalar(select(Course).where(Course.slug == SLUG))


def _approve_all(admin, asset_type: str, prefix: str = "") -> int:
    n = 0
    for item in admin.get(f"{API}/admin/review-queue?asset_type={asset_type}&limit=500").json():
        if item["key"].startswith(prefix):
            assert admin.post(f"{API}/admin/assets/{asset_type}/{item['id']}/decision", json={"decision": "approve"}).status_code == 200
            n += 1
    return n


# --------------------------------------------------------------------------- loading


def test_the_syllabus_is_loaded_as_a_draft_exam_course(sdb):
    syl = load_syllabus_file(SLUG)
    course = _course(sdb)
    assert (course.status, course.content_policy) == ("draft", "reviewed_only")
    assert course.content_targets["mock_targets"] == {"ssc-cgl-tier1": 20, "ssc-cgl-tier2": 10}
    exams = sdb.scalars(select(CourseExam).where(CourseExam.course_id == course.id).order_by(CourseExam.position)).all()
    assert len(exams) == 2 and course.exam_profile_id == exams[0].exam_profile_id
    nodes = sdb.scalars(select(CourseNode).where(CourseNode.course_id == course.id)).all()
    assert len(nodes) == len(syl.nodes) and all(n.key for n in nodes)
    assert {n.node_type for n in nodes} == {"subject", "chapter", "topic", "subtopic"}
    placed = sdb.scalar(
        select(func.count()).select_from(NodeConcept).join(CourseNode, CourseNode.id == NodeConcept.node_id).where(CourseNode.course_id == course.id)
    )
    assert placed == len(syl.placements)
    # Authored content waits for review.
    for model in (Formula, Shortcut, QuestionPattern):
        statuses = set(sdb.scalars(select(model.status).where(model.source == "syllabus")))
        assert statuses == {"in_review"}, model


def test_reused_concepts_are_shared_with_the_arithmetic_course(sdb):
    cid = concept_id("percentage-basics")
    courses = {c.slug for c in sdb.scalars(select(Course).join(CourseNode).join(NodeConcept).where(NodeConcept.concept_id == cid))}
    assert courses == {"ssc-cgl", "ssc-cgl-quant-arithmetic"}
    assert sdb.scalar(select(func.count()).select_from(Concept).where(Concept.slug == "percentage-basics")) == 1


def test_reloading_the_syllabus_changes_nothing(sdb):
    stats = Counter()
    load_syllabus(sdb, load_syllabus_file(SLUG), stats)
    sdb.commit()
    assert dict(stats) == {}


def _edit_formula(syl, key: str, changes: dict | None):
    """A copy of the syllabus with one formula changed (or removed when changes is None)."""
    slug, fkey = key.split(":")
    c = syl.concepts[slug]
    if changes is None:
        formulas = [f for f in c.formulas if f.key != fkey]
    else:
        formulas = [f.model_copy(update=changes) if f.key == fkey else f for f in c.formulas]
    concepts = {**syl.concepts, slug: type(c)(**{**c.__dict__, "formulas": formulas})}
    return type(syl)(**{**syl.__dict__, "concepts": concepts})


def test_review_survives_reloads_and_edits_go_back_to_review(sdb, admin):
    key = "percentage-marks:pass-marks"
    _approve_all(admin, "formula", "percentage-marks:")
    syl = load_syllabus_file(SLUG)

    def status():
        sdb.expire_all()
        return sdb.scalar(select(Formula.status).where(Formula.key == key))

    load_syllabus(sdb, syl, Counter())
    sdb.commit()
    assert status() == "verified"  # unchanged text keeps its review
    load_syllabus(sdb, _edit_formula(syl, key, {"expression": "pass marks = pass% × maximum / 100"}), stats := Counter())
    sdb.commit()
    assert status() == "in_review" and stats["formulas.updated"] == 1
    load_syllabus(sdb, _edit_formula(syl, key, None), stats := Counter())
    sdb.commit()
    assert status() == "retired" and stats["formulas.retired"] == 1
    load_syllabus(sdb, syl, stats := Counter())
    sdb.commit()
    assert status() == "in_review" and stats["formulas.updated"] == 1  # back in the files, with the original text


def test_a_rejected_item_stays_rejected(sdb, admin):
    item = next(i for i in admin.get(f"{API}/admin/review-queue?asset_type=shortcut&limit=500").json() if i["key"].startswith("percentage-comparison:"))
    assert admin.post(f"{API}/admin/assets/shortcut/{item['id']}/decision", json={"decision": "reject"}).json()["status"] == "retired"
    load_syllabus(sdb, load_syllabus_file(SLUG), Counter())
    sdb.commit()
    assert sdb.scalar(select(Shortcut.status).where(Shortcut.key == item["key"])) == "retired"


# --------------------------------------------------------------------------- visibility and policy


def test_draft_courses_are_hidden_from_learners(sclient, learner, admin):
    assert SLUG not in {c["slug"] for c in sclient.get(f"{API}/courses").json()}
    assert sclient.get(f"{API}/courses/{SLUG}").status_code == 404
    assert learner.get(f"{API}/courses/{SLUG}").status_code == 404
    assert learner.post(f"{API}/courses/{SLUG}/enroll").status_code == 404
    detail = admin.get(f"{API}/courses/{SLUG}").json()
    assert [e["slug"] for e in detail["exams"]] == ["ssc-cgl-tier1", "ssc-cgl-tier2"]
    assert detail["content_policy"] == "reviewed_only"
    computer = next(n for n in detail["tree"] if n["key"] == "computer")
    assert computer["node_type"] == "subject" and computer["tiers"] == ["tier2"]
    assert {c["slug"] for c in admin.get(f"{API}/admin/courses").json()} >= {SLUG, "ssc-cgl-quant-arithmetic"}


def test_course_detail_lists_verified_strategies(sclient, admin):
    assert admin.get(f"{API}/courses/{SLUG}").json()["strategies"] == []
    _approve_all(admin, "strategy")
    strategies = admin.get(f"{API}/courses/{SLUG}").json()["strategies"]
    keys = {s["key"] for s in strategies}
    assert {"tier1-overall", "tier2-overall", "quant:approach"} <= keys  # course and subject level, not chapters
    assert not any(s["scope"] == "chapter" for s in strategies)
    tier1 = next(s for s in strategies if s["key"] == "tier1-overall")
    assert tier1["exam"] == "ssc-cgl-tier1" and tier1["tactics"]


def test_learners_get_only_reviewed_lessons_in_exam_courses(sclient, learner, admin):
    cid = str(concept_id("percentage-marks"))
    # A staff member generates a draft; learners do not see it and cannot generate one.
    staff = admin.get(f"{API}/concepts/{cid}/lesson?level=1&generate=true").json()
    assert staff["status"] == "in_review"
    seen = learner.get(f"{API}/concepts/{cid}/lesson?level=1&generate=true").json()
    assert seen["status"] == "missing" and seen["can_generate"] is False and "being prepared" in seen["note"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Lesson).where(Lesson.concept_id == concept_id("percentage-marks"))) == 1
    assert admin.post(f"{API}/admin/assets/lesson/{staff['id']}/decision", json={"decision": "approve"}).status_code == 200
    assert learner.get(f"{API}/concepts/{cid}/lesson?level=1").json()["status"] == "verified"


def test_open_courses_keep_learner_generation(sclient, learner):
    cid = str(concept_id("python-loops"))
    body = learner.get(f"{API}/concepts/{cid}/lesson?level=4").json()
    assert body["status"] == "missing" and body["can_generate"] is True


# --------------------------------------------------------------------------- study pack


def test_study_pack_serves_verified_content_with_an_etag(sclient, learner, admin):
    cid = str(concept_id("percentage-marks"))
    empty = learner.get(f"{API}/concepts/{cid}/study-pack")
    assert empty.status_code == 200 and empty.json()["formulas"] == [] and empty.json()["reviewed_only"] is True
    assert empty.headers["cache-control"] == "private, max-age=300"
    assert learner.get(f"{API}/concepts/{cid}/study-pack?preview=true").status_code == 403
    preview = admin.get(f"{API}/concepts/{cid}/study-pack?preview=true").json()
    assert preview["formulas"] and preview["patterns"] and preview["shortcuts"]
    for kind in ("formula", "shortcut", "pattern"):
        _approve_all(admin, kind, "percentage-marks:")
    _approve_all(admin, "strategy")
    pack = learner.get(f"{API}/concepts/{cid}/study-pack")
    data = pack.json()
    assert len(data["formulas"]) == len(preview["formulas"]) and data["patterns"][0]["pyq_count"] == 0
    shortcut = next(s for s in data["shortcuts"] if s["key"] == "percentage-marks:difference-method")
    assert shortcut["pattern"] == "percentage-marks:two-students" and shortcut["example"]["seconds_saved"] == 30
    assert [s["scope"] for s in data["strategies"]] == ["chapter", "subject"]  # nearest first
    assert data["strategies"][0]["key"] == "quant.percentage:approach"
    again = learner.get(f"{API}/concepts/{cid}/study-pack", headers={**learner.headers, "If-None-Match": pack.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    changed = learner.get(f"{API}/concepts/{cid}/study-pack", headers={**learner.headers, "If-None-Match": empty.headers["etag"]})
    assert changed.status_code == 200


# --------------------------------------------------------------------------- coverage


def test_coverage_reports_gaps_and_mock_readiness(sclient, admin, learner):
    assert learner.get(f"{API}/admin/courses/{SLUG}/coverage").status_code == 403
    report = admin.get(f"{API}/admin/courses/{SLUG}/coverage").json()
    syl = load_syllabus_file(SLUG)
    assert report["totals"]["concepts"] == len(syl.concepts)
    assert report["ready"] is False and report["totals"]["complete"] == 0
    assert [s["key"] for s in report["subjects"]] == syl.course.subjects
    tier1 = next(m for m in report["mocks"] if m["exam"] == "ssc-cgl-tier1")
    assert tier1["mocks_planned"] == 20 and {s["needed"] for s in tier1["sections"]} == {500}
    tier2 = next(m for m in report["mocks"] if m["exam"] == "ssc-cgl-tier2")
    assert {s["subject"]: s["needed"] for s in tier2["sections"]}["english"] == 450
    scoped = admin.get(f"{API}/admin/courses/{SLUG}/coverage?scope=quant.percentage").json()["concepts"]
    basics = next(c for c in scoped if c["slug"] == "percentage-basics")
    assert basics["have"]["practice_questions"] > 0  # the arithmetic course's questions count here too
    assert basics["missing"]["formulas"] == 1 and "1/en" not in basics["missing"].get("lessons", [])
    # Approving the formulas closes that gap.
    _approve_all(admin, "formula", "percentage-basics:")
    scoped = admin.get(f"{API}/admin/courses/{SLUG}/coverage?scope=quant.percentage").json()["concepts"]
    assert "formulas" not in next(c for c in scoped if c["slug"] == "percentage-basics")["missing"]


def test_coverage_of_a_course_without_targets_uses_the_default(sclient, admin):
    report = admin.get(f"{API}/admin/courses/python-fundamentals/coverage").json()
    assert report["totals"]["concepts"] > 0 and report["mocks"] == []


# --------------------------------------------------------------------------- review


def test_review_queue_lists_and_decides_the_new_types(sclient, admin):
    for kind in ("formula", "shortcut", "pattern", "strategy"):
        items = admin.get(f"{API}/admin/review-queue?asset_type={kind}&limit=3").json()
        assert len(items) == 3 and all(i["asset_type"] == kind and i["source"] == "syllabus" for i in items)
    formula = admin.get(f"{API}/admin/review-queue?asset_type=formula&limit=1").json()[0]
    refused = admin.post(f"{API}/admin/assets/formula/{formula['id']}/decision", json={"decision": "approve", "edits": {"name": "x"}})
    assert refused.status_code == 422 and "syllabus" in refused.json()["detail"]
    with SessionLocal() as db:  # content from other sources (generated, PR 6) can be edited in review
        f = db.scalar(select(Formula).where(Formula.key == formula["key"]))
        f.source = "ai"
        db.commit()
    ok = admin.post(f"{API}/admin/assets/formula/{formula['id']}/decision", json={"decision": "approve", "edits": {"name": "Renamed"}})
    assert ok.json()["status"] == "verified"
    bad = admin.get(f"{API}/admin/review-queue?asset_type=pattern&limit=1").json()[0]
    with SessionLocal() as db:
        db.scalar(select(QuestionPattern).where(QuestionPattern.key == bad["key"])).source = "ai"
        db.commit()
    assert admin.post(f"{API}/admin/assets/pattern/{bad['id']}/decision", json={"decision": "approve", "edits": {"frequency": "often"}}).status_code == 422
    with SessionLocal() as db:
        f = db.scalar(select(Formula).where(Formula.key == formula["key"]))
        assert (f.name, f.reviewed_by is not None) == ("Renamed", True)
    stats = admin.get(f"{API}/admin/stats").json()
    assert stats["in_review"] > 1000


# --------------------------------------------------------------------------- mock pool


def test_mock_pool_questions_are_kept_out_of_practice(sdb):
    cid = concept_id("percentage-basics")
    user = identity.create_user(sdb, "pool@example.com", "password-123", "Pool")
    held = qservice.add_question(
        sdb,
        qtype="numerical",
        stem="Held back for mocks: what is 10% of 70?",
        payload={"answer": 7, "tolerance": 0},
        concept_ids=[cid],
        pool="mock",
    )
    sdb.commit()
    seen = set()
    for _ in range(40):
        q = learning.choose_question(sdb, user.id, cid, exclude=seen)
        if q is None:
            break
        seen.add(q.id)
    assert seen and held.id not in seen
    assert held.stem_hash == qservice.stem_hash("held back for mocks what is 10 of 70")


@pytest.mark.parametrize("stem", ["Population is 1,00,000.", "population is 100000"])
def test_stem_hash_ignores_case_spacing_and_digit_grouping(stem):
    assert qservice.stem_hash(stem) == qservice.stem_hash("POPULATION   is 100000")


def test_seeded_questions_carry_a_stem_hash(sdb):
    assert sdb.scalar(select(func.count()).select_from(Question).where(Question.stem_hash.is_(None))) == 0
    assert sdb.scalar(select(func.count()).select_from(ExamStrategy)) == len(load_syllabus_file(SLUG).strategies)


def test_loading_only_the_syllabus_brings_the_courses_it_reuses(sdb):
    from app.seed.courses import ALL_COURSES
    from app.seed.loader import load

    refs = load_syllabus_file(SLUG).refs
    owners = {m.COURSE["slug"] for m in ALL_COURSES if set(m.CONCEPTS) & refs}
    assert "ssc-cgl-quant-arithmetic" in owners
    stats = load(sdb, only=["ssc-cgl"], build_tests=False)
    assert stats["courses.loaded"] == 1 + len(owners)
