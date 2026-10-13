"""Assessment jobs: processing previous-year question imports."""

import json
import uuid

from sqlalchemy import select

from app.jobs.context import JobContext, PermanentJobError
from app.jobs.registry import handler
from app.modules.assessment import pyq
from app.modules.assessment.models import PyqImport, PyqSource

SAVE_EVERY = 50  # rows per checkpoint


@handler("pyq.import")
def pyq_import(ctx: JobContext) -> None:
    imp = ctx.db.get(PyqImport, uuid.UUID(ctx.payload["import_id"]))
    if imp is None:
        raise PermanentJobError("import not found")
    data = json.loads(imp.payload)
    paper, rows = data["paper"], data["questions"]
    summary = ctx.result.setdefault(
        "summary",
        {
            "paper": paper["key"],
            "rows": len(rows),
            "dry_run": imp.dry_run,
            **dict.fromkeys(("created", "updated", "unchanged", "duplicate", "invalid", "unmapped"), 0),
        },
    )
    errors = ctx.result.setdefault("errors", [])
    seen = set(ctx.checkpoint.get("seen", []))
    if imp.dry_run:
        source = ctx.db.scalar(select(PyqSource).where(PyqSource.key == paper["key"]))
    else:
        source = pyq.upsert_source(ctx.db, paper)
    imp.status = "running"
    start = int(ctx.checkpoint.get("next", 0))
    for i in range(start, len(rows)):
        raw = rows[i] if isinstance(rows[i], dict) else {}
        outcome, message, unmapped = pyq.import_row(ctx.db, paper, source, raw, seen, imp.dry_run)
        summary[outcome] += 1
        summary["unmapped"] += int(unmapped)
        if message and len(errors) < pyq.MAX_ERRORS:
            errors.append({"row": i + 1, "number": raw.get("number"), "outcome": outcome, "error": message})
        if (i + 1) % SAVE_EVERY == 0 and i + 1 < len(rows):
            ctx.checkpoint.update(next=i + 1, seen=sorted(seen))
            imp.summary, imp.errors = summary, errors
            ctx.save()
    pyq.finish(imp, "done", summary, errors)
