"""Read a syllabus directory, validate it as a whole and flatten it for the loader.

File-level shape is checked by the Pydantic models in `schema`; this module checks what spans
files: every exam, subject, chapter and concept reference resolves, tiers only narrow going
down the tree, keys fit their columns, prerequisites have no cycles and no file is forgotten.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.seed.syllabus.schema import (
    ChapterSpec,
    ConceptSpec,
    CourseFile,
    ExamProfilesFile,
    FormulaSpec,
    PatternQSpec,
    Requirements,
    ShortcutSpec,
    StrategySpec,
    SubjectSpec,
)

NODE_KEY_MAX = 120
CONTENT_KEY_MAX = 160


class SyllabusError(Exception):
    pass


@dataclass
class NodeRow:
    key: str  # dotted path, unique within the course
    parent_key: str | None
    node_type: str  # subject | chapter | topic | subtopic
    title: str
    position: int
    tiers: list[str]


@dataclass
class Placement:
    node_key: str
    concept: str  # slug
    weight: float
    position: int
    tiers: list[str]


@dataclass
class ConceptContent:
    """Everything the syllabus says about one concept, gathered from all of its placements."""

    slug: str
    spec: ConceptSpec | None = None  # the defining entry (None: defined by another course)
    subject: str = ""  # where it is defined (or first placed): requirements come from here
    chapter: str = ""
    tiers: list[str] = field(default_factory=list)  # union over placements
    formulas: list[FormulaSpec] = field(default_factory=list)
    patterns: list[tuple[PatternQSpec, list[str]]] = field(default_factory=list)  # with effective tiers
    shortcuts: list[ShortcutSpec] = field(default_factory=list)


@dataclass
class StrategyRow:
    key: str
    node_key: str | None
    spec: StrategySpec


@dataclass
class Syllabus:
    path: Path
    course: CourseFile
    profiles: ExamProfilesFile
    subjects: list[SubjectSpec]
    chapters: dict[str, list[ChapterSpec]]  # subject key -> chapters in order
    nodes: list[NodeRow]
    placements: list[Placement]
    concepts: dict[str, ConceptContent]  # every concept placed in the course, by slug
    strategies: list[StrategyRow]

    @property
    def defined(self) -> dict[str, ConceptSpec]:
        return {slug: c.spec for slug, c in self.concepts.items() if c.spec}

    @property
    def refs(self) -> set[str]:
        """Concepts this syllabus places but another (seed) course defines."""
        return {slug for slug, c in self.concepts.items() if not c.spec}

    def requirements(self, slug: str) -> Requirements:
        c = self.concepts[slug]
        return self.course.content_requirements.for_node(c.subject, c.chapter)

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for subject in self.subjects:
            row = dict.fromkeys(("chapters", "topics", "subtopics", "concepts", "formulas", "patterns", "shortcuts"), 0)
            for n in self.nodes:
                if n.key.split(".")[0] == subject.key and n.node_type != "subject":
                    row[f"{n.node_type}s"] += 1
            for c in self.concepts.values():
                if c.subject == subject.key:
                    row["concepts"] += 1
                    row["formulas"] += len(c.formulas)
                    row["patterns"] += len(c.patterns)
                    row["shortcuts"] += len(c.shortcuts)
            out[subject.key] = row
        return out


def _read_yaml(path: Path) -> object:
    if not path.is_file():
        raise SyllabusError(f"{path}: file not found")
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise SyllabusError(f"{path}: invalid YAML: {exc}") from exc


def _parse(model, path: Path):
    try:
        return model.model_validate(_read_yaml(path))
    except ValidationError as exc:
        lines = [f"  {'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}" for e in exc.errors()[:20]]
        raise SyllabusError(f"{path}: {exc.error_count()} problem(s)\n" + "\n".join(lines)) from exc


def _narrow(own: list[str], parent: list[str], where: str, stages: set[str]) -> list[str]:
    unknown = set(own) - stages
    if unknown:
        raise SyllabusError(f"{where}: unknown tiers {sorted(unknown)}; the course's exam stages are {sorted(stages)}")
    if not own:
        return list(parent)
    if not set(own) <= set(parent):
        raise SyllabusError(f"{where}: tiers {own} are not within its parent's {parent}")
    return [t for t in parent if t in own]  # keep the parent's order


def read(path: Path, external: set[str] | None = None, partial: list[str] | None = None, only_chapters: set[str] | None = None) -> Syllabus:
    """Read and validate the syllabus in `path`. `external` names concepts that other seed courses
    define; `ref:` may point at them (or at concepts this syllabus defines).

    With `partial` (a list), missing chapter files and references to concepts not found are
    appended to it as warnings instead of failing: for checking a syllabus while it is written.
    `only_chapters` ("subject/chapter" names) reads only those chapter files (implies partial)."""
    if only_chapters is not None and partial is None:
        partial = []
    external = external or set()

    def soft(message: str) -> None:
        if partial is None:
            raise SyllabusError(message)
        partial.append(message)

    course: CourseFile = _parse(CourseFile, path / "course.yaml")
    profiles: ExamProfilesFile = _parse(ExamProfilesFile, path / "exam_profiles.yaml")
    by_slug = {p.slug: p for p in profiles.profiles}
    for slug in course.exams:
        if slug not in by_slug:
            raise SyllabusError(f"course.yaml: exam {slug!r} is not in exam_profiles.yaml")
    unused = set(by_slug) - set(course.exams)
    if unused:
        raise SyllabusError(f"exam_profiles.yaml: {sorted(unused)} are not listed in course.yaml exams")
    stages = [by_slug[s].stage for s in course.exams]
    stage_set = set(stages)
    for slug in course.mock_targets:
        if slug not in by_slug:
            raise SyllabusError(f"course.yaml: mock_targets names unknown exam {slug!r}")
    for p in profiles.profiles:
        for s in p.pattern.sections:
            if s.subject and s.subject not in course.subjects:
                raise SyllabusError(f"exam_profiles.yaml: {p.slug} section {s.name!r} draws from unknown subject {s.subject!r}")

    def check_strategy(s: StrategySpec, where: str) -> None:
        if s.exam and s.exam not in by_slug:
            raise SyllabusError(f"{where}: strategy {s.key} is for unknown exam {s.exam!r}")

    nodes: list[NodeRow] = []
    placements: list[Placement] = []
    concepts: dict[str, ConceptContent] = {}
    strategies: list[StrategyRow] = []
    subjects: list[SubjectSpec] = []
    chapters_by_subject: dict[str, list[ChapterSpec]] = {}
    seen_nodes: set[str] = set()

    for s in course.strategies:
        check_strategy(s, "course.yaml")
        strategies.append(StrategyRow(s.key, None, s))

    def add_node(key: str, parent: str | None, node_type: str, title: str, pos: int, tiers: list[str]) -> None:
        if len(key) > NODE_KEY_MAX:
            raise SyllabusError(f"node key {key!r} is longer than {NODE_KEY_MAX} characters")
        if key in seen_nodes:
            raise SyllabusError(f"duplicate node key {key!r}")
        seen_nodes.add(key)
        nodes.append(NodeRow(key, parent, node_type, title, pos, tiers))

    def add_concepts(items: list[ConceptSpec], node_key: str, node_tiers: list[str], subject: str, chapter: str) -> None:
        for pos, c in enumerate(items):
            where = f"{node_key}: concept {c.id}"
            tiers = _narrow(c.tiers, node_tiers, where, stage_set)
            if any(p.concept == c.id and p.node_key == node_key for p in placements):
                raise SyllabusError(f"{where}: placed twice under the same node")
            placements.append(Placement(node_key, c.id, c.weight, pos, tiers))
            entry = concepts.get(c.id)
            if entry is None:
                entry = concepts[c.id] = ConceptContent(slug=c.id, subject=subject, chapter=chapter)
            if c.slug:
                if entry.spec is not None:
                    raise SyllabusError(f"{where}: defined twice (use `ref: {c.id}` for the second placement)")
                if c.slug in external:
                    raise SyllabusError(f"{where}: another seed course already defines it; use `ref: {c.slug}`")
                entry.spec, entry.subject, entry.chapter = c, subject, chapter
            entry.tiers = [t for t in stages if t in set(entry.tiers) | set(tiers)]
            entry.formulas += c.formulas
            entry.shortcuts += c.shortcuts
            entry.patterns += [(p, _narrow(p.tiers, tiers, f"{where} pattern {p.key}", stage_set)) for p in c.patterns]

    for spos, subject_key in enumerate(course.subjects):
        sdir = path / subject_key
        subject: SubjectSpec = _parse(SubjectSpec, sdir / "subject.yaml")
        if subject.key != subject_key:
            raise SyllabusError(f"{sdir}/subject.yaml: key {subject.key!r} must match its directory {subject_key!r}")
        subjects.append(subject)
        s_tiers = _narrow(subject.tiers, stages, f"subject {subject.key}", stage_set)
        add_node(subject.key, None, "subject", subject.title, spos, s_tiers)
        for st in subject.strategies:
            check_strategy(st, f"subject {subject.key}")
            strategies.append(StrategyRow(f"{subject.key}:{st.key}", subject.key, st))
        files = {p.stem for p in sdir.glob("*.yaml")} - {"subject"}
        forgotten = files - set(subject.chapters)
        if forgotten:
            raise SyllabusError(f"{sdir}: chapter files {sorted(forgotten)} are not listed in subject.yaml")
        chapters: list[ChapterSpec] = []
        for cpos, chapter_key in enumerate(subject.chapters):
            if only_chapters is not None and f"{subject_key}/{chapter_key}" not in only_chapters:
                continue
            if not (sdir / f"{chapter_key}.yaml").is_file():
                soft(f"{sdir}/{chapter_key}.yaml: file not found")
                continue
            chapter: ChapterSpec = _parse(ChapterSpec, sdir / f"{chapter_key}.yaml")
            if chapter.key != chapter_key:
                raise SyllabusError(f"{sdir}/{chapter_key}.yaml: key {chapter.key!r} must match the file name")
            chapters.append(chapter)
            ch_key = f"{subject.key}.{chapter.key}"
            ch_tiers = _narrow(chapter.tiers, s_tiers, f"chapter {ch_key}", stage_set)
            add_node(ch_key, subject.key, "chapter", chapter.title, cpos, ch_tiers)
            for st in chapter.strategies:
                check_strategy(st, f"chapter {ch_key}")
                strategies.append(StrategyRow(f"{ch_key}:{st.key}", ch_key, st))
            for tpos, topic in enumerate(chapter.topics):
                t_key = f"{ch_key}.{topic.key}"
                t_tiers = _narrow(topic.tiers, ch_tiers, f"topic {t_key}", stage_set)
                add_node(t_key, ch_key, "topic", topic.title, tpos, t_tiers)
                add_concepts(topic.concepts, t_key, t_tiers, subject.key, chapter.key)
                for stpos, sub in enumerate(topic.subtopics):
                    st_key = f"{t_key}.{sub.key}"
                    st_tiers = _narrow(sub.tiers, t_tiers, f"subtopic {st_key}", stage_set)
                    add_node(st_key, t_key, "subtopic", sub.title, stpos, st_tiers)
                    add_concepts(sub.concepts, st_key, st_tiers, subject.key, chapter.key)
        chapters_by_subject[subject.key] = chapters

    for row in strategies:
        if len(row.key) > NODE_KEY_MAX:
            raise SyllabusError(f"strategy key {row.key!r} is longer than {NODE_KEY_MAX} characters")
    req = course.content_requirements
    for key in req.subjects:
        if key not in course.subjects:
            raise SyllabusError(f"course.yaml: content_requirements names unknown subject {key!r}")
    for key in req.chapters:
        subject_key, _, chapter_key = key.partition(".")
        listed = any(sub.key == subject_key and chapter_key in sub.chapters for sub in subjects)
        if not listed or key.count(".") != 1:
            raise SyllabusError(f"course.yaml: content_requirements names unknown chapter {key!r} (use subject.chapter)")

    for slug, c in concepts.items():
        if c.spec is None and slug not in external:
            soft(f"concept ref {slug!r} is neither defined in this syllabus nor by a seed course")
        for attr in ("formulas", "shortcuts"):
            keys = [i.key for i in getattr(c, attr)]
            if len(keys) != len(set(keys)):
                raise SyllabusError(f"concept {slug}: duplicate {attr} keys across its placements")
        pkeys = [p.key for p, _ in c.patterns]
        if len(pkeys) != len(set(pkeys)):
            raise SyllabusError(f"concept {slug}: duplicate pattern keys across its placements")
        for key in [*pkeys, *(f.key for f in c.formulas), *(s.key for s in c.shortcuts)]:
            if len(f"{slug}:{key}") > CONTENT_KEY_MAX:
                raise SyllabusError(f"concept {slug}: key {key!r} makes a stored key longer than {CONTENT_KEY_MAX}")
        for s in c.shortcuts:  # a shortcut placed through a ref may point at a pattern of another placement
            if s.pattern and s.pattern not in pkeys:
                raise SyllabusError(f"concept {slug}: shortcut {s.key} points at unknown pattern {s.pattern!r}")
    _check_prerequisites(concepts, external, soft)
    return Syllabus(path, course, profiles, subjects, chapters_by_subject, nodes, placements, concepts, strategies)


def _check_prerequisites(concepts: dict[str, ConceptContent], external: set[str], soft) -> None:
    graph: dict[str, list[str]] = {}
    for slug, c in concepts.items():
        if not c.spec:
            continue
        for pre in c.spec.prerequisites:
            if pre not in concepts and pre not in external:
                soft(f"concept {slug}: unknown prerequisite {pre!r}")
        graph[slug] = list(c.spec.prerequisites)
    state: dict[str, int] = {}  # 1 visiting, 2 done

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            cycle = trail[trail.index(node) :] + [node]
            raise SyllabusError(f"prerequisite cycle: {' -> '.join(cycle)}")
        state[node] = 1
        for nxt in graph.get(node, []):
            visit(nxt, [*trail, node])
        state[node] = 2

    for node in graph:
        visit(node, [])
