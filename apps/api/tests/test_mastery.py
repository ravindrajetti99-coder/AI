from datetime import UTC, datetime, timedelta

import pytest

from app.modules.learning import mastery as mm

NOW = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)


def test_success_raises_ability_and_failure_lowers_it():
    assert mm.update_ability(0.0, 0.0, 1.0) > 0.0
    assert mm.update_ability(0.0, 0.0, 0.0) < 0.0


def test_harder_items_teach_more():
    easy_gain = mm.update_ability(0.0, -2.0, 1.0)
    hard_gain = mm.update_ability(0.0, 2.0, 1.0)
    assert hard_gain > easy_gain


def test_hints_and_slow_answers_shrink_gains_but_not_losses():
    clean = mm.update_ability(0.0, 0.0, 1.0)
    hinted = mm.update_ability(0.0, 0.0, 1.0, hints_used=3)
    slow = mm.update_ability(0.0, 0.0, 1.0, seconds=400, target_seconds=90)
    assert hinted < clean and slow < clean
    assert mm.update_ability(0.0, 0.0, 0.0, hints_used=6) == mm.update_ability(0.0, 0.0, 0.0)
    assert mm.update_ability(0.0, 0.0, 1.0, hints_used=100) > 0.0  # gain floor of 20%


def test_ability_is_clamped():
    theta = 3.9
    for _ in range(50):
        theta = mm.update_ability(theta, -4.0, 1.0)
    assert theta <= 4.0


def test_difficulty_calibration():
    assert mm.update_difficulty(0.0, 0.0, 1.0) < 0.0  # beaten -> easier
    assert mm.update_difficulty(0.0, 0.0, 0.0) > 0.0  # missed -> harder


def test_labels():
    assert mm.label(0.95, 2) == "learning"  # too few attempts to judge
    assert mm.label(0.3, 5) == "weak"
    assert mm.label(0.6, 5) == "developing"
    assert mm.label(0.85, 5) == "strong"


def test_target_difficulty_aims_for_seventy_percent():
    for theta in (-2.0, 0.0, 1.5):
        assert mm.expected_score(theta, mm.target_difficulty(theta)) == pytest.approx(0.70, abs=0.01)


def test_revision_ladder_success_path():
    learned = NOW
    assert mm.first_due(learned) == learned + timedelta(days=2)  # day 3 counting the learning day
    stage, anchor, due, done = mm.next_review(0, learned, True, learned + timedelta(days=2))
    assert (stage, anchor, done) == (1, learned, False)
    assert due == learned + timedelta(days=6)  # day 7
    stage, _, due, _ = mm.next_review(stage, learned, True, learned + timedelta(days=6))
    assert (stage, due) == (2, learned + timedelta(days=14))
    stage, _, due, _ = mm.next_review(stage, learned, True, learned + timedelta(days=14))
    assert (stage, due) == (3, learned + timedelta(days=29))
    _, _, _, done = mm.next_review(stage, learned, True, learned + timedelta(days=29))
    assert done


def test_revision_ladder_miss_restarts_and_late_learners_get_breathing_room():
    stage, anchor, due, done = mm.next_review(2, NOW - timedelta(days=20), False, NOW)
    assert (stage, anchor, due, done) == (0, NOW, mm.first_due(NOW), False)
    late = NOW + timedelta(days=40)
    stage, _, due, _ = mm.next_review(0, NOW, True, late)
    assert stage == 1 and due > late
