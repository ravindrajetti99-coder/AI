"""The worker loop: claim a job, run its handler with a heartbeat, record the outcome.

Failure handling:
- a handler raising AppError or PermanentJobError fails the job at once;
- any other exception retries it with exponential backoff until `max_attempts`;
- a worker that dies mid-job stops heart-beating, and any worker's reaper re-queues the job;
- on shutdown (SIGTERM) the current job goes back to the queue at its next checkpoint, without
  using up an attempt.
"""

import logging
import os
import random
import secrets
import socket
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal, engine, utcnow
from app.core.errors import AppError
from app.jobs import registry, service
from app.jobs.backends import QueueBackend, make_backend
from app.jobs.context import Interrupted, JobCancelled, JobContext, LeaseLost, PermanentJobError
from app.jobs.models import Job

log = logging.getLogger("eduverse.worker")

MAX_BACKOFF_SECONDS = 3600


def backoff_seconds(attempt: int, base: float) -> float:
    """30 s, 60 s, 120 s, ... (capped at an hour), with +/-20% jitter so retries spread out."""
    return min(base * 2 ** max(0, attempt - 1), MAX_BACKOFF_SECONDS) * random.uniform(0.8, 1.2)


class _Heartbeat(threading.Thread):
    """Keeps `heartbeat_at` fresh while a handler runs, in its own connection."""

    def __init__(self, job_id, lease: str, interval: float, clock: Callable[[], datetime], on_beat: Callable[[], None]):
        super().__init__(name=f"heartbeat-{job_id}", daemon=True)
        self.job_id, self.lease, self.interval, self.clock, self.on_beat = job_id, lease, interval, clock, on_beat
        self.stopped = threading.Event()

    def run(self) -> None:
        while not self.stopped.wait(self.interval):
            try:
                with engine.begin() as conn:
                    conn.execute(
                        update(Job.__table__)
                        .where(Job.__table__.c.id == self.job_id, Job.__table__.c.lease == self.lease, Job.__table__.c.status == "running")
                        .values(heartbeat_at=self.clock())
                    )
                self.on_beat()
            except Exception as exc:  # e.g. SQLite busy: the next beat (or a checkpoint) catches up
                log.warning("heartbeat for job %s failed: %s", self.job_id, exc)

    def stop(self) -> None:
        self.stopped.set()
        self.join(timeout=5)


