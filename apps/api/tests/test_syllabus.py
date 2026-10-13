"""The syllabus file format, its validation, and the completeness of the SSC CGL syllabus."""

import re
import shutil
from pathlib import Path

import pytest
import yaml

from app.seed.courses import ssc_quant
from app.seed.syllabus import DATA_DIR, SyllabusError, exam_profile, external_concepts, load_syllabus_file
from app.seed.syllabus.reader import read

SSC = DATA_DIR / "ssc-cgl"


@pytest.fixture(scope="module")
def ssc():
    return load_syllabus_file("ssc-cgl")


# --------------------------------------------------------------------------- exam profiles


def test_tier1_pattern_matches_the_notice(ssc):
    p = {x.slug: x for x in ssc.profiles.profiles}["ssc-cgl-tier1"].pattern
    assert [s.questions for s in p.sections] == [25, 25, 25, 25]
    assert sum(s.marks for s in p.sections) == 200
    assert (p.marks_per_question, p.negative_marks, p.duration_minutes) == (2, 0.5, 60)
    assert {s.subject for s in p.sections} == {"quant", "reasoning", "english", "general-awareness"}


def test_tier2_pattern_matches_the_notice(ssc):
    p = {x.slug: x for x in ssc.profiles.profiles}["ssc-cgl-tier2"].pattern
    by_subject = {s.subject: s for s in p.sections}
    assert {k: v.questions for k, v in by_subject.items()} == {"quant": 30, "reasoning": 30, "english": 45, "general-awareness": 25, "computer": 20}
    assert sum(s.marks for s in p.sections) == 450  # 150 questions × 3
    assert (p.marks_per_question, p.negative_marks) == (3, 1)
    assert by_subject["computer"].qualifying and by_subject["computer"].duration_minutes == 15
    assert [c.name for c in p.components] == ["Data Entry Speed Test"]


def test_the_arithmetic_course_shares_the_tier1_profile():
    assert ssc_quant.EXAM == exam_profile("ssc-cgl", "ssc-cgl-tier1")
    assert ssc_quant.EXAM["pattern"]["negative_marks"] == 0.5 and ssc_quant.EXAM["pattern"]["default_section"] == "Quantitative Aptitude"


# --------------------------------------------------------------------------- the SSC CGL syllabus


def test_course_settings(ssc):
    c = ssc.course
    assert (c.slug, c.status, c.content_policy, c.authored_status) == ("ssc-cgl", "draft", "reviewed_only", "in_review")
    assert c.exams == ["ssc-cgl-tier1", "ssc-cgl-tier2"]
    assert c.subjects == ["quant", "reasoning", "english", "general-awareness", "computer"]


def test_every_subject_is_expanded_to_concepts(ssc):
    counts = ssc.counts()
    minimum = {"quant": 150, "reasoning": 80, "english": 90, "general-awareness": 200, "computer": 40}
    for subject, n in minimum.items():
        assert counts[subject]["concepts"] >= n, (subject, counts[subject])
        assert counts[subject]["patterns"] >= counts[subject]["concepts"], subject  # at least one exam pattern per concept on average
    assert counts["quant"]["formulas"] >= counts["quant"]["concepts"]  # the formula sheet is authored
    assert sum(r["concepts"] for r in counts.values()) >= 650


def test_every_concept_has_a_summary_and_sits_in_one_subject(ssc):
    for slug, c in ssc.defined.items():
        assert len(c.summary) >= 40, slug
        assert c.title.strip(), slug
    for p in ssc.placements:
        assert p.node_key.count(".") >= 2, p  # under a topic or sub topic, never directly under a chapter


def test_computer_knowledge_is_tier2_only(ssc):
    for n in ssc.nodes:
        if n.key.startswith("computer"):
            assert n.tiers == ["tier2"], n.key
    assert all(p.tiers == ["tier2"] for p in ssc.placements if p.node_key.startswith("computer."))


def test_existing_concepts_are_reused_not_redefined(ssc):
    assert {"percentage-basics", "percentage-change", "successive-percentage", "profit-loss", "discount", "simple-interest", "compound-interest"} <= ssc.refs
    assert not set(ssc.defined) & external_concepts()


