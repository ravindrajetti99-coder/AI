"""Queue transports. The `jobs` table always holds job state; a backend decides how workers find
and claim work. `DatabaseQueue` is the only one today; a Redis backend would push job ids to a
stream after commit and claim from it, leaving the table, handlers and API unchanged."""

import logging
import secrets
import threading
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.jobs.models import Job

log = logging.getLogger("eduverse.jobs")

CHANNEL = "eduverse_jobs"

# Without LISTEN/NOTIFY (SQLite), an enqueue still wakes workers in the same process (the API's
# embedded worker) as soon as its transaction commits; workers elsewhere poll.
_local_wake = threading.Event()


class QueueBackend(Protocol):
    def notify(self, db: Session, queue: str) -> None:
        """Called inside the enqueueing transaction; wakes idle workers once it commits."""

    def claim(self, worker_id: str, queues: Sequence[str] | None, now: datetime) -> tuple[uuid.UUID, str] | None:
        """Take the next due job: mark it running and return (job id, lease), or None."""

    @staticmethod
    def _full_queues(db: Session) -> list[str]:
        """Queues already running their EDU_JOBS_QUEUE_CONCURRENCY limit. A soft cap: workers
        claiming at the same instant can overshoot it by one each."""
        caps = get_settings().jobs_queue_concurrency
        if not caps:
            return []
        running = dict(db.execute(select(Job.queue, func.count()).where(Job.status == "running", Job.queue.in_(caps)).group_by(Job.queue)).all())
        return [queue for queue, cap in caps.items() if running.get(queue, 0) >= cap]

    def wait(self, timeout: float, stop: threading.Event) -> None:
        """Block until new work may be available, `timeout` passes, or `stop` is set."""

    def close(self) -> None: ...


class DatabaseQueue:
    """Claims with SELECT ... FOR UPDATE SKIP LOCKED plus a compare-and-set, so any number of
    workers can share the table (on SQLite, which has no row locks, the compare-and-set alone
    keeps claims exclusive). On PostgreSQL, LISTEN/NOTIFY wakes idle workers as soon as a job
    commits; elsewhere workers poll."""

    def __init__(self) -> None:
        self.postgres = engine.dialect.name == "postgresql"
        self._listener = None

    def notify(self, db: Session, queue: str) -> None:
        if self.postgres:
            db.execute(text("SELECT pg_notify(:channel, :queue)"), {"channel": CHANNEL, "queue": queue})
        else:
            event.listen(db, "after_commit", lambda _session: _local_wake.set(), once=True)

    def claim(self, worker_id: str, queues: Sequence[str] | None, now: datetime) -> tuple[uuid.UUID, str] | None:
        with SessionLocal() as db:
            full = self._full_queues(db)
            for _ in range(5):  # another worker may win the compare-and-set; try the next job
                q = select(Job.id).where(Job.status == "queued", Job.run_at <= now)
                if queues:
                    q = q.where(Job.queue.in_(queues))
                if full:
                    q = q.where(Job.queue.not_in(full))
                q = q.order_by(Job.priority.desc(), Job.run_at, Job.id).limit(1).with_for_update(skip_locked=True)
                job_id = db.scalar(q)
                if job_id is None:
                    db.rollback()
                    return None
                lease = secrets.token_hex(16)
                res = db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "queued")
                    .values(status="running", attempts=Job.attempts + 1, locked_by=worker_id, lease=lease, started_at=now, heartbeat_at=now, updated_at=now)
                    .execution_options(synchronize_session=False)
                )
                db.commit()
                if res.rowcount == 1:
                    return job_id, lease
        return None

    @staticmethod
    def _full_queues(db: Session) -> list[str]:
        """Queues already running their EDU_JOBS_QUEUE_CONCURRENCY limit. A soft cap: workers
        claiming at the same instant can overshoot it by one each."""
        caps = get_settings().jobs_queue_concurrency
        if not caps:
            return []
        running = dict(db.execute(select(Job.queue, func.count()).where(Job.status == "running", Job.queue.in_(caps)).group_by(Job.queue)).all())
        return [queue for queue, cap in caps.items() if running.get(queue, 0) >= cap]

    def wait(self, timeout: float, stop: threading.Event) -> None:
        deadline = time.monotonic() + timeout
        if not self.postgres:
            while not stop.is_set() and (remaining := deadline - time.monotonic()) > 0:
                if _local_wake.wait(min(remaining, 0.5)):
                    _local_wake.clear()
                    return
            return
        try:
            conn = self._listen()
            while not stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                # Short slices keep shutdown responsive; any notification means "check now".
                # Always exhaust the generator: psycopg holds the connection lock while it runs.
                woken = False
                for _ in conn.notifies(timeout=min(remaining, 1.0), stop_after=1):
                    woken = True
                if woken:
                    for _ in conn.notifies(timeout=0):  # drain the rest of the burst
                        pass
                    return
        except Exception as exc:  # lost connection: poll this round, reconnect next time
            log.warning("LISTEN failed (%s); polling instead", exc)
            self.close()
            stop.wait(max(0.0, deadline - time.monotonic()))

    def _listen(self):
        if self._listener is None or self._listener.closed:
            import psycopg

            url = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
            self._listener = psycopg.connect(url, autocommit=True)
            self._listener.execute(f"LISTEN {CHANNEL}")
        return self._listener

    def close(self) -> None:
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None


def make_backend() -> QueueBackend:
    name = get_settings().jobs_backend
    if name == "database":
        return DatabaseQueue()
    raise RuntimeError(f"Unknown jobs backend {name}")


@lru_cache
def default_backend() -> QueueBackend:
    """Shared by enqueuers (only `notify` is used there); each worker makes its own for LISTEN."""
    return make_backend()
