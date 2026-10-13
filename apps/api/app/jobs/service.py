"""Enqueue, inspect, cancel and retry jobs. Other modules use only these functions."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.db import as_utc, utcnow
from app.core.errors import Conflict, NotFound
from app.jobs import registry
from app.jobs.backends import default_backend
from app.jobs.models import FINISHED, Job


def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    *,
    created_by: uuid.UUID | None = None,
    run_at: datetime | None = None,
    priority: int = 0,
    dedupe_key: str | None = None,
    max_attempts: int | None = None,
) -> Job:
    """Add a job in the caller's transaction: it becomes visible to workers when the caller
    commits, and disappears with a rollback. With `dedupe_key`, an existing job with that key is
    returned instead (racing enqueuers hit the unique constraint at commit)."""
    spec = registry.get(kind)
    if dedupe_key:
        existing = db.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
        if existing:
            return existing
    job = Job(
        kind=kind,
        queue=spec.queue,
        payload=payload or {},
        created_by=created_by,
        run_at=run_at or utcnow(),
        priority=priority,
        dedupe_key=dedupe_key,
        max_attempts=max_attempts or spec.max_attempts,
    )
    db.add(job)
    db.flush()
    default_backend().notify(db, job.queue)
    return job


def get(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise NotFound("Job not found")
    return job


def list_jobs(db: Session, status: str | None = None, queue: str | None = None, kind: str | None = None, limit: int = 50) -> list[Job]:
    q = select(Job)
    if status:
        q = q.where(Job.status == status)
    if queue:
        q = q.where(Job.queue == queue)
    if kind:
        q = q.where(Job.kind == kind)
    return list(db.scalars(q.order_by(Job.created_at.desc(), Job.id).limit(limit)).all())


def cancel(db: Session, job_id: uuid.UUID) -> Job:
    """A queued job is cancelled at once; a running one stops at its next checkpoint. The caller commits."""
    now = utcnow()
    rows = db.execute(
        update(Job).where(Job.id == job_id, Job.status == "queued").values(status="cancelled", finished_at=now, updated_at=now, error="Cancelled")
    ).rowcount
    if not rows:
        rows = db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(cancel_requested=True, updated_at=now)).rowcount
    job = get(db, job_id)
    db.refresh(job)
    if not rows:
        raise Conflict(f"Job is already {job.status}")
    return job


def retry(db: Session, job_id: uuid.UUID) -> Job:
    """Queue a failed or cancelled job again with fresh attempts. Its checkpoint is kept, so it
    resumes after the work it already finished. The caller commits."""
    now = utcnow()
    job = get(db, job_id)
    rows = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status.in_(("failed", "cancelled")))
        .values(status="queued", attempts=0, run_at=now, error="", cancel_requested=False, finished_at=None, lease=None, locked_by=None, updated_at=now)
    ).rowcount
    if not rows:
        raise Conflict(f"Only failed or cancelled jobs can be retried (this one is {job.status})")
    default_backend().notify(db, job.queue)
    db.refresh(job)
    return job


def reap_stale(db: Session, now: datetime, stale_after: float) -> dict:
    """Recover running jobs whose worker stopped heart-beating (crashed, killed, lost its
    connection): cancel them if staff asked, otherwise retry them while attempts remain."""
    cutoff = now - timedelta(seconds=stale_after)
    stale = (Job.status == "running", Job.heartbeat_at < cutoff)
    released = {"lease": None, "locked_by": None, "updated_at": now}
    counts = {
        "cancelled": db.execute(update(Job).where(*stale, Job.cancel_requested.is_(True)).values(status="cancelled", finished_at=now, **released)).rowcount,
        "requeued": db.execute(
            update(Job)
            .where(*stale, Job.attempts < Job.max_attempts)
            .values(status="queued", run_at=now, error="Worker stopped responding; retrying", **released)
        ).rowcount,
        "failed": db.execute(update(Job).where(*stale).values(status="failed", finished_at=now, error="Worker stopped responding", **released)).rowcount,
    }
    db.commit()
    return counts


def prune(db: Session, older_than: datetime) -> int:
    """Delete finished jobs older than the retention window."""
    return db.execute(delete(Job).where(Job.status.in_(FINISHED), Job.finished_at < older_than)).rowcount


def row(job: Job) -> dict:
    def iso(dt):
        return as_utc(dt).isoformat() if dt else None

    return {
        "id": str(job.id),
        "kind": job.kind,
        "queue": job.queue,
        "status": job.status,
        "payload": job.payload,
        "result": job.result,
        "error": job.error,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "cancel_requested": job.cancel_requested,
        "created_at": iso(job.created_at),
        "run_at": iso(job.run_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }
