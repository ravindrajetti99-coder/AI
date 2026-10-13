"""CLI: `python -m app.seed.syllabus [NAME ...]` validates syllabi and prints their size."""

import argparse
import sys

from app.seed.syllabus import ALL_SYLLABI, DATA_DIR, SyllabusError, external_concepts
from app.seed.syllabus.reader import read


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed.syllabus", description="Validate syllabus files without touching the database.")
    parser.add_argument("names", nargs="*", default=list(ALL_SYLLABI), help=f"syllabus directories under {DATA_DIR} (default: all)")
    parser.add_argument("--partial", action="store_true", help="report missing chapter files and unresolved concepts as warnings")
    parser.add_argument("--subject", help="only print the counts of this subject")
    parser.add_argument("--chapters", nargs="+", metavar="SUBJECT/CHAPTER", help="read only these chapter files (implies --partial)")
    args = parser.parse_args(argv)
    external = external_concepts()
    failed = False
    for name in args.names:
        warnings: list[str] | None = [] if args.partial or args.chapters else None
        try:
            syl = read(DATA_DIR / name, external, partial=warnings, only_chapters=set(args.chapters) if args.chapters else None)
        except SyllabusError as exc:
            print(f"{name}: INVALID\n{exc}", file=sys.stderr)
            failed = True
            continue
        counts = syl.counts()
        cols = ("chapters", "topics", "subtopics", "concepts", "formulas", "patterns", "shortcuts")
        print(f"{name}: ok ({syl.course.title}; exams {', '.join(syl.course.exams)})")
        print(f"  {'subject':<22}" + "".join(f"{c:>10}" for c in cols))
        for subject, row in counts.items():
            if args.subject and subject != args.subject:
                continue
            print(f"  {subject:<22}" + "".join(f"{row[c]:>10}" for c in cols))
        totals = {c: sum(r[c] for r in counts.values()) for c in cols}
        print(f"  {'total':<22}" + "".join(f"{totals[c]:>10}" for c in cols))
        print(f"  strategies: {len(syl.strategies)}; reused concepts: {', '.join(sorted(syl.refs)) or 'none'}")
        for w in warnings or []:
            if not args.subject or f"/{args.subject}/" in w or "concept" in w:
                print(f"  warning: {w}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
