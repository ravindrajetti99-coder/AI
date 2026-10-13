"""AI Code Review: quality, performance, security and optimisation feedback."""

import ast

from app.ai import gateway
from app.ai.schemas import CodeReviewOut

PROMPT_VERSION = "codereview-v1"


def review_task(code: str, language: str, problem: str, test_summary: str = "") -> gateway.Task:
    system = (
        "You are a senior engineer reviewing a learner's code. Give a 0-10 score and specific findings in the categories "
        "correctness, quality, performance, security and style, each with a line number when possible and a concrete "
        "suggestion. Teach, don't just judge: explain why. Keep it to the 3-8 most useful findings."
    )
    user = f"Language: {language}\nProblem: {problem}\nTest results: {test_summary}\n\n<code>\n{code[:12000]}\n</code>"
    return gateway.Task(
        name="code.review",
        prompt_version=PROMPT_VERSION,
        tier="standard",
        system=system,
        user=user,
        schema=CodeReviewOut,
        offline=lambda: offline_review(code, language, test_summary),
        max_tokens=1800,
    )


DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
DANGEROUS_MODULES = {"os", "subprocess", "pickle", "shelve", "marshal"}


def offline_review(code: str, language: str, test_summary: str = "") -> dict:
    if language != "python":
        return {"score": 5.0, "summary": "Static review is available for Python; connect an AI provider to review other languages.", "findings": []}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "score": 1.0,
            "summary": "The code does not parse.",
            "findings": [
                {
                    "category": "correctness",
                    "severity": "error",
                    "line": exc.lineno,
                    "message": f"Syntax error: {exc.msg}",
                    "suggestion": "Fix the syntax before running tests.",
                }
            ],
        }
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(
                {
                    "category": "quality",
                    "severity": "warning",
                    "line": node.lineno,
                    "message": "Bare `except:` hides every error, including typos.",
                    "suggestion": "Catch the specific exception you expect, e.g. `except ValueError:`.",
                }
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALLS:
            findings.append(
                {
                    "category": "security",
                    "severity": "error",
                    "line": node.lineno,
                    "message": f"`{node.func.id}()` executes arbitrary code.",
                    "suggestion": "Parse input explicitly (int(), json.loads()) instead.",
                }
            )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
            for n in names:
                if n in DANGEROUS_MODULES:
                    findings.append(
                        {
                            "category": "security",
                            "severity": "warning",
                            "line": node.lineno,
                            "message": f"Module `{n}` can touch the system or deserialize untrusted data.",
                            "suggestion": "Avoid it unless the task needs it; never unpickle untrusted input.",
                        }
                    )
        if isinstance(node, (ast.For, ast.While)):
            inner = [n for n in ast.walk(node) if isinstance(n, (ast.For, ast.While)) and n is not node]
            if inner:
                findings.append(
                    {
                        "category": "performance",
                        "severity": "info",
                        "line": node.lineno,
                        "message": "Nested loops: O(n^2) or worse.",
                        "suggestion": "Check whether a set/dict lookup or sorting removes the inner loop.",
                    }
                )
        if isinstance(node, ast.FunctionDef):
            if not ast.get_docstring(node) and len(node.body) > 5:
                findings.append(
                    {
                        "category": "style",
                        "severity": "info",
                        "line": node.lineno,
                        "message": f"`{node.name}` has no docstring.",
                        "suggestion": "Add one line saying what it returns.",
                    }
                )
            for arg in node.args.defaults:
                if isinstance(arg, (ast.List, ast.Dict, ast.Set)):
                    findings.append(
                        {
                            "category": "correctness",
                            "severity": "warning",
                            "line": node.lineno,
                            "message": "Mutable default argument is shared between calls.",
                            "suggestion": "Use `None` and create the list/dict inside the function.",
                        }
                    )
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            if any(isinstance(c, ast.Constant) and isinstance(c.value, (int, str)) for c in node.comparators):
                findings.append(
                    {
                        "category": "correctness",
                        "severity": "warning",
                        "line": node.lineno,
                        "message": "`is` compares identity, not value.",
                        "suggestion": "Use `==` for numbers and strings.",
                    }
                )
        if isinstance(node, ast.Name) and node.id in {"list", "dict", "str", "id", "sum", "max", "min"} and isinstance(node.ctx, ast.Store):
            findings.append(
                {
                    "category": "style",
                    "severity": "info",
                    "line": node.lineno,
                    "message": f"Variable `{node.id}` shadows a built-in.",
                    "suggestion": "Pick a descriptive name, e.g. `numbers`.",
                }
            )
    for name in ("range(len(",):
        for i, line in enumerate(code.splitlines(), 1):
            if name in line:
                findings.append(
                    {
                        "category": "style",
                        "severity": "info",
                        "line": i,
                        "message": "`range(len(x))` indexing.",
                        "suggestion": "Iterate directly, or use `enumerate(x)` when you need the index.",
                    }
                )
                break
    passed_all = "failed 0" in test_summary or (test_summary and "all passed" in test_summary)
    penalty = sum({"error": 2.5, "warning": 1.0, "info": 0.3}[f["severity"]] for f in findings)
    score = max(0.0, min(10.0, (9.0 if passed_all else 6.0) - penalty + (1.0 if not findings else 0.0)))
    summary = "Clean code; no static issues found." if not findings else f"{len(findings)} things to improve, most important first."
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    return {"score": round(score, 1), "summary": summary, "findings": findings[:10]}
