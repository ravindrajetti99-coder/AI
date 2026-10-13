"""Learner model maths: Elo/IRT-style mastery and the spaced revision ladder (pure functions)."""

import math
from datetime import datetime, timedelta

K_LEARNER = 0.6  # learning rate for ability updates
K_ITEM = 0.05  # learning rate for item difficulty calibration
WEAK_THRESHOLD = 0.5
STRONG_THRESHOLD = 0.8
MIN_ATTEMPTS_FOR_LABEL = 3

# Day 1 learn -> day 3 revision -> day 7 practice -> day 15 advanced test -> day 30 final recall.
LADDER = [
    {"stage": 0, "name": "revision", "day": 3},
    {"stage": 1, "name": "practice", "day": 7},
    {"stage": 2, "name": "advanced_test", "day": 15},
    {"stage": 3, "name": "final_recall", "day": 30},
]


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def expected_score(theta: float, b: float) -> float:
    return sigmoid(theta - b)


def update_ability(theta: float, b: float, score: float, hints_used: int = 0, seconds: int = 0, target_seconds: int = 0) -> float:
    """Raise ability more for success on harder items; hints and very slow answers shrink the gain.
    Failures always count fully, so hints never hide a gap."""
    p = expected_score(theta, b)
    gain = score - p
    if gain > 0:
        gain *= max(0.2, 1.0 - 0.15 * hints_used)
        if target_seconds and seconds > 3 * target_seconds:
            gain *= 0.7
    return max(-4.0, min(4.0, theta + K_LEARNER * gain))


def update_difficulty(b: float, theta: float, score: float) -> float:
    """Items learners beat more than expected get easier; ones they miss get harder."""
    return max(-4.0, min(4.0, b - K_ITEM * (score - expected_score(theta, b))))


def mastery_score(theta: float) -> float:
    return round(sigmoid(theta), 4)


def label(score: float, attempts: int) -> str:
    if attempts < MIN_ATTEMPTS_FOR_LABEL:
        return "learning"
    if score < WEAK_THRESHOLD:
        return "weak"
    if score >= STRONG_THRESHOLD:
        return "strong"
    return "developing"


def first_due(learned_at: datetime) -> datetime:
    return learned_at + timedelta(days=LADDER[0]["day"] - 1)


def next_review(stage: int, learned_at: datetime, success: bool, now: datetime) -> tuple[int, datetime, datetime, bool]:
    """Returns (new_stage, new_learned_at, due_at, completed).

    Success moves one rung up the ladder (due dates are anchored to the learning day).
    A miss restarts the ladder from today: the concept is treated as freshly relearned."""
    if not success:
        return 0, now, first_due(now), False
    nxt = stage + 1
    if nxt >= len(LADDER):
        return stage, learned_at, now, True
    due = learned_at + timedelta(days=LADDER[nxt]["day"] - 1)
    if due <= now:  # learner is late: don't make the next rung immediately due
        due = now + timedelta(days=max(1, LADDER[nxt]["day"] - LADDER[stage]["day"]))
    return nxt, learned_at, due, False


def target_difficulty(theta: float) -> float:
    """Desirable difficulty: items the learner should get right about 70% of the time
    (sigmoid(0.85) ~= 0.70) - hard enough to stretch, easy enough to keep momentum."""
    return theta - 0.85