# The course owner's list. Each item must appear in that subject as a node, concept or pattern title.
REQUIRED = {
    "quant": [
        "natural numbers",
        "whole numbers",
        "integers",
        "rational numbers",
        "irrational numbers",
        "divisibility",
        "factors",
        "multiples",
        "prime",
        "composite",
        "hcf",
        "lcm",
        "number of factors",
        "sum of factors",
        "remainder",
        "unit digit",
        "last two digit",
        "cyclicity",
        "simplification",
        "bodmas",
        "conversion",
        "successive",
        "comparison",
        "reverse percentage",
        "marks",
        "pass marks",
        "election",
        "votes",
        "invalid votes",
        "population",
        "income",
        "savings",
        "expenditure",
        "equivalent",
        "cost price",
        "selling price",
        "marked price",
        "profit",
        "loss",
        "discount",
        "successive discount",
        "false weight",
        "dishonest",
        "simple interest",
        "compound interest",
        "difference",
        "half-yearly|half yearly",
        "quarterly",
        "variable rate",
        "growth",
        "ratio",
        "equivalent ratio",
        "partnership",
        "mixture",
        "age",
        "direct proportion",
        "inverse proportion",
        "average",
        "weighted average",
        "replacement",
        "efficiency",
        "combined work",
        "lcm method",
        "pipes",
        "cistern",
        "alternate",
        "wages",
        "relative speed",
        "train",
        "boats",
        "stream",
        "race",
        "average speed",
        "circular",
        "identities",
        "linear equation",
        "quadratic",
        "algebraic expression",
        "lines",
        "angles",
        "triangle",
        "similar",
        "congruen",
        "circle",
        "quadrilateral",
        "polygon",
        "theorem",
        "square",
        "rectangle",
        "sector",
        "cube",
        "cuboid",
        "cylinder",
        "cone",
        "sphere",
        "hemisphere",
        "trigonometric ratio",
        "identit",
        "heights and distances",
        "table",
        "bar",
        "pie chart",
        "line graph",
        "caselet",
    ],
    "reasoning": [
        "analogy",
        "classification",
        "number series",
        "alphabet series",
        "coding",
        "blood relation",
        "direction",
        "ranking",
        "order",
        "venn diagram",
        "syllogism",
        "conclusion",
        "assumption",
        "calendar",
        "clock",
        "mathematical operation",
        "non-verbal|non verbal",
        "mirror image",
        "water image",
        "paper folding",
        "embedded figure",
        "figure counting|counting of figures",
    ],
    "english": [
        "parts of speech",
        "tense",
        "voice",
        "narration|direct and indirect speech",
        "subject-verb agreement|subject verb agreement",
        "article",
        "preposition",
        "conjunction",
        "synonym",
        "antonym",
        "one word substitution|one-word substitution",
        "idiom",
        "phrase",
        "spelling",
        "error spotting|spot the error",
        "fill in the blank",
        "cloze",
        "sentence improvement|improvement of sentences",
        "reading comprehension|comprehension passage",
    ],
    "general-awareness": [
        "ancient",
        "medieval",
        "modern",
        "freedom",
        "physical geography",
        "indian geography|india",
        "climate",
        "resources",
        "constitution",
        "fundamental rights",
        "parliament",
        "judiciary|supreme court",
        "president",
        "prime minister",
        "governance|local government",
        "banking",
        "inflation",
        "budget",
        "econom",
        "physics",
        "chemistry",
        "biology",
        "current affairs",
    ],
    "computer": [
        "memory",
        "input",
        "output",
        "operating system",
        "word",
        "excel",
        "powerpoint",
        "internet",
        "e-mail|email",
        "network",
        "security",
        "virus",
    ],
}


def _titles(ssc, subject: str) -> list[str]:
    titles = [n.title for n in ssc.nodes if n.key.split(".")[0] == subject]
    for slug, c in ssc.concepts.items():
        if c.subject == subject:
            titles.append(c.spec.title if c.spec else slug.replace("-", " "))
            titles += [p.title for p, _ in c.patterns]
    return [t.lower() for t in titles]


@pytest.mark.parametrize("subject", sorted(REQUIRED))
def test_the_owners_topic_list_is_covered(ssc, subject):
    titles = _titles(ssc, subject)
    missing = [term for term in REQUIRED[subject] if not any(re.search(term, t) for t in titles)]
    assert not missing, f"{subject}: no node, concept or pattern title mentions {missing}"


# --------------------------------------------------------------------------- validation


@pytest.fixture
def mini(tmp_path) -> Path:
    """A small valid syllabus to break in different ways."""
    root = tmp_path / "mini"
    shutil.copytree(SSC, root, ignore=shutil.ignore_patterns("*.yaml"))
    for sub in ("reasoning", "english", "general-awareness", "computer"):
        shutil.rmtree(root / sub)
    shutil.copy(SSC / "exam_profiles.yaml", root / "exam_profiles.yaml")
    course = yaml.safe_load((SSC / "course.yaml").read_text())
    course.update(subjects=["quant"], content_requirements={"default": course["content_requirements"]["default"]})
    (root / "course.yaml").write_text(yaml.safe_dump(course))
    profiles = yaml.safe_load((SSC / "exam_profiles.yaml").read_text())
    for p in profiles["profiles"]:
        for s in p["pattern"]["sections"]:
            s["subject"] = "quant"
    (root / "exam_profiles.yaml").write_text(yaml.safe_dump(profiles))
    (root / "quant").mkdir(exist_ok=True)
    subject = {"key": "quant", "title": "Quant", "tiers": ["tier1", "tier2"], "chapters": ["basics"]}
    (root / "quant" / "subject.yaml").write_text(yaml.safe_dump(subject))
    write_chapter(root, _chapter())
    return root


