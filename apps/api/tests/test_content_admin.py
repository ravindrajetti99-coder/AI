"""Lessons, tutor, flags, and the admin content pipeline: uploads, retrieval, generation jobs, review."""

import uuid

from conftest import API, concept_id, make_actor
from sqlalchemy import select

from app.ai import retrieval
from app.core.db import SessionLocal
from app.modules.content.models import Lesson
from app.modules.identity.models import AuditLog

NOTES = b"""# Simple Interest

Simple interest is the interest calculated only on the principal amount. The formula is SI = P x R x T / 100.

Interest earned each year stays the same because the principal does not change.

# Compound Interest

Compound interest is calculated on the principal plus the interest added so far. The amount is A = P(1 + R/100)^T.

Compound interest grows faster than simple interest because interest is earned on interest.
"""


# --------------------------------------------------------------------------- lessons and tutor


def test_lesson_levels_locales_and_missing_levels(learner):
    en = learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 1}).json()
    assert en["verified"] and en["locale"] == "en" and en["body"]["diagram"].startswith("flowchart")
    te = learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 1, "locale": "te"}).json()
    assert te["locale"] == "te" and "శాతం" in te["body"]["definition"]
    fallback = learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 2, "locale": "te"}).json()
    assert fallback["locale"] == "en" and "showing English" in fallback["note"]
    missing = learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 4}).json()
    assert missing["status"] == "missing" and missing["can_generate"]
    assert learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 5}).status_code == 422
    assert learner.get(f"{API}/concepts/nope/lesson").status_code == 404


def test_generating_a_missing_level_creates_a_draft_for_review(learner):
    r = learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 4, "generate": True}).json()
    assert r["status"] == "in_review" and not r["verified"] and r["source"] == "offline"
    assert "without an AI model" in r["note"] and r["body"]["definition"]
    again = learner.get(f"{API}/concepts/percentage-basics/lesson", params={"level": 4}).json()
    assert again["id"] == r["id"] and "not yet verified" in again["note"]


def test_flashcards_and_tutor(learner):
    cards = learner.get(f"{API}/concepts/simple-interest/flashcards").json()
    assert {"front": "SI formula", "back": "P × R × T / 100"}.items() <= cards[0].items()
    first = learner.post(f"{API}/concepts/simple-interest/ask", json={"question": "What does the principal mean in simple interest?"}).json()
    assert first["provider"] == "offline" and "Principal" in first["reply"] and first["follow_up_questions"]
    follow = learner.post(f"{API}/concepts/simple-interest/ask", json={"question": "and the time?", "conversation_id": first["conversation_id"]}).json()
    assert follow["conversation_id"] == first["conversation_id"]
    other = make_actor(learner.client)
    stolen = other.post(f"{API}/concepts/simple-interest/ask", json={"question": "hi", "conversation_id": first["conversation_id"]})
    assert stolen.status_code == 404


def test_learners_can_flag_content_for_staff(learner, admin):
    lesson = learner.get(f"{API}/concepts/discount/lesson").json()
    assert learner.post(f"{API}/content/flags", json={"asset_type": "lesson", "asset_id": lesson["id"], "reason": "Example 2 has a typo"}).status_code == 201
    assert learner.get(f"{API}/admin/flags").status_code == 403
    flags = admin.get(f"{API}/admin/flags").json()
    assert flags[0]["asset_id"] == lesson["id"] and flags[0]["reason"] == "Example 2 has a typo"


# --------------------------------------------------------------------------- uploads and retrieval


def course_id(client, slug="ssc-cgl-quant-arithmetic"):
    return client.get(f"{API}/courses/{slug}").json()["id"]


def test_upload_parses_and_chunks_with_headings(admin):
    r = admin.post(
        f"{API}/admin/documents",
        files={"file": ("interest notes.md", NOTES, "text/markdown")},
        data={"title": "Interest notes", "course_id": course_id(admin.client)},
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "chunked" and doc["chunks"] >= 1 and doc["filename"] == "interest_notes.md"
    with SessionLocal() as db:
        hits = retrieval.search(db, "compound interest on interest", course_id=uuid.UUID(course_id(admin.client)))
    assert hits and hits[0]["heading"] == "Compound Interest"
    assert [d["id"] for d in admin.get(f"{API}/admin/documents").json()] == [doc["id"]]


def test_upload_validation(admin, learner):
    assert admin.post(f"{API}/admin/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    assert admin.post(f"{API}/admin/documents", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")}).status_code == 400
    assert learner.post(f"{API}/admin/documents", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 403
    missing = admin.post(f"{API}/admin/documents", files={"file": ("a.txt", b"hello", "text/plain")}, data={"course_id": str(uuid.uuid4())})
    assert missing.status_code == 404


def test_chunking_keeps_headings_pages_and_overlap():
    text = "\f[page 1]\n\nIntro\n\n" + " ".join(f"w{i}" for i in range(500)) + "\n\n\f[page 2]\n\nTail paragraph here."
    chunks = retrieval.chunk_text(text, target_words=200, overlap_words=20)
    assert chunks[0]["heading"] == "Intro" and chunks[0]["page"] == 1
    assert chunks[-1]["page"] == 2 and "Tail paragraph" in chunks[-1]["text"]


# --------------------------------------------------------------------------- generation jobs and review


def run_job(admin, **body):
    r = admin.post(f"{API}/admin/generate", json=body)
    assert r.status_code == 202, r.text
    job = admin.get(f"{API}/admin/jobs/{r.json()['job_id']}").json()  # background task ran after the response
    assert job["status"] == "done", job
    return job


def test_generation_jobs_create_review_drafts(admin):
    cid = str(concept_id("discount"))
    lessons = run_job(admin, kind="lessons", concept_ids=[cid], levels=[3, 4])
    assert [c["level"] for c in lessons["outputs"]["created"]] == [3, 4] and lessons["outputs"]["providers"] == ["offline"]
    cards = run_job(admin, kind="flashcards", concept_ids=[cid], count=3)
    assert cards["outputs"]["created"]
    questions = run_job(admin, kind="questions", concept_ids=[cid], count=3)
    assert questions["outputs"]["created"] or questions["outputs"]["skipped"] == 0
    mock = run_job(admin, kind="mock_test", course_id=course_id(admin.client), count=10, title="Quick 10")
    assert mock["outputs"]["created"][0]["title"] == "Quick 10"
    queue = admin.get(f"{API}/admin/review-queue").json()
    kinds = {item["asset_type"] for item in queue}
    assert {"lesson", "flashcard"} <= kinds
    with SessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "generate"))
        assert audit.entity_id == lessons["id"]  # the job id, recorded after it exists


