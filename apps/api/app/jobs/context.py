"""What a handler sees while it runs: its payload, a session, and checkpoints that survive retries."""

import copy
import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.jobs.models import Job


class PermanentJobError(Exception):
    """Fail the job without retrying (bad input, missing data). AppError is treated the same way."""


class JobCancelled(Exception):
    """Staff cancelled the job; raised at a checkpoint after the work so far is saved."""


class Interrupted(Exception):
    """The worker is shutting down; raised at a checkpoint so the job goes back to the queue."""


class LeaseLost(Exception):
    """Another worker owns the job now (this one was presumed dead); drop uncommitted work."""


class JobContext:
    """Handlers write content through `db` and call `save()` after each unit of work. `save()`
    commits that work together with the job's result and checkpoint in one transaction, so a
    retry resumes after the last saved unit and never repeats (or pays twice for) finished work.
    Anything not yet saved when the handler returns is committed together with the final status.
    """

    def __init__(self, db: Session, job: Job, lease: str, clock: Callable[[], datetime], stopping: Callable[[], bool]):
        self.db = db
        self.id: uuid.UUID = job.id
        self.kind = job.kind
        self.payload: dict = copy.deepcopy(job.payload or {})
        self.attempt = job.attempts
        self.max_attempts = job.max_attempts
        self.created_by: uuid.UUID | None = job.created_by
        self.result: dict = copy.deepcopy(job.result or {})
        self.checkpoint: dict = copy.deepcopy(job.checkpoint or {})
        self.clock = clock
        self._lease = lease
        self._stopping = stopping
        self._saved = (copy.deepcopy(self.result), copy.deepcopy(self.checkpoint))
        # Set by handlers whose payload holds something that should not outlive the job (an
        # email body with a link or code): stored in place of the payload once the job finishes.
        self.final_payload: dict | None = None

    def now(self) -> datetime:
        return self.clock()

    # ------------------------------------------------------------------ checkpoints

    def is_done(self, key: str) -> bool:
        return key in self.checkpoint.get("done", [])

    def mark_done(self, key: str) -> None:
        self.checkpoint.setdefault("done", []).append(key)

    def save(self) -> None:
        """Commit the work so far; then stop here if the job was cancelled or the worker is stopping."""
        self.write(result=self.result, checkpoint=self.checkpoint, heartbeat_at=self.now())
        self.db.commit()
        self._saved = (copy.deepcopy(self.result), copy.deepcopy(self.checkpoint))
        if self.db.scalar(select(Job.cancel_requested).where(Job.id == self.id)):
            raise JobCancelled()
        if self._stopping():
            raise Interrupted()

    def rollback(self) -> None:
        """Discard unsaved work, in the database and in `result`/`checkpoint`."""
        self.db.rollback()
        self.result, self.checkpoint = copy.deepcopy(self._saved[0]), copy.deepcopy(self._saved[1])

    # ------------------------------------------------------------------ status changes (used by the worker)

    def write(self, **values) -> None:
        """Update this job's row, but only while this worker still holds the lease."""
        res = self.db.execute(
            update(Job)
            .where(Job.id == self.id, Job.lease == self._lease, Job.status == "running")
            .values(updated_at=self.now(), **values)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            self.db.rollback()
            raise LeaseLost(f"job {self.id} is no longer leased to this worker")

    def finish(self, status: str, error: str = "") -> None:
        extra = {"payload": self.final_payload} if self.final_payload is not None else {}
        self.write(status=status, error=error[:2000], result=self.result, checkpoint=self.checkpoint, lease=None, finished_at=self.now(), **extra)
        self.db.commit()

    def requeue(self, run_at: datetime, error: str = "", count_attempt: bool = True) -> None:
        values = {
            "status": "queued",
            "run_at": run_at,
            "error": error[:2000],
            "result": self.result,
            "checkpoint": self.checkpoint,
            "lease": None,
            "locked_by": None,
        }
        if not count_attempt:
            values["attempts"] = Job.attempts - 1
        self.write(**values)
        self.db.commit()
