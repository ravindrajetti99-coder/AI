"""Grading of coding, speaking, descriptive and interview answers (offline engines) and the code runner."""

import pytest
from conftest import API

from app.ai.engines import code_review, examiner
from app.modules.labs import runner
from app.modules.labs.runner import run_python

TESTS = [{"args": [2, 3], "expected": 5}, {"args": [10, -4], "expected": 6, "hidden": True}]


def test_runner_passes_fails_and_hides_hidden_tests():
    ok = run_python("def add(a, b):\n    return a + b\n", "add", TESTS)
    assert (ok.ok, ok.passed, ok.total) == (True, 2, 2) and ok.summary().endswith("(all passed)")
    bad = run_python("def add(a, b):\n    return a - b\n", "add", TESTS)
    assert (bad.passed, bad.total) == (0, 2)
    public = bad.public()["results"]
    assert public[0]["expected"] == 5 and public[0]["got"] == -1
    assert public[1] == {"hidden": True, "passed": False, "error": ""}  # no args, expected or output leak


def test_runner_reports_errors():
    assert "SyntaxError" in run_python("def add(a, b)\n    return a", "add", TESTS).error
    assert run_python("def plus(a, b):\n    return a + b", "add", TESTS).error == "Function add was not defined"
    crash = run_python("def add(a, b):\n    return a / 0", "add", TESTS)
    assert crash.ok and crash.passed == 0 and "ZeroDivisionError" in crash.results[0]["error"]
    printed = run_python("print('hello')\ndef add(a, b):\n    return a + b", "add", TESTS)
    assert printed.stdout == "hello\n" and printed.passed == 2


def test_runner_stops_infinite_loops_and_memory_hogs():
    loop = run_python("def add(a, b):\n    while True:\n        pass", "add", TESTS)
    assert loop.ok is False and (loop.timed_out or loop.error)
    hog = run_python("def add(a, b):\n    x = 'a' * (2 * 1024 ** 3)\n    return 0", "add", TESTS)
    assert hog.passed == 0


def test_runner_has_no_network_when_namespaces_are_available():
    if not runner._unshare_works():
        pytest.skip("user namespaces unavailable here; production uses Judge0")
    code = "def add(a, b):\n    import socket\n    socket.create_connection(('1.1.1.1', 53), timeout=1)\n    return a + b"
    assert run_python(code, "add", TESTS).passed == 0


def test_runner_can_be_disabled(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "code_runner", "disabled")
    assert run_python("def add(a, b): return a + b", "add", TESTS).error == "Code execution is disabled on this server"


def test_code_run_endpoint_uses_visible_tests_only(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "python-functions", "types": "coding"}).json()["question"]
    solution = "def is_palindrome(text):\n    s = text.lower().replace(' ', '')\n    return s == s[::-1]\n"
    if q["payload"]["function_name"] != "is_palindrome":
        pytest.skip("adaptive pick chose another coding question")
    r = learner.post(f"{API}/code/run", json={"question_id": q["id"], "code": solution}).json()
    assert r["total"] == len(q["payload"]["examples"]) and r["passed"] == r["total"]


def test_coding_attempt_runs_hidden_tests_and_reviews_the_code(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "python-conditionals", "types": "coding"}).json()["question"]
    fn = q["payload"]["function_name"]
    code = {
        "grade": "def grade(marks):\n    if marks >= 60:\n        return 'First'\n    elif marks >= 50:\n        return 'Second'\n    elif marks >= 35:\n        return 'Pass'\n    return 'Fail'\n",
        "is_leap": "def is_leap(year):\n    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0\n",
    }[fn]
    body = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": {"code": code}}).json()
    assert body["is_correct"] and body["score"] == 1.0
    assert body["feedback"]["review_source"] == "offline" and body["feedback"]["review"]["score"] >= 9
    off_by_one = code.replace(">= 60", "> 60").replace("% 400 == 0", "% 400 == 1")
    worse = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": {"code": off_by_one}}).json()
    assert not worse["is_correct"] and worse["score"] < 1.0


