"""Periodic housekeeping, enqueued by workers that serve the `maintenance` queue."""

from datetime import timedelta

from app.core.config import get_settings
from app.jobs import registry, service
from app.jobs.context import JobContext
from app.modules.identity import service as identity


@registry.handler("maintenance.prune", queue="maintenance", every=3600, max_attempts=1)
def prune(ctx: JobContext) -> None:
    """Delete finished jobs past the retention window and refresh tokens that have expired."""
    now = ctx.now()
    ctx.result = {
        "jobs_deleted": service.prune(ctx.db, now - timedelta(days=get_settings().jobs_retention_days)),
        "refresh_tokens_deleted": identity.purge_expired_refresh_tokens(ctx.db, now),
    }
