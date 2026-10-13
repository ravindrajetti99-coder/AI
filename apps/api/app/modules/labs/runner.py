"""Code execution for the programming lab.

`local`  : Python in a subprocess with CPU/memory/file-size limits, no inherited environment,
           isolated temp dir, and no network when `unshare` is available. For development only.
`judge0` : sends the same harness to an isolated Judge0 service (production).
"""

import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from app.core.config import get_settings

# The child only calls the learner's function and reports what it returned; it never sees the
# expected values. Learner code shares the interpreter with the harness, so it could forge a
# report, but without the expected values a forged report is no better than solving the task.
HARNESS = r"""
import io, json, sys, contextlib, traceback
NONCE = "__NONCE__"
SPEC = json.loads(__SPEC__)
ns = {"__name__": "learner"}
out = {"compile_error": None, "results": []}
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        exec(compile(SPEC["code"], "solution.py", "exec"), ns)
except Exception as e:
    out["compile_error"] = "".join(traceback.format_exception_only(type(e), e)).strip()
fn = ns.get(SPEC["function_name"]) if not out["compile_error"] else None
if not out["compile_error"] and not callable(fn):
    out["compile_error"] = "Function %s was not defined" % SPEC["function_name"]
for args in SPEC["args"] if fn else []:
    rec = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            got = fn(*args)
        if isinstance(got, tuple):
            got = list(got)
        rec["got"] = got if isinstance(got, (int, float, str, bool, list, dict, type(None))) else repr(got)
    except Exception as e:
        rec["error"] = "".join(traceback.format_exception_only(type(e), e)).strip()
    out["results"].append(rec)
out["stdout"] = buf.getvalue()[:2000]
sys.__stdout__.write(NONCE + json.dumps(out, default=repr) + NONCE)
"""


def matches(got, expected) -> bool:
    """Compare a returned value with the expected one: floats within 1e-6, bools never equal ints."""
    if isinstance(expected, bool) or isinstance(got, bool):
        return type(got) is type(expected) and got == expected
    if isinstance(expected, float) or isinstance(got, float):
        return isinstance(got, (int, float)) and isinstance(expected, (int, float)) and math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-6)
    if isinstance(expected, list):
        return isinstance(got, list) and len(got) == len(expected) and all(matches(g, e) for g, e in zip(got, expected, strict=True))
    if isinstance(expected, dict):
        return isinstance(got, dict) and got.keys() == expected.keys() and all(matches(got[k], expected[k]) for k in expected)
    return got == expected


@dataclass
class RunResult:
    ok: bool
    passed: int = 0
    total: int = 0
    results: list = field(default_factory=list)
    error: str = ""
    stdout: str = ""
    timed_out: bool = False

    def summary(self) -> str:
        if self.error:
            return f"error: {self.error}"
        return f"passed {self.passed} of {self.total}, failed {self.total - self.passed}" + (
            " (all passed)" if self.total and self.passed == self.total else ""
        )

    def public(self) -> dict:
        """Hide arguments/expected values of hidden tests from the learner."""
        shown = []
        for r in self.results:
            if r.get("hidden"):
                shown.append({"hidden": True, "passed": r.get("passed", False), "error": r.get("error", "")[:200] if not r.get("passed") else ""})
            else:
                shown.append(r)
        return {
            "ok": self.ok,
            "passed": self.passed,
            "total": self.total,
            "results": shown,
            "error": self.error,
            "stdout": self.stdout,
            "timed_out": self.timed_out,
        }


def _build(code: str, function_name: str, tests: list[dict]) -> tuple[str, str]:
    nonce = secrets.token_hex(12)
    spec = json.dumps({"code": code, "function_name": function_name, "args": [t["args"] for t in tests]})
    return HARNESS.replace("__NONCE__", nonce).replace("__SPEC__", repr(spec)), nonce


def _parse(stdout: str, nonce: str) -> dict | None:
    parts = stdout.split(nonce)
    if len(parts) < 3:
        return None
    try:
        return json.loads(parts[-2])
    except json.JSONDecodeError:
        return None


def _limits():  # runs in the child before exec (POSIX only)
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    os.setsid()


def run_python(code: str, function_name: str, tests: list[dict]) -> RunResult:
    s = get_settings()
    if s.code_runner == "disabled":
        return RunResult(ok=False, error="Code execution is disabled on this server")
    if len(code) > 20_000:
        return RunResult(ok=False, error="Code is too long (20,000 characters max)")
    script, nonce = _build(code, function_name, tests)
    if s.code_runner == "judge0":
        return _run_judge0(script, nonce, tests)
    with tempfile.TemporaryDirectory(prefix="edu-run-") as tmp:
        path = os.path.join(tmp, "harness.py")
        with open(path, "w") as f:
            f.write(script)
        cmd = [sys.executable, "-I", "-S", path]
        if shutil.which("unshare") and _unshare_works():
            cmd = ["unshare", "-rn", *cmd]  # private, empty network namespace
        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=s.code_timeout_seconds,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                preexec_fn=_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return RunResult(ok=False, total=len(tests), error=f"Time limit exceeded ({s.code_timeout_seconds}s)", timed_out=True)
    data = _parse(proc.stdout, nonce)
    if data is None:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["Program crashed or used too much memory"]
        return RunResult(ok=False, total=len(tests), error=err[0][:300])
    return _from_data(data, tests)


def _from_data(data: dict, tests: list[dict]) -> RunResult:
    if data.get("compile_error"):
        return RunResult(ok=False, total=len(tests), error=data["compile_error"], stdout=data.get("stdout", ""))
    reported = data.get("results") or []
    results = []
    for i, t in enumerate(tests):
        rec = {"args": t["args"], "expected": t["expected"], "hidden": t.get("hidden", False)}
        got = reported[i] if i < len(reported) and isinstance(reported[i], dict) else {"error": "No result reported"}
        if "error" in got:
            rec["passed"], rec["error"] = False, str(got["error"])
        else:
            rec["got"] = got.get("got")
            rec["passed"] = matches(rec["got"], t["expected"])
        results.append(rec)
    passed = sum(1 for r in results if r["passed"])
    return RunResult(ok=True, passed=passed, total=len(results), results=results, stdout=str(data.get("stdout", ""))[:2000])


_UNSHARE_OK: bool | None = None


def _unshare_works() -> bool:
    global _UNSHARE_OK
    if _UNSHARE_OK is None:
        try:
            _UNSHARE_OK = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=3).returncode == 0
        except Exception:
            _UNSHARE_OK = False
    return _UNSHARE_OK


def _run_judge0(script: str, nonce: str, tests: list[dict]) -> RunResult:
    import httpx

    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.judge0_url.rstrip('/')}/submissions?wait=true",
            json={"source_code": script, "language_id": 71, "cpu_time_limit": s.code_timeout_seconds, "memory_limit": 256000, "enable_network": False},
            timeout=s.code_timeout_seconds + 15,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return RunResult(ok=False, total=len(tests), error=f"Runner unavailable: {exc}")
    data = _parse(body.get("stdout") or "", nonce)
    if data is None:
        return RunResult(ok=False, total=len(tests), error=(body.get("stderr") or body.get("status", {}).get("description") or "Run failed")[:300])
    return _from_data(data, tests)