def test_speaking_attempt(learner):
    items = learner.get(f"{API}/language/speaking", params={"language": "en-IN"}).json()
    assert items and all(i["qtype"] == "speaking" for i in items)
    item = next(i for i in items if i["payload"]["sentence"].startswith("Yesterday I went"))
    good = learner.post(
        f"{API}/attempts", json={"question_id": item["id"], "response": {"transcript": "yesterday I went to the market and bought vegetables"}}
    ).json()
    assert good["is_correct"] and good["feedback"]["accuracy"] == 1.0
    poor = learner.post(f"{API}/attempts", json={"question_id": item["id"], "response": {"transcript": "yesterday I go to market"}}).json()
    assert not poor["is_correct"] and "bought" in poor["feedback"]["missed"]


def test_interview_answers_are_scored_against_the_rubric(learner):
    q = learner.get(f"{API}/practice/next", params={"concept": "python-functions", "types": "interview"}).json()["question"]
    strong = (
        "A list is mutable, so it can be changed after creation, while a tuple is immutable and cannot be changed.\n\n"
        "Use tuples for fixed records or as dictionary keys, and use lists for collections that grow or change.\n\n"
        "Lists use square brackets and tuples use parentheses; tuples are slightly faster and use less memory. Therefore choose by mutability."
    )
    weak = "Both store items. I use lists mostly."
    good = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": {"text": strong}}).json()
    bad = learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": {"text": weak}}).json()
    assert good["feedback"]["evaluated_by"] == "offline"
    ev = good["feedback"]["evaluation"]
    assert ev["max_total"] == 10 and ev["total"] >= 8 and good["is_correct"]
    assert bad["score"] < 0.3 and bad["feedback"]["evaluation"]["missing_points"]
    assert learner.post(f"{API}/attempts", json={"question_id": q["id"], "response": {"text": "   "}}).status_code == 400


def test_offline_examiner_scores_in_half_marks_and_flags_presentation():
    rubric = [{"criterion": "Definition", "max_marks": 2, "expected_points": ["depreciation allocates the cost of an asset over its useful life"]}]
    full = examiner.offline_evaluate(rubric, "", "Depreciation allocates the cost of an asset over its useful life.")
    assert full["total"] == 2 and full["criteria"][0]["awarded"] == 2
    none = examiner.offline_evaluate(rubric, "", "It is about money.")
    assert none["total"] == 0 and none["missing_points"] and "very short" in none["presentation_feedback"]
    long = examiner.offline_evaluate(rubric, "", "word " * 300, word_limit=100)
    assert "Over the word limit" in long["presentation_feedback"]


def test_offline_code_review_findings():
    code = "def f(items=[]):\n    try:\n        x = eval(input())\n    except:\n        pass\n    for i in range(len(items)):\n        for j in items:\n            if i is 1:\n                list = []\n    return items\n"
    review = code_review.offline_review(code, "python", "passed 1 of 2, failed 1")
    categories = {(f["category"], f["severity"]) for f in review["findings"]}
    assert ("security", "error") in categories and ("quality", "warning") in categories
    assert ("correctness", "warning") in categories and ("performance", "info") in categories
    assert review["findings"][0]["severity"] == "error"  # most important first
    assert review["score"] < 5
    assert code_review.offline_review("def f(:", "python")["findings"][0]["message"].startswith("Syntax error")
    assert code_review.offline_review("x", "java")["findings"] == []


def test_learner_code_cannot_forge_a_passing_report():
    """The child never learns hidden expected values, so a forged report still fails them."""
    forge = (
        "import sys, json, os\n"
        "nonce = sys.modules['__main__'].NONCE\n"
        "fake = {'compile_error': None, 'results': [{'got': 5}, {'got': 5}], 'stdout': ''}\n"
        "sys.__stdout__.write(nonce + json.dumps(fake) + nonce)\n"
        "sys.__stdout__.flush()\n"
        "os._exit(0)\n"
    )
    r = run_python(forge, "add", TESTS)
    assert (r.passed, r.total) == (1, 2)  # the visible example can be hard-coded, the hidden one cannot
    assert "expected" not in __import__("json").dumps(runner._build("x", "add", TESTS)[0].split("SPEC = json.loads(")[1].split(")\n")[0])


def test_result_comparison_rules():
    assert runner.matches(98.60000000000001, 98.6) and runner.matches(3, 3.0)
    assert not runner.matches(1, True) and not runner.matches(True, 1)
    assert runner.matches([0.1 + 0.2, "a"], [0.3, "a"]) and not runner.matches([1, 2], [1, 2, 3])
    assert runner.matches({"go": 3}, {"go": 3}) and not runner.matches({"go": 3}, {"GO": 3})
