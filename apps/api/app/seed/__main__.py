"""CLI: `python -m app.seed [--only SLUG ...] [--no-tests]`."""

import argparse
import sys

from app import models  # noqa: F401  (registers all tables)
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.seed.loader import SeedError, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description="Load or refresh the EduVerse seed courses (safe to re-run).")
    parser.add_argument("--only", nargs="+", metavar="SLUG", help="course slugs to load (default: all)")
    parser.add_argument("--no-tests", action="store_true", help="skip building the mock test of each course")
    args = parser.parse_args(argv)
    if not get_settings().is_production:
        Base.metadata.create_all(engine)  # production runs `alembic upgrade head` first
    with SessionLocal() as db:
        try:
            stats = load(db, only=args.only, build_tests=not args.no_tests)
        except SeedError as exc:
            print(f"seed failed: {exc}", file=sys.stderr)
            return 1
    print("Seed complete:")
    for key, value in sorted(stats.items()):
        print(f"  {key:<30} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
