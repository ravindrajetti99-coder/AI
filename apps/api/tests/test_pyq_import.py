"""Previous-year question imports: JSON and CSV papers, validation, dedupe, re-imports, dry runs,
mapping and the PYQ analysis in study packs."""

import json

import pytest
from conftest import API, concept_id
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.assessment.models import PyqSource, Question, QuestionConcept

PAPER = {
    "key": "ssc-cgl:tier1:2024-09-09:s1",
    "exam": "ssc-cgl",
    "tier": "tier1",
    "year": 2024,
    "exam_date": "2024-09-09",
    "shift": "1",
    "title": "SSC CGL Tier 1, 9 September 2024, shift 1",
    "source": "SSC answer key and question paper",
    "licence": "public-government-document",
}


def mcq(number: int, stem: str, answer: str = "b", **extra) -> dict:
    options = [{"id": i, "text": t} for i, t in zip("abcd", ("400", "500", "600", "450"), strict=True)]
    return {"number": number, "stem": stem, "options": options, "answer": answer, **extra}


ROWS = [
    mcq(
        1,
        "A candidate scoring 30% fails by 15 marks and another scoring 40% passes by 35 marks. Find the maximum marks.",
        concepts=["percentage-marks"],
        pattern="percentage-marks:two-students",
        steps={"hint": "Difference of percentages = difference of marks.", "solution": "10% = 50, so 500."},
    ),
    mcq(2, "Find 23% of 2,700.", answer="b", concepts=["percentage-basics"], pool="mock"),
    mcq(3, "In an election between two candidates the winner got 60% of 2,500 valid votes. By how many votes did he win?", answer="b"),
    mcq(4, "Broken row", answer="z", concepts=["percentage-basics"]),
]


def submit(actor, rows=None, paper=PAPER, fmt="json", dry_run=False, content=None):
    if content is None:
        content = json.dumps({"paper": paper, "questions": rows if rows is not None else ROWS})
    body = {"filename": f"paper.{fmt}", "format": fmt, "content": content, "dry_run": dry_run}
    if fmt == "csv":
        body["paper"] = paper
    return actor.post(f"{API}/admin/pyq/imports", json=body)


def run(actor, worker, **kw) -> dict:
    r = submit(actor, **kw)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued" and r.json()["job_id"]
    worker.drain()
    return actor.get(f"{API}/admin/pyq/imports/{r.json()['id']}").json()


def pyqs(db) -> list[Question]:
    return list(db.scalars(select(Question).where(Question.source == "pyq").order_by(Question.external_key)))


def test_json_import_creates_questions_for_review(sclient, admin, worker):
    result = run(admin, worker)
    assert result["status"] == "done" and result["job_status"] == "done"
    s = result["summary"]
    assert (s["rows"], s["created"], s["invalid"], s["unmapped"], s["duplicate"]) == (4, 3, 1, 1, 0)
    assert result["errors"] == [{"row": 4, "number": 4, "outcome": "invalid", "error": "question 4: answer 'z' is not one of the options ['a', 'b', 'c', 'd']"}]
    with SessionLocal() as db:
        qs = pyqs(db)
        assert [q.external_key for q in qs] == [f"pyq:{PAPER['key']}:{n}" for n in (1, 2, 3)]
        assert {q.status for q in qs} == {"in_review"} and {q.pyq_year for q in qs} == {2024}
        source = db.scalar(select(PyqSource).where(PyqSource.key == PAPER["key"]))
        assert source.licence == "public-government-document" and all(q.pyq_source_id == source.id for q in qs)
        first = qs[0]
        assert first.pattern_id is not None and first.stem_hash
        assert db.scalar(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == first.id)) == concept_id("percentage-marks")
        assert [q.pool for q in qs] == ["practice", "mock", "practice"]
    sources = admin.get(f"{API}/admin/pyq/sources").json()
    assert sources[0]["key"] == PAPER["key"] and sources[0]["questions"] == 3
    listed = admin.get(f"{API}/admin/pyq/imports").json()
    assert listed[0]["error_count"] == 1 and "errors" not in listed[0]