def test_notes_job_summarises_an_uploaded_document(admin):
    doc = admin.post(f"{API}/admin/documents", files={"file": ("notes.md", NOTES, "text/markdown")}, data={"title": "Interest notes"}).json()
    job = run_job(admin, kind="notes", document_id=doc["id"], concept_ids=[str(concept_id("compound-interest"))])
    note = next(i for i in admin.get(f"{API}/admin/review-queue", params={"asset_type": "note"}).json() if i["id"] == job["outputs"]["created"][0]["id"])
    assert note["concept"] == "Compound interest"
    assert "Simple interest is the interest" in note["content"]["body"] and "Compound interest" in note["content"]["body"]


def test_job_validation(admin, learner):
    assert admin.post(f"{API}/admin/generate", json={"kind": "lessons"}).status_code == 400
    assert admin.post(f"{API}/admin/generate", json={"kind": "notes"}).status_code == 400
    assert admin.post(f"{API}/admin/generate", json={"kind": "lessons", "concept_ids": [str(concept_id("discount"))], "levels": [7]}).status_code == 400
    assert learner.post(f"{API}/admin/generate", json={"kind": "lessons", "concept_ids": []}).status_code == 403
    failed = admin.post(f"{API}/admin/generate", json={"kind": "mock_test", "course_id": str(uuid.uuid4())}).json()
    assert admin.get(f"{API}/admin/jobs/{failed['job_id']}").json()["status"] == "failed"


def test_review_decisions(admin, learner):
    reviewer = make_actor(admin.client, "reviewer")
    cid = concept_id("discount")
    job = run_job(admin, kind="lessons", concept_ids=[str(cid)], levels=[1])
    draft_id = job["outputs"]["created"][0]["id"]
    edits = {"definition": "A discount is a reduction on the marked price."}
    r = reviewer.post(f"{API}/admin/assets/lesson/{draft_id}/decision", json={"decision": "approve", "edits": edits})
    assert r.json()["status"] == "verified"
    shown = learner.get(f"{API}/concepts/discount/lesson", params={"level": 1}).json()
    assert shown["id"] == draft_id and shown["body"]["definition"] == edits["definition"]
    with SessionLocal() as db:
        statuses = {lesson.source: lesson.status for lesson in db.scalars(select(Lesson).where(Lesson.concept_id == cid, Lesson.level == 1)).all()}
    assert statuses == {"manual": "retired", "offline": "verified"}  # one verified lesson per slot
    bad = reviewer.post(f"{API}/admin/assets/lesson/{draft_id}/decision", json={"decision": "approve", "edits": {"examples": "not a list"}})
    assert bad.status_code == 422
    assert reviewer.post(f"{API}/admin/assets/widget/{draft_id}/decision", json={"decision": "approve"}).status_code == 404
    assert learner.post(f"{API}/admin/assets/lesson/{draft_id}/decision", json={"decision": "reject"}).status_code == 403


def test_reviewed_questions_reach_practice(admin, learner):
    cid = str(concept_id("discount"))
    q = admin.post(
        f"{API}/admin/questions",
        json={
            "concept_ids": [cid],
            "qtype": "mcq",
            "stem": "A ₹1,000 item at 10% off costs?",
            "payload": {"options": [{"id": "a", "text": "₹900"}, {"id": "b", "text": "₹990"}], "answer": "a"},
            "steps": {"hint": "Discount is on the marked price."},
            "pyq_year": 2023,
        },
    )
    assert q.status_code == 201
    shown = learner.get(f"{API}/questions/{q.json()['id']}").json()
    assert shown["source"] == "pyq" and shown["pyq_year"] == 2023
    no_rubric = admin.post(
        f"{API}/admin/questions", json={"concept_ids": [cid], "qtype": "descriptive", "stem": "Explain discounts.", "payload": {"max_marks": 5}}
    )
    assert no_rubric.status_code == 400


def test_stats_and_ai_usage(admin, learner):
    learner.post(f"{API}/concepts/simple-interest/ask", json={"question": "What is principal?"})
    stats = admin.get(f"{API}/admin/stats").json()
    assert stats["courses"] == 6 and stats["concepts"] == 36 and stats["questions_verified"] > 200
    usage = admin.get(f"{API}/admin/ai-usage").json()
    row = next(r for r in usage["rows"] if r["feature"] == "tutor.chat")
    assert row["provider"] == "offline" and row["calls"] == 1 and row["cost_usd"] == 0
    assert learner.get(f"{API}/admin/stats").status_code == 403


def test_health(sclient):
    body = sclient.get(f"{API}/health").json()
    assert body == {"status": "ok", "ai": {"providers": [], "mode": "offline"}, "env": "test"}
    r = sclient.get(f"{API}/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
