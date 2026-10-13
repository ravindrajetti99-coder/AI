"""Compact constructors for hand-authored seed content."""


def L(definition, explanation, examples=(), key_points=(), mistakes=(), memory="", exam="", checks=(), diagram=""):
    return {
        "definition": definition,
        "explanation": explanation,
        "examples": [{"title": t, "body": b} for t, b in examples],
        "diagram": diagram,
        "key_points": list(key_points),
        "common_mistakes": list(mistakes),
        "memory_technique": memory,
        "exam_relevance": exam,
        "check_questions": [{"question": q, "answer": a} for q, a in checks],
        "citations": [],
    }


def steps(hint, concept, approach, solution, shortcut="", mistakes=""):
    return {"hint": hint, "concept": concept, "approach": approach, "solution": solution, "shortcut": shortcut, "mistakes": mistakes}


def mcq(stem, options, answer, explanation, st, difficulty="medium", qtype="mcq", **extra):
    ids = ["a", "b", "c", "d", "e"]
    payload = {"options": [{"id": i, "text": o} for i, o in zip(ids, options, strict=False)], "answer": answer, **extra}
    return {"qtype": qtype, "stem": stem, "payload": payload, "explanation": explanation, "difficulty": difficulty, "steps": st}


AR_OPTIONS = [
    "Both A and R are true, and R is the correct explanation of A",
    "Both A and R are true, but R is not the correct explanation of A",
    "A is true, but R is false",
    "A is false, but R is true",
]


def assertion_reason(assertion, reason, answer, explanation, st, difficulty="medium"):
    return mcq(f"Assertion (A): {assertion}\nReason (R): {reason}", AR_OPTIONS, answer, explanation, st, difficulty, qtype="assertion_reason", assertion=assertion, reason=reason)


def multi(stem, options, answers, explanation, st, difficulty="medium"):
    ids = ["a", "b", "c", "d", "e"]
    return {"qtype": "multi", "stem": stem, "payload": {"options": [{"id": i, "text": o} for i, o in zip(ids, options, strict=False)], "answers": answers}, "explanation": explanation, "difficulty": difficulty, "steps": st}


def descriptive(stem, criteria, model_answer, explanation="", difficulty="medium", qtype="descriptive", word_limit=None, st=None):
    """criteria: [(criterion, max_marks, [expected points])]"""
    rubric = [{"criterion": c, "max_marks": m, "expected_points": pts} for c, m, pts in criteria]
    return {
        "qtype": qtype,
        "stem": stem,
        "payload": {"max_marks": sum(m for _, m, _ in criteria), **({"word_limit": word_limit} if word_limit else {})},
        "explanation": explanation,
        "difficulty": difficulty,
        "steps": st or {},
        "rubric": rubric,
        "model_answer": model_answer,
    }


def coding(stem, function_name, starter, tests, explanation, st, difficulty="easy"):
    """tests: [(args, expected, hidden)]"""
    return {
        "qtype": "coding",
        "stem": stem,
        "payload": {
            "language": "python",
            "function_name": function_name,
            "starter_code": starter,
            "tests": [{"args": list(a), "expected": e, "hidden": h} for a, e, h in tests],
        },
        "explanation": explanation,
        "difficulty": difficulty,
        "steps": st,
    }


def speaking(sentence, translation="", language="en-US", difficulty="easy"):
    return {"qtype": "speaking", "stem": "Read this sentence aloud clearly.", "payload": {"sentence": sentence, "language": language, "translation": translation}, "explanation": "", "difficulty": difficulty, "steps": {}}