def _chapter(**concept) -> dict:
    base = {"slug": "mini-ratio", "title": "Ratio", "summary": "A ratio compares two quantities of the same kind by division."}
    return {
        "key": "basics",
        "title": "Basics",
        "topics": [
            {
                "key": "ratio",
                "title": "Ratio",
                "concepts": [
                    {**base, **concept},
                    {"slug": "mini-proportion", "title": "Proportion", "summary": "Two equal ratios form a proportion: a:b = c:d."},
                ],
            }
        ],
    }


def write_chapter(root: Path, chapter: dict) -> None:
    (root / "quant" / f"{chapter['key']}.yaml").write_text(yaml.safe_dump(chapter, sort_keys=False))


def test_the_mini_syllabus_is_valid(mini):
    syl = read(mini, external_concepts())
    assert set(syl.defined) == {"mini-ratio", "mini-proportion"}
    assert [n.key for n in syl.nodes] == ["quant", "quant.basics", "quant.basics.ratio"]


@pytest.mark.parametrize(
    ("concept", "message"),
    [
        ({"prerequisites": ["nope"]}, "unknown prerequisite"),
        ({"prerequisites": ["mini-ratio"]}, "itself"),
        ({"tiers": ["tier3"]}, "unknown tiers"),
        ({"colour": "red"}, "Extra inputs are not permitted"),
        ({"slug": "percentage-basics"}, "another seed course already defines it"),
        ({"shortcuts": [{"key": "s", "title": "S", "rule": "r", "pattern": "missing"}]}, "unknown pattern"),
        ({"formulas": [{"key": "f", "name": "F", "expression": "a"}, {"key": "f", "name": "G", "expression": "b"}]}, "duplicate key"),
        ({"summary": ""}, "title and summary are required"),
    ],
)
def test_invalid_concepts_are_rejected(mini, concept, message):
    write_chapter(mini, _chapter(**concept))
    with pytest.raises(SyllabusError, match=message):
        read(mini, external_concepts())


def test_prerequisite_cycles_are_rejected(mini):
    chapter = _chapter(prerequisites=["mini-proportion"])
    chapter["topics"][0]["concepts"][1]["prerequisites"] = ["mini-ratio"]
    write_chapter(mini, chapter)
    with pytest.raises(SyllabusError, match="prerequisite cycle"):
        read(mini, external_concepts())


def test_a_concept_defined_twice_must_use_ref(mini):
    chapter = _chapter()
    chapter["topics"].append(
        {
            "key": "again",
            "title": "Again",
            "concepts": [{"slug": "mini-ratio", "title": "Ratio", "summary": "Defined a second time by mistake, which is refused."}],
        }
    )
    write_chapter(mini, chapter)
    with pytest.raises(SyllabusError, match="defined twice"):
        read(mini, external_concepts())
    chapter["topics"][1]["concepts"] = [{"ref": "mini-ratio"}]
    write_chapter(mini, chapter)
    assert len([p for p in read(mini, external_concepts()).placements if p.concept == "mini-ratio"]) == 2


def test_tiers_only_narrow_down_the_tree(mini):
    subject = yaml.safe_load((mini / "quant" / "subject.yaml").read_text())
    subject["tiers"] = ["tier1"]
    (mini / "quant" / "subject.yaml").write_text(yaml.safe_dump(subject))
    write_chapter(mini, _chapter(tiers=["tier2"]))
    with pytest.raises(SyllabusError, match="not within its parent"):
        read(mini, external_concepts())


def test_forgotten_and_missing_chapter_files_are_reported(mini):
    (mini / "quant" / "extra.yaml").write_text("key: extra\n")
    with pytest.raises(SyllabusError, match="not listed in subject.yaml"):
        read(mini, external_concepts())
    (mini / "quant" / "extra.yaml").unlink()
    (mini / "quant" / "basics.yaml").unlink()
    with pytest.raises(SyllabusError, match="file not found"):
        read(mini, external_concepts())
    warnings: list[str] = []
    read(mini, external_concepts(), partial=warnings)
    assert any("file not found" in w for w in warnings)


def test_exam_patterns_must_add_up(mini):
    profiles = yaml.safe_load((mini / "exam_profiles.yaml").read_text())
    profiles["profiles"][0]["pattern"]["sections"][0]["marks"] = 49
    (mini / "exam_profiles.yaml").write_text(yaml.safe_dump(profiles))
    with pytest.raises(SyllabusError, match=r"25 questions × 2.0 marks is not 49"):
        read(mini, external_concepts())


def test_the_cli_validates_and_reports_counts(capsys):
    from app.seed.syllabus.__main__ import main

    assert main(["ssc-cgl"]) == 0
    out = capsys.readouterr().out
    assert "ssc-cgl: ok" in out and "general-awareness" in out
