"""Exam syllabi kept as data (YAML), one directory per course under `data/`.

`python -m app.seed` loads them after the Python seed courses; `python -m app.seed.syllabus`
validates them and prints what they contain. See `schema` for the file format.
"""

from functools import lru_cache
from pathlib import Path

from app.seed.syllabus.reader import Syllabus, SyllabusError, read

DATA_DIR = Path(__file__).resolve().parent / "data"
ALL_SYLLABI = ("ssc-cgl",)

__all__ = ["ALL_SYLLABI", "DATA_DIR", "Syllabus", "SyllabusError", "exam_profile", "external_concepts", "load_syllabus_file"]


def external_concepts() -> set[str]:
    """Concept slugs defined by the Python seed courses (what `ref:` may point at)."""
    from app.seed.courses import ALL_COURSES

    return {slug for m in ALL_COURSES for slug in m.CONCEPTS}


@lru_cache
def load_syllabus_file(name: str) -> Syllabus:
    return read(DATA_DIR / name, external_concepts())


def exam_profile(name: str, slug: str) -> dict:
    """One exam profile of a syllabus as a seed `exam` dict (single source for Python courses
    that prepare for the same exam stage)."""
    from app.seed.syllabus.reader import ExamProfilesFile, _parse

    profiles: ExamProfilesFile = _parse(ExamProfilesFile, DATA_DIR / name / "exam_profiles.yaml")
    for p in profiles.profiles:
        if p.slug == slug:
            return {"slug": p.slug, "name": p.name, "body": p.body, "domain": p.domain, "pattern": profile_pattern(p)}
    raise SyllabusError(f"{name}: no exam profile {slug!r}")


def profile_pattern(p) -> dict:
    """What is stored in `exam_profiles.pattern` (the mock builder and the web read it). Empty
    optional fields are left out so the stored pattern stays readable."""
    pattern = p.pattern.model_dump(exclude_none=True)
    pattern["sections"] = [{k: v for k, v in s.items() if v not in ("", False)} for s in pattern["sections"]]
    pattern["components"] = [{k: v for k, v in c.items() if v != ""} for c in pattern["components"]]
    return {"stage": p.stage, **pattern}
