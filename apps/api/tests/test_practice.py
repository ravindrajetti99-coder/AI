"""Practice -> attempt -> mastery -> revision, adaptive selection, plans and the dashboard."""

from datetime import UTC, datetime, timedelta

from conftest import API, answer_for, concept_id, make_actor, set_mastery, wrong_for
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.assessment.models import Question
from app.modules.learning.models import Attempt, Mastery, ReviewItem

COURSE = "ssc-cgl-quant-arithmetic"


def test_enrollment(learner):
    assert learner.post(f"{API}/courses/{COURSE}/enroll").status_code == 201
    assert learner.post(f"{API}/courses/{COURSE}/enroll").status_code == 201  # idempotent
    assert [e["slug"] for e in learner.get(f"{API}/me/enrollments").json()] == [COURSE]
    assert learner.delete(f"{API}/courses/{COURSE}/enroll").status_code == 204
    assert learner.get(f"{API}/me/enrollments").json() == []


def test_next_question_hides_answer_keys_and_starts_at_the_syllabus_frontier(learner):
    r = learner.get(f"{API}/practice/next", params={"course": COURSE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reason"] == "next in syllabus" and body["concept"]["slug"] == "percentage-basics"
    q = body["question"]
    assert "answer" not in q["payload"] and "answers" not in q["payload"] and "tolerance" not in q["payload"]
    assert q["concepts"][0]["slug"] == "percentage-basics"
    assert learner.get(f"{API}/practice/next").status_code == 400


def test_coding_questions_show_only_visible_examples(learner):
    r = learner.get(f"{API}/practice/next", params={"concept": "python-functions", "types": "coding"}).json()
    payload = r["question"]["payload"]
    assert payload["starter_code"] and payload["function_name"]
    assert payload["examples"] and all(not t.get("hidden") for t in payload["examples"])
    assert "tests" not in payload


def test_correct_attempt_raises_mastery_and_schedules_revision(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "percentage-basics"}).json()["question"]
    r = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"]), "seconds": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_correct"] and body["score"] == 1.0 and body["steps"]
    change = body["mastery"][0]
    assert change["after"] > change["before"] and change["label"] == "learning"
    with SessionLocal() as db:
        review = db.scalar(select(ReviewItem).where(ReviewItem.user_id == learner.id))
        assert review.stage == 0 and review.due_at.date() > datetime.now(UTC).date()
    history = learner.get(f"{API}/me/attempts").json()
    assert len(history) == 1 and history[0]["is_correct"]


def test_wrong_answer_explains_the_mistake(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "profit-loss", "types": "mcq"}).json()["question"]
    body = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": wrong_for(q["id"])}).json()
    assert body["is_correct"] is False and body["correct_answer"]
    assert "correct answer is" in body["feedback"]["mistake_note"]
    assert body["mastery"][0]["after"] < body["mastery"][0]["before"]


def test_unanswered_attempts_are_rejected(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "percentage-basics", "types": "mcq"}).json()["question"]
    r = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": {}})
    assert r.status_code == 400


def test_hints_reduce_the_mastery_gain(sclient):
    a, b = make_actor(sclient), make_actor(sclient)
    q = a.get(f"{API}/practice/next", params={"concept": "simple-interest", "types": "mcq"}).json()["question"]
    steps = a.get(f"{API}/questions/{q['id']}/steps/2").json()
    assert [s["kind"] for s in steps["steps"]] == ["hint", "concept"] and steps["total_steps"] >= 4
    a.get(f"{API}/questions/{q['id']}/steps/6")
    assert a.get(f"{API}/questions/{q['id']}/steps/7").status_code == 400
    with_hints = a.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"])}).json()
    clean = b.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"])}).json()
    assert with_hints["hints_used"] == 6 and clean["hints_used"] == 0
    gain_hinted = with_hints["mastery"][0]["after"] - with_hints["mastery"][0]["before"]
    gain_clean = clean["mastery"][0]["after"] - clean["mastery"][0]["before"]
    assert 0 < gain_hinted < gain_clean
    # Hints are consumed by the attempt; the next attempt starts clean.
    again = a.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"])}).json()
    assert again["hints_used"] == 0


def test_recently_answered_and_excluded_questions_are_skipped(learner):
    first = learner.get(f"{API}/practice/next", params={"concept": "discount"}).json()["question"]
    learner.post(f"{API}/attempts", json={"question_id": first["id"], "response": answer_for(first["id"])})
    second = learner.get(f"{API}/practice/next", params={"concept": "discount"}).json()["question"]
    assert second["id"] != first["id"]
    third = learner.get(f"{API}/practice/next", params={"concept": "discount", "exclude": second["id"]}).json()["question"]
    assert third["id"] not in (first["id"], second["id"])


def test_adaptive_choice_targets_desirable_difficulty(learner):
    with SessionLocal() as db:
        qs = db.scalars(select(Question).where(Question.external_key.startswith("compound-interest:"))).all()
        spread = {q.difficulty for q in qs}
    assert {"medium", "hard"} <= spread
    set_mastery(learner.id, "compound-interest", 0.9, 10, theta=3.0)  # target b = 2.15 -> hardest items
    strong = learner.get(f"{API}/practice/next", params={"concept": "compound-interest"}).json()["question"]
    assert strong["difficulty"] == "hard"
    set_mastery(learner.id, "compound-interest", 0.12, 10, theta=-2.0)  # target b = -2.85 -> easiest items
    weak = learner.get(f"{API}/practice/next", params={"concept": "compound-interest"}).json()["question"]
    assert weak["difficulty"] == "medium"