class Worker:
    def __init__(
        self, queues: Sequence[str] | None = None, *, name: str | None = None, backend: QueueBackend | None = None, clock: Callable[[], datetime] = utcnow
    ):
        s = get_settings()
        if s.jobs_stale_after_seconds <= 2 * s.jobs_heartbeat_seconds:
            raise ValueError("EDU_JOBS_STALE_AFTER_SECONDS must be more than twice EDU_JOBS_HEARTBEAT_SECONDS")
        self.queues = list(queues) if queues else None  # None: every queue
        self.name = name or f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(3)}"
        self.backend = backend or make_backend()
        self.clock = clock
        self.poll_seconds = s.jobs_poll_seconds
        self.heartbeat_seconds = s.jobs_heartbeat_seconds
        self.stale_after = s.jobs_stale_after_seconds
        self.retry_base = s.jobs_retry_base_seconds
        self.health_file = Path(s.jobs_health_file) if s.jobs_health_file else None
        self.stop_event = threading.Event()
        self._last_reap: datetime | None = None
        self._scheduled: dict[str, int] = {}  # periodic kind -> last bucket enqueued

    # ------------------------------------------------------------------ lifecycle

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def stopping(self) -> bool:
        return self.stop_event.is_set()

    def run(self) -> None:
        log.info("worker %s started (queues: %s)", self.name, ", ".join(self.queues) if self.queues else "all")
        try:
            while not self.stopping:
                try:
                    self.touch()
                    self.maintain()
                    if not self.run_once():
                        self.backend.wait(self.poll_seconds, self.stop_event)
                except Exception:  # database unavailable and the like: back off, stay alive
                    log.exception("worker loop error")
                    self.stop_event.wait(min(30.0, self.poll_seconds * 2))
        finally:
            self.backend.close()
            log.info("worker %s stopped", self.name)

    def run_once(self) -> bool:
        """Claim and run one due job; False when there was none."""
        claimed = self.backend.claim(self.name, self.queues, self.clock())
        if not claimed:
            return False
        self.execute(*claimed)
        return True

    def drain(self, limit: int = 1000) -> int:
        """Run due jobs until none are left (tests, `--once`)."""
        done = 0
        while done < limit and not self.stopping and self.run_once():
            done += 1
        return done

    def touch(self) -> None:
        """Liveness for `python -m app.worker --healthcheck`."""
        if self.health_file:
            try:
                self.health_file.touch()
            except OSError as exc:
                log.warning("cannot touch %s: %s", self.health_file, exc)

    # ------------------------------------------------------------------ maintenance

    def maintain(self) -> None:
        now = self.clock()
        if self._last_reap is None or (now - self._last_reap).total_seconds() >= min(60.0, self.stale_after / 2):
            with SessionLocal() as db:
                counts = service.reap_stale(db, now, self.stale_after)
            if any(counts.values()):
                log.warning("recovered stale jobs: %s", counts)
            self._last_reap = now
        self.schedule_periodic(now)

    def schedule_periodic(self, now: datetime) -> None:
        """Enqueue each periodic job once per interval. The dedupe key names the interval, so any
        number of workers produce one job per run."""
        for spec in registry.load().values():
            if not spec.every or (self.queues and spec.queue not in self.queues):
                continue
            bucket = int(now.timestamp() // spec.every)
            if self._scheduled.get(spec.kind) == bucket:
                continue
            with SessionLocal() as db:
                try:
                    service.enqueue(db, spec.kind, dedupe_key=f"{spec.kind}:{bucket}", run_at=now)
                    db.commit()
                except IntegrityError:  # another worker enqueued it first
                    db.rollback()
            self._scheduled[spec.kind] = bucket

    # ------------------------------------------------------------------ running a job

    def execute(self, job_id, lease: str) -> None:
        db = SessionLocal()
        beat = _Heartbeat(job_id, lease, self.heartbeat_seconds, self.clock, self.touch)
        beat.start()
        started = time.monotonic()
        try:
            job = db.get(Job, job_id)
            if job is None:  # deleted after the claim
                return
            ctx = JobContext(db, job, lease, self.clock, lambda: self.stopping)
            log.info("job %s %s: attempt %s of %s", job.kind, job.id, ctx.attempt, ctx.max_attempts)
            try:
                spec = registry.load().get(job.kind)
                if not spec:
                    raise PermanentJobError(f"No handler for job kind {job.kind}")
                spec.fn(ctx)
                ctx.finish("done")  # commits the handler's unsaved work with the status
                log.info("job %s %s: done in %.1fs", job.kind, job.id, time.monotonic() - started)
            except LeaseLost:
                log.warning("job %s %s: lease lost to another worker; result discarded", job.kind, job.id)
            except JobCancelled:
                ctx.finish("cancelled", "Cancelled")
            except Interrupted:
                ctx.requeue(self.clock(), "Worker stopped; resuming from the last checkpoint", count_attempt=False)
                log.info("job %s %s: handed back to the queue", job.kind, job.id)
            except Exception as exc:
                ctx.rollback()
                self._failed(ctx, exc)
        except LeaseLost:
            log.warning("job %s: lease lost while recording the outcome", job_id)
        except Exception:  # could not even record the outcome: the reaper will recover the job
            log.exception("job %s: could not record the outcome", job_id)
        finally:
            beat.stop()
            db.close()

    def _failed(self, ctx: JobContext, exc: Exception) -> None:
        message = str(exc) or type(exc).__name__
        if isinstance(exc, AppError | PermanentJobError):
            log.warning("job %s %s failed: %s", ctx.kind, ctx.id, message)
            ctx.finish("failed", message)
        elif ctx.attempt >= ctx.max_attempts:
            log.error("job %s %s failed after %s attempts: %s", ctx.kind, ctx.id, ctx.attempt, message, exc_info=exc)
            ctx.finish("failed", message)
        else:
            delay = backoff_seconds(ctx.attempt, self.retry_base)
            log.warning("job %s %s: attempt %s failed (%s); retrying in %.0fs", ctx.kind, ctx.id, ctx.attempt, message, delay)
            ctx.requeue(self.clock() + timedelta(seconds=delay), message)


def start_embedded() -> tuple[Worker, threading.Thread]:
    """A worker thread inside the API process (EDU_JOBS_EMBEDDED_WORKER)."""
    worker = Worker(name=f"api:{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(3)}")
    thread = threading.Thread(target=worker.run, name="embedded-worker", daemon=True)
    thread.start()
    return worker, thread


def healthy(max_age: float | None = None) -> bool:
    s = get_settings()
    if not s.jobs_health_file:
        return True
    max_age = max_age or max(60.0, 3 * s.jobs_poll_seconds, 3 * s.jobs_heartbeat_seconds)
    try:
        return time.time() - os.path.getmtime(s.jobs_health_file) < max_age
    except OSError:
        return False
