"""Timed mock tests: start, save answers, submit with negative marking, reports."""

from datetime import UTC, datetime, timedelta

from conftest import API, answer_for, make_actor, wrong_for

from app.core.db import SessionLocal
from app.modules.learning.models import Attempt, TestAttempt

COURSE = "ssc-cgl-quant-arithmetic"


def start(actor):
    tests = actor.get(f"{API}/courses/{COURSE}/tests").json()
    assert len(tests) == 1 and tests[0]["questions"] == 20 and tests[0]["max_marks"] == 40
    r = actor.post(f"{API}/tests/{tests[0]['id']}/start")
    assert r.status_code == 200, r.text
    return tests[0], r.json()


def test_full_mock_with_negative_marking(learner):
    meta, run = start(learner)
    assert run["instructions"].startswith("2 mark(s) per question; 0.5 deducted")
    items = run["items"]
    assert len(items) == 20 and all("answer" not in i["question"]["payload"] for i in items)
    ta = run["test_attempt_id"]
    right, wrong = items[:12], items[12:16]  # 4 left unanswered
    for it in right:
        assert (
            learner.put(
                f"{API}/test-attempts/{ta}/answers", json={"question_id": it["question"]["id"], "response": answer_for(it["question"]["id"])}
            ).status_code
            == 200
        )
    for it in wrong:
        learner.put(f"{API}/test-attempts/{ta}/answers", json={"question_id": it["question"]["id"], "response": wrong_for(it["question"]["id"])})
    # Resuming returns the same attempt with the saved answers.
    resumed = learner.post(f"{API}/tests/{meta['id']}/start").json()
    assert resumed["test_attempt_id"] == ta and len(resumed["answers"]) == 16

    report = learner.post(f"{API}/test-attempts/{ta}/submit").json()
    assert report["score"] == 12 * 2 - 4 * 0.5 == 22
    assert report["max_score"] == 40 and report["percent"] == 55.0
    assert (report["attempted"], report["questions"]) == (16, 20)
    assert report["accuracy"] == 0.75
    section = report["sections"][0]
    assert (section["correct"], section["wrong"], section["unattempted"]) == (12, 4, 4)
    review = {r["question"]["id"]: r for r in report["review"]}
    assert review[wrong[0]["question"]["id"]]["marks"] == -0.5
    assert review[items[-1]["question"]["id"]]["marks"] == 0 and review[items[-1]["question"]["id"]]["answered"] is False
    assert review[right[0]["question"]["id"]]["correct_answer"] is not None

    # Submitting twice returns the stored report; late answers are refused.
    assert learner.post(f"{API}/test-attempts/{ta}/submit").json() == report
    late = learner.put(f"{API}/test-attempts/{ta}/answers", json={"question_id": items[-1]["question"]["id"], "response": {"choice": "a"}})
    assert late.status_code == 409
    assert learner.get(f"{API}/test-attempts/{ta}").json()["score"] == 22
    assert learner.get(f"{API}/courses/{COURSE}/tests").json()[0]["last_score"] == 22
    with SessionLocal() as db:
        assert db.query(Attempt).filter(Attempt.user_id == learner.id).count() == 16  # answered items feed mastery
    # A new start after submitting opens a fresh attempt.
    assert learner.post(f"{API}/tests/{meta['id']}/start").json()["test_attempt_id"] != ta


def test_attempts_are_private(learner):
    _, run = start(learner)
    other = make_actor(learner.client)
    ta = run["test_attempt_id"]
    assert other.get(f"{API}/test-attempts/{ta}").status_code == 404
    assert other.post(f"{API}/test-attempts/{ta}/submit").status_code == 404
    qid = run["items"][0]["question"]["id"]
    assert other.put(f"{API}/test-attempts/{ta}/answers", json={"question_id": qid, "response": {"choice": "a"}}).status_code == 404


def test_answers_must_belong_to_the_test(learner):
    _, run = start(learner)
    stranger = learner.get(f"{API}/practice/next", params={"concept": "python-loops"}).json()["question"]
    r = learner.put(f"{API}/test-attempts/{run['test_attempt_id']}/answers", json={"question_id": stranger["id"], "response": {"choice": "a"}})
    assert r.status_code == 404


def test_timer_is_enforced(learner):
    _, run = start(learner)
    ta, item = run["test_attempt_id"], run["items"][0]["question"]["id"]
    learner.put(f"{API}/test-attempts/{ta}/answers", json={"question_id": item, "response": answer_for(item)})
    with SessionLocal() as db:
        attempt = db.get(TestAttempt, __import__("uuid").UUID(ta))
        attempt.started_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    late = learner.put(f"{API}/test-attempts/{ta}/answers", json={"question_id": run["items"][1]["question"]["id"], "response": {"choice": "a"}})
    assert late.status_code == 409 and "Time is up" in late.json()["detail"]
    report = learner.post(f"{API}/test-attempts/{ta}/submit").json()
    assert report["score"] == 2 and report["time_taken_seconds"] == 12 * 60 + 120  # capped at the duration + grace
    with SessionLocal() as db:
        assert db.query(Attempt).filter(Attempt.user_id == learner.id).one().seconds == (12 * 60 + 120) // 20


def test_unknown_test(learner):
    assert learner.post(f"{API}/tests/{__import__('uuid').uuid4()}/start").status_code == 404