def test_prerequisite_gap_is_fixed_first(learner):
    set_mastery(learner.id, "percentage-basics", 0.4, 1)  # still "learning", but below the weak line
    set_mastery(learner.id, "percentage-change", 0.3, 5)  # weak
    r = learner.get(f"{API}/practice/next", params={"course": COURSE}).json()
    assert r["concept"]["slug"] == "percentage-basics"
    assert r["reason"] == "prerequisite gap behind Percentage increase and decrease"


def test_due_revisions_come_first(learner):
    with SessionLocal() as db:
        db.add(
            ReviewItem(
                user_id=learner.id,
                concept_id=concept_id("discount"),
                stage=0,
                learned_at=datetime.now(UTC) - timedelta(days=3),
                due_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        db.commit()
    r = learner.get(f"{API}/practice/next", params={"course": COURSE}).json()
    assert (r["concept"]["slug"], r["reason"]) == ("discount", "revision due")


def test_review_cycle(learner):
    learned = datetime.now(UTC) - timedelta(days=2, minutes=5)
    with SessionLocal() as db:
        item = ReviewItem(user_id=learner.id, concept_id=concept_id("simple-interest"), stage=0, learned_at=learned, due_at=learned + timedelta(days=2))
        db.add(item)
        db.commit()
        item_id = item.id
    reviews = learner.get(f"{API}/me/reviews").json()
    assert [d["concept"]["slug"] for d in reviews["due"]] == ["simple-interest"] and reviews["due"][0]["stage_name"] == "revision"
    pack = learner.get(f"{API}/me/reviews/{item_id}/questions").json()
    assert len(pack["questions"]) == 3 and len({q["id"] for q in pack["questions"]}) == 3
    # Completing without answering anything is refused.
    assert learner.post(f"{API}/me/reviews/{item_id}/complete", json={"started_at": pack["started_at"]}).status_code == 400
    for q in pack["questions"]:
        learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"])})
    done = learner.post(f"{API}/me/reviews/{item_id}/complete", json={"started_at": pack["started_at"]}).json()
    assert done["success"] and done["stage"] == 1 and (done["correct"], done["total"]) == (3, 3)
    assert datetime.fromisoformat(done["next_due"]) > datetime.now(UTC)
    forgot = learner.post(f"{API}/me/reviews/{item_id}/complete", json={"self_rating": "forgot"}).json()
    assert forgot["success"] is False and forgot["stage"] == 0
    other = make_actor(learner.client)
    assert other.get(f"{API}/me/reviews/{item_id}/questions").status_code == 404


def test_completing_a_lesson_starts_the_ladder(learner):
    r = learner.post(f"{API}/me/lessons/progress", json={"concept_id": str(concept_id("discount")), "seconds": 300, "completed": True})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(ReviewItem).where(ReviewItem.user_id == learner.id))
        assert db.get(Mastery, (learner.id, concept_id("discount"))).attempts == 0
    upcoming = learner.get(f"{API}/me/reviews").json()["upcoming"]
    assert [u["concept"]["slug"] for u in upcoming] == ["discount"]


def test_plan_prioritises_weak_concepts_within_the_time_budget(learner):
    learner.post(f"{API}/courses/{COURSE}/enroll")
    learner.patch(f"{API}/me", json={"daily_minutes_goal": 45})
    set_mastery(learner.id, "percentage-basics", 0.3, 4)
    plan = learner.get(f"{API}/me/plan", params={"course": COURSE}).json()
    assert plan[0]["kind"] == "weak" and plan[0]["title"] == "Strengthen: Percentage basics"
    assert sum(p["minutes"] for p in plan) <= 45
    item = plan[0]["id"]
    assert learner.patch(f"{API}/me/plan/{item}", json={"status": "done"}).json()["status"] == "done"
    regenerated = learner.post(f"{API}/me/plan/regenerate", params={"course": COURSE}).json()
    assert item not in {p["id"] for p in regenerated}  # finished items are kept, not regenerated
    week = learner.get(f"{API}/me/plan/week", params={"course": COURSE}).json()
    assert len(week) == 7


def test_dashboard(learner):
    learner.post(f"{API}/courses/{COURSE}/enroll")
    q = learner.get(f"{API}/practice/next", params={"course": COURSE}).json()["question"]
    learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"]), "seconds": 40})
    d = learner.get(f"{API}/me/dashboard").json()
    assert d["user"]["name"] == "Ravi" and d["ai"]["mode"] == "offline"
    course = d["courses"][0]
    assert course["slug"] == COURSE and 0 < course["readiness"] < 1 and course["coverage"] > 0
    assert course["modules"][0]["title"] == "Arithmetic"
    assert d["stats"]["attempts"] == 1 and d["stats"]["streak_days"] == 1 and d["stats"]["accuracy"] == 1.0
    assert d["plan"] and all(p["course_id"] == course["course_id"] for p in d["plan"])
    progress = learner.get(f"{API}/me/courses/{COURSE}/progress").json()
    assert progress["readiness"] == course["readiness"]


def test_mentor_note(learner):
    learner.post(f"{API}/courses/{COURSE}/enroll")
    set_mastery(learner.id, "profit-loss", 0.3, 4)
    r = learner.get(f"{API}/me/mentor", params={"course": COURSE})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "offline" and "Profit and loss" in body["message"] and body["focus"] == ["Profit and loss"]


def test_attempts_store_hint_usage_per_attempt(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "discount", "types": "mcq"}).json()["question"]
    learner.get(f"{API}/questions/{q['id']}/steps/1")
    learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": answer_for(q["id"])})
    with SessionLocal() as db:
        assert db.scalar(select(Attempt.hints_used).where(Attempt.user_id == learner.id)) == 1
