"""Deterministic scoring for objective question types (pure functions, no I/O)."""

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass
class ScoreResult:
    score: float  # 0..1 fraction of credit
    is_correct: bool
    detail: dict = field(default_factory=dict)


def _norm_choice(value) -> str:
    return str(value).strip().lower()


def score_choice(payload: dict, response: dict) -> ScoreResult:
    """mcq / assertion_reason / case_study: one correct option id."""
    chosen = response.get("choice")
    if chosen is None:
        return ScoreResult(0.0, False, {"answered": False})
    ok = _norm_choice(chosen) == _norm_choice(payload["answer"])
    return ScoreResult(1.0 if ok else 0.0, ok, {"answered": True, "correct_answer": payload["answer"]})


def score_multi(payload: dict, response: dict) -> ScoreResult:
    """multi-correct. Exams normally award full credit only for the exact set;
    payload.partial=True enables JEE-style partial credit (no wrong picks allowed)."""
    chosen = {_norm_choice(c) for c in response.get("choices") or []}
    if not chosen:
        return ScoreResult(0.0, False, {"answered": False})
    answers = {_norm_choice(a) for a in payload["answers"]}
    if chosen == answers:
        return ScoreResult(1.0, True, {"answered": True, "correct_answer": sorted(answers)})
    if payload.get("partial") and chosen < answers:
        return ScoreResult(len(chosen) / len(answers), False, {"answered": True, "partial": True, "correct_answer": sorted(answers)})
    return ScoreResult(0.0, False, {"answered": True, "correct_answer": sorted(answers)})


def score_numerical(payload: dict, response: dict) -> ScoreResult:
    raw = response.get("value")
    if raw is None or raw == "":
        return ScoreResult(0.0, False, {"answered": False})
    try:
        value = float(str(raw).replace(",", "").strip())
    except ValueError:
        return ScoreResult(0.0, False, {"answered": True, "error": "not a number", "correct_answer": payload["answer"]})
    answer = float(payload["answer"])
    tol = float(payload.get("tolerance", 0.0))
    # Absolute tolerance, plus a tiny relative slack for floating point.
    ok = math.isclose(value, answer, abs_tol=max(tol, 1e-9), rel_tol=1e-9)
    return ScoreResult(1.0 if ok else 0.0, ok, {"answered": True, "correct_answer": answer, "unit": payload.get("unit", "")})


def score_objective(qtype: str, payload: dict, response: dict) -> ScoreResult:
    if qtype in ("mcq", "assertion_reason", "case_study"):
        return score_choice(payload, response)
    if qtype == "multi":
        return score_multi(payload, response)
    if qtype == "numerical":
        return score_numerical(payload, response)
    raise ValueError(f"{qtype} is not an objective type")


def marks_for(result: ScoreResult, marks: float, negative: float) -> float:
    """Exam marks: full/partial credit, negative marking only for a wrong attempted answer."""
    if not result.detail.get("answered"):
        return 0.0
    if result.score > 0:
        return round(marks * result.score, 4)
    return -abs(negative)


_WORD = re.compile(r"[\w']+", re.UNICODE)


def score_speaking(target: str, transcript: str) -> ScoreResult:
    """Pronunciation practice: compare a speech-recognition transcript with the target sentence
    word by word. Returns accuracy and the words that were missed or substituted."""
    t_words = [w.lower() for w in _WORD.findall(target)]
    s_words = [w.lower() for w in _WORD.findall(transcript or "")]
    if not t_words:
        return ScoreResult(0.0, False, {"answered": bool(s_words)})
    sm = SequenceMatcher(a=t_words, b=s_words, autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    missed: list[str] = []
    substitutions: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            missed.extend(t_words[i1:i2])
        elif tag == "replace":
            substitutions.append({"expected": " ".join(t_words[i1:i2]), "heard": " ".join(s_words[j1:j2])})
    accuracy = matched / len(t_words)
    return ScoreResult(
        round(accuracy, 4),
        accuracy >= 0.9,
        {"answered": bool(s_words), "accuracy": round(accuracy, 4), "missed": missed, "substitutions": substitutions},
    )