def test_a_pattern_implies_its_concept(sclient, admin, worker):
    run(
        admin,
        worker,
        rows=[mcq(1, "Two candidates scoring 25% and 50% miss and pass by 30 and 20 marks. Find the pass mark.", pattern="percentage-marks:two-students")],
    )
    with SessionLocal() as db:
        q = pyqs(db)[0]
        assert db.scalar(select(QuestionConcept.concept_id).where(QuestionConcept.question_id == q.id)) == concept_id("percentage-marks")


def test_reimport_updates_in_place_and_reports_unchanged(sclient, admin, worker):
    run(admin, worker)
    with SessionLocal() as db:
        for q in pyqs(db):
            q.status = "verified"
        db.commit()
    rows = [dict(r) for r in ROWS]
    rows[1] = {**rows[1], "explanation": "23/100 × 2700 = 621"}
    s = run(admin, worker, rows=rows)["summary"]
    assert (s["created"], s["updated"], s["unchanged"], s["invalid"]) == (0, 1, 2, 1)
    with SessionLocal() as db:
        statuses = {q.external_key.rsplit(":", 1)[1]: q.status for q in pyqs(db)}
        assert statuses == {"1": "verified", "2": "in_review", "3": "verified"}  # a corrected question is reviewed again
        assert db.scalar(select(func.count()).select_from(Question).where(Question.source == "pyq")) == 3


def test_duplicates_are_reported_not_stored_twice(sclient, admin, worker):
    run(admin, worker)
    other_paper = {**PAPER, "key": "ssc-cgl:tier1:2024-09-10:s2", "exam_date": "2024-09-10", "shift": "2"}
    rows = [
        mcq(7, "find 23 % of 2700 ?", answer="b"),  # same question as row 2 of the first paper
        mcq(8, "Find 12.5% of 64.", answer="a"),
        mcq(9, "Find 12.5%  of 64", answer="a"),  # repeats row 8 of this file
    ]
    result = run(admin, worker, rows=rows, paper=other_paper)
    s = result["summary"]
    assert (s["created"], s["duplicate"]) == (1, 2)
    assert "already in the bank" in result["errors"][0]["error"] and "earlier question of this file" in result["errors"][1]["error"]


def test_dry_run_writes_nothing(sclient, admin, worker):
    result = run(admin, worker, dry_run=True)
    assert result["summary"]["created"] == 3 and result["summary"]["dry_run"] is True
    with SessionLocal() as db:
        assert pyqs(db) == [] and db.scalar(select(func.count()).select_from(PyqSource)) == 0


def test_csv_import(sclient, admin, worker):
    csv_text = (
        "number,section,stem,option_a,option_b,option_c,option_d,answer,concepts,pattern,difficulty,hint,solution\n"
        '5,Quantitative Aptitude,"If 35% of a number is 84, find the number.",220,240,250,260,b,percentage-basics,percentage-basics:find-whole,easy,'
        '"Divide by 35%","84 × 100 / 35 = 240"\n'
        '6,Quantitative Aptitude,"A is 25% more than B. By what percent is B less than A?",20%,25%,15%,30%,a,percentage-comparison;percentage-change,,medium,,\n'
    )
    result = run(admin, worker, fmt="csv", content=csv_text)
    assert result["summary"]["created"] == 2 and result["summary"]["invalid"] == 0
    with SessionLocal() as db:
        q5 = db.scalar(select(Question).where(Question.external_key == f"pyq:{PAPER['key']}:5"))
        assert q5.payload["answer"] == "b" and [o["text"] for o in q5.payload["options"]] == ["220", "240", "250", "260"]
        assert q5.difficulty == "easy" and q5.pattern_id is not None
        q6 = db.scalar(select(Question).where(Question.external_key == f"pyq:{PAPER['key']}:6"))
        assert len(db.scalars(select(QuestionConcept).where(QuestionConcept.question_id == q6.id)).all()) == 2


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        ({"fmt": "json", "content": "{not json"}, 422, "Not valid JSON"),
        ({"fmt": "json", "content": json.dumps({"questions": []})}, 422, "Paper details"),
        ({"fmt": "json", "content": json.dumps({"paper": PAPER, "questions": []})}, 422, "no questions"),
        ({"fmt": "csv", "content": "number,stem,colour\n1,x,red\n"}, 422, "Unknown CSV columns"),
        ({"fmt": "json", "content": json.dumps({"paper": {**PAPER, "source": ""}, "questions": ROWS})}, 422, "Paper details"),
    ],
)
def test_unusable_files_are_refused_at_once(sclient, admin, body, status, message):
    r = submit(admin, **body)
    assert r.status_code == status and message in json.dumps(r.json())


