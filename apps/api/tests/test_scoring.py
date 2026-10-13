import pytest

from app.modules.assessment import scoring

MCQ = {"options": [{"id": "a", "text": "1"}, {"id": "b", "text": "2"}], "answer": "b"}
MULTI = {"options": [{"id": x, "text": x} for x in "abcd"], "answers": ["a", "c"]}


def test_choice_correct_wrong_and_unanswered():
    assert scoring.score_choice(MCQ, {"choice": "B "}).is_correct  # case and whitespace tolerant
    wrong = scoring.score_choice(MCQ, {"choice": "a"})
    assert (wrong.score, wrong.is_correct, wrong.detail["correct_answer"]) == (0.0, False, "b")
    assert scoring.score_choice(MCQ, {}).detail == {"answered": False}


def test_multi_needs_the_exact_set_unless_partial():
    assert scoring.score_multi(MULTI, {"choices": ["c", "a"]}).score == 1.0
    assert scoring.score_multi(MULTI, {"choices": ["a"]}).score == 0.0
    partial = {**MULTI, "partial": True}
    assert scoring.score_multi(partial, {"choices": ["a"]}).score == 0.5
    assert scoring.score_multi(partial, {"choices": ["a", "b"]}).score == 0.0  # a wrong pick voids partial credit
    assert scoring.score_multi(MULTI, {"choices": []}).detail["answered"] is False


@pytest.mark.parametrize(
    ("value", "ok"),
    [("12.5", True), ("12.51", True), ("12.52", False), ("1,012.5", False), (" 12.5 ", True), (12.5, True)],
)
def test_numerical_tolerance(value, ok):
    payload = {"answer": 12.5, "tolerance": 0.01}
    assert scoring.score_numerical(payload, {"value": value}).is_correct is ok


def test_numerical_accepts_thousands_separators_and_rejects_text():
    assert scoring.score_numerical({"answer": 1012.5}, {"value": "1,012.5"}).is_correct
    bad = scoring.score_numerical({"answer": 3}, {"value": "three"})
    assert bad.detail["answered"] and bad.detail["error"] == "not a number"
    assert scoring.score_numerical({"answer": 3}, {"value": ""}).detail["answered"] is False


def test_marks_with_negative_marking():
    right = scoring.ScoreResult(1.0, True, {"answered": True})
    wrong = scoring.ScoreResult(0.0, False, {"answered": True})
    skipped = scoring.ScoreResult(0.0, False, {"answered": False})
    half = scoring.ScoreResult(0.5, False, {"answered": True})
    assert scoring.marks_for(right, 2, 0.5) == 2
    assert scoring.marks_for(wrong, 2, 0.5) == -0.5
    assert scoring.marks_for(skipped, 2, 0.5) == 0
    assert scoring.marks_for(half, 4, 1) == 2  # partial credit is never penalised


def test_score_objective_rejects_subjective_types():
    with pytest.raises(ValueError):
        scoring.score_objective("descriptive", {}, {})


def test_speaking_match():
    perfect = scoring.score_speaking("I usually wake up at six.", "i usually wake up at six")
    assert perfect.score == 1.0 and perfect.is_correct
    r = scoring.score_speaking("I usually wake up at six", "I wake up at seven")
    assert r.detail["missed"] == ["usually"]
    assert r.detail["substitutions"] == [{"expected": "six", "heard": "seven"}]
    assert r.score == pytest.approx(4 / 6, abs=1e-4) and not r.is_correct
    assert scoring.score_speaking("Hello there", "").detail["answered"] is False