def test_a_licence_is_required(sclient, admin):
    r = submit(admin, fmt="csv", content="number,stem\n1,What is 2 + 2?\n", paper={**PAPER, "licence": "found-online"})
    assert r.status_code == 422 and "licence" in json.dumps(r.json())


def test_unmapped_questions_can_be_mapped(sclient, admin, worker, learner):
    run(admin, worker)
    unmapped = admin.get(f"{API}/admin/pyq/unmapped").json()
    assert len(unmapped) == 1 and unmapped[0]["external_key"].endswith(":3")
    qid = unmapped[0]["id"]
    assert admin.post(f"{API}/admin/questions/{qid}/mapping", json={"concepts": ["nope"]}).status_code == 404
    wrong = admin.post(f"{API}/admin/questions/{qid}/mapping", json={"concepts": ["percentage-basics"], "pattern": "percentage-elections:margin-to-total"})
    assert wrong.status_code == 422
    ok = admin.post(
        f"{API}/admin/questions/{qid}/mapping", json={"concepts": ["percentage-elections"], "pattern": "percentage-elections:margin-to-total", "pool": "mock"}
    )
    assert ok.status_code == 200 and ok.json()["pool"] == "mock"
    assert admin.get(f"{API}/admin/pyq/unmapped").json() == []
    assert learner.post(f"{API}/admin/questions/{qid}/mapping", json={"concepts": ["percentage-elections"]}).status_code == 403


def test_pyq_endpoints_are_staff_only(sclient, learner):
    assert submit(learner).status_code == 403
    for path in ("imports", "sources", "unmapped"):
        assert learner.get(f"{API}/admin/pyq/{path}").status_code == 403


def test_verified_pyqs_feed_the_study_pack_analysis(sclient, admin, worker, learner):
    run(admin, worker)
    later = {**PAPER, "key": "ssc-cgl:tier2:2025-01-18:s1", "tier": "tier2", "year": 2025, "exam_date": "2025-01-18"}
    run(
        admin,
        worker,
        paper=later,
        rows=[mcq(1, "Two candidates scoring 35% and 45% fail by 20 and pass by 30. Find the maximum marks.", pattern="percentage-marks:two-students")],
    )
    with SessionLocal() as db:
        for q in pyqs(db):
            q.status = "verified"
        db.commit()
    for item in admin.get(f"{API}/admin/review-queue?asset_type=pattern&limit=500").json():
        if item["key"].startswith("percentage-marks:"):
            admin.post(f"{API}/admin/assets/pattern/{item['id']}/decision", json={"decision": "approve"})
    pack = learner.get(f"{API}/concepts/percentage-marks/study-pack").json()
    assert pack["pyq"] == {"total": 2, "by_year": {"2024": 1, "2025": 1}, "by_tier": {"tier1": 1, "tier2": 1}, "first_year": 2024, "last_year": 2025}
    two = next(p for p in pack["patterns"] if p["key"] == "percentage-marks:two-students")
    assert two["pyq_count"] == 2
    report = admin.get(f"{API}/admin/courses/ssc-cgl/coverage?scope=quant.percentage").json()
    marks = next(c for c in report["concepts"] if c["slug"] == "percentage-marks")
    assert marks["have"]["pyq_questions"] == 2 and marks["have"]["practice_questions"] == 2
