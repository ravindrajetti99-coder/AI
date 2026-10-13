"""The persistent job queue: transactional enqueue, exclusive claims, retries with backoff, crash
recovery, lease fencing, checkpoints, cancellation, graceful shutdown, periodic jobs, the worker
loop (LISTEN/NOTIFY on PostgreSQL), the embedded API worker and the admin endpoints."""

import os
import signal
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import API, concept_id, make_actor
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app import worker as worker_cli
from app.core.config import get_settings
from app.core.db import SessionLocal, utcnow
from app.core.errors import AppError, Conflict
from app.jobs import registry, service
from app.jobs.backends import DatabaseQueue
from app.jobs.context import PermanentJobError
from app.jobs.models import Job
from app.jobs.worker import Worker, backoff_seconds, healthy
from app.main import app
from app.modules.content import service as content
from app.modules.content.models import Lesson
from app.modules.identity import service as identity
from app.modules.identity.models import AuditLog, RefreshToken


@pytest.fixture
def handlers(monkeypatch):
    """Register throwaway handlers (on the `test` queue unless given) for one test."""
    table = dict(registry.load())
    monkeypatch.setattr(registry, "_HANDLERS", table)

    def add(kind, fn, queue="test", **kw):
        table[kind] = registry.Spec(kind, fn, queue, **kw)

    return add


class Clock:
    """Real time plus an offset that a test moves forward (to make retries and stale jobs due)."""

    def __init__(self):
        self.offset = timedelta()

    def __call__(self):
        return utcnow() + self.offset

    @property
    def now(self):
        return self()

    def advance(self, **kw):
        self.offset += timedelta(**kw)


def enqueue(kind, payload=None, **kw) -> uuid.UUID:
    with SessionLocal() as db:
        job = service.enqueue(db, kind, payload, **kw)
        db.commit()
        return job.id


def load(job_id) -> Job:
    with SessionLocal() as db:
        return db.get(Job, job_id)


def audit_actions() -> list[str]:
    with SessionLocal() as db:
        return sorted(db.scalars(select(AuditLog.action).where(AuditLog.entity == "test")).all())


def write_item(ctx, name):
    ctx.db.add(AuditLog(action=name, entity="test", entity_id=str(ctx.id)))


# --------------------------------------------------------------------------- enqueue and claim


def test_enqueue_commits_with_the_callers_transaction(empty_db, handlers, worker):
    seen = []
    handlers("test.echo", lambda ctx: (seen.append(ctx.payload), ctx.result.update(echo=ctx.payload["n"])))
    with SessionLocal() as db:
        service.enqueue(db, "test.echo", {"n": 1})
        db.rollback()  # the caller's work failed, so its job never existed
    assert worker.drain() == 0
    job_id = enqueue("test.echo", {"n": 2})
    assert worker.drain() == 1 and seen == [{"n": 2}]
    job = load(job_id)
    assert (job.status, job.attempts, job.result, job.lease, job.queue) == ("done", 1, {"echo": 2}, None, "test")
    assert job.started_at and job.finished_at


def test_unknown_kinds_are_rejected_at_enqueue(empty_db):
    with SessionLocal() as db, pytest.raises(AppError, match="Unknown job kind"):
        service.enqueue(db, "nope.missing")


def test_priority_and_run_at_decide_the_order(empty_db, handlers):
    order = []
    handlers("test.order", lambda ctx: order.append(ctx.payload["name"]))
    clock = Clock()
    later = enqueue("test.order", {"name": "later"}, run_at=utcnow() + timedelta(minutes=5))
    enqueue("test.order", {"name": "low"})
    enqueue("test.order", {"name": "high"}, priority=10)
    w = Worker(name="w", clock=clock)
    assert w.drain() == 2 and order == ["high", "low"]
    assert load(later).status == "queued"  # not due yet
    clock.advance(minutes=6)
    assert w.drain() == 1 and order[-1] == "later"


def test_concurrent_workers_never_run_a_job_twice(empty_db, handlers):
    ran, lock, errors = [], threading.Lock(), []

    def record(ctx):
        with lock:
            ran.append(ctx.id)

    handlers("test.count", record)
    ids = {enqueue("test.count", {"i": i}) for i in range(24)}

    def drain(n):
        try:
            Worker(name=f"w{n}").drain()
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=drain, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert sorted(map(str, ran)) == sorted(map(str, ids))  # each job exactly once
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(Job.status == "done", Job.attempts == 1)) == 24


def test_dedupe_key_returns_the_existing_job(empty_db, handlers):
    handlers("test.once", lambda ctx: None)
    first = enqueue("test.once", dedupe_key="report:2026-10")
    assert enqueue("test.once", dedupe_key="report:2026-10") == first
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "test.once")) == 1


# --------------------------------------------------------------------------- failures and retries


def test_transient_errors_retry_with_backoff(empty_db, handlers):
    attempts = []

    def flaky(ctx):
        attempts.append(ctx.attempt)
        if ctx.attempt < 3:
            raise RuntimeError("provider overloaded")
        ctx.result["ok"] = True

    handlers("test.flaky", flaky)
    clock = Clock()
    w = Worker(name="w", clock=clock)
    job_id = enqueue("test.flaky")
    w.drain()
    job = load(job_id)
    assert (job.status, job.attempts, job.error) == ("queued", 1, "provider overloaded")
    assert job.run_at.replace(tzinfo=UTC) > clock.now  # waits out the backoff
    assert w.drain() == 0
    clock.advance(hours=1)
    w.drain()
    assert load(job_id).attempts == 2 and load(job_id).status == "queued"
    clock.advance(hours=2)
    w.drain()
    job = load(job_id)
    assert (job.status, job.attempts, job.result, job.error) == ("done", 3, {"ok": True}, "")
    assert attempts == [1, 2, 3]


@pytest.mark.parametrize("error", [PermanentJobError("bad payload"), AppError("bad payload")])
def test_permanent_errors_fail_without_retrying(empty_db, handlers, worker, error):
    def broken(ctx):
        raise error

    handlers("test.broken", broken)
    job = load(enqueue("test.broken"))
    worker.drain()
    job = load(job.id)
    assert (job.status, job.attempts, job.error) == ("failed", 1, "bad payload")


def test_retries_stop_at_max_attempts(empty_db, handlers):
    def always(ctx):
        raise RuntimeError("still down")

    handlers("test.down", always, max_attempts=2)
    clock = Clock()
    w = Worker(name="w", clock=clock)
    job_id = enqueue("test.down")
    for _ in range(3):
        w.drain()
        clock.advance(hours=2)
    job = load(job_id)
    assert (job.status, job.attempts, job.error, job.max_attempts) == ("failed", 2, "still down", 2)


def test_backoff_doubles_with_jitter_and_is_capped():
    assert 24 <= backoff_seconds(1, 30) <= 36
    assert 96 <= backoff_seconds(3, 30) <= 144
    assert backoff_seconds(30, 30) <= 3600 * 1.2


# --------------------------------------------------------------------------- crash recovery and leases


def test_jobs_of_a_dead_worker_are_recovered(empty_db, handlers):
    handlers("test.work", lambda ctx: ctx.result.update(by="survivor"))
    clock = Clock()
    retried = enqueue("test.work")
    exhausted = enqueue("test.work", max_attempts=1)
    cancelled = enqueue("test.work")
    dead = DatabaseQueue()
    for _ in range(3):  # a worker claims them and dies without a trace
        assert dead.claim("dead-worker", ["test"], clock.now)
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == cancelled).values(cancel_requested=True))
        db.commit()
    survivor = Worker(name="survivor", clock=clock)
    survivor.maintain()
    assert load(retried).status == "running"  # heartbeat still fresh: leave it alone
    clock.advance(seconds=get_settings().jobs_stale_after_seconds + 1)
    survivor.maintain()
    assert (load(exhausted).status, load(exhausted).error) == ("failed", "Worker stopped responding")
    assert load(cancelled).status == "cancelled"
    assert load(retried).status == "queued" and load(retried).locked_by is None
    survivor.drain()
    job = load(retried)
    assert (job.status, job.attempts, job.result) == ("done", 2, {"by": "survivor"})


def test_a_worker_that_lost_its_lease_cannot_write(empty_db, handlers, worker):
    taken = {}

    def slow(ctx):
        # Meanwhile this worker was presumed dead: the job was re-queued and another worker took it.
        with SessionLocal() as other:
            other.execute(update(Job).where(Job.id == ctx.id).values(status="queued", lease=None))
            other.commit()
        taken["lease"] = DatabaseQueue().claim("worker-b", ["test"], utcnow())[1]
        write_item(ctx, "stale-write")
        ctx.save()

    handlers("test.slow", slow)
    job_id = enqueue("test.slow")
    worker.drain()
    job = load(job_id)
    assert (job.status, job.locked_by, job.lease) == ("running", "worker-b", taken["lease"])  # untouched
    assert audit_actions() == []  # the stale worker's writes were rolled back


def test_heartbeats_keep_long_jobs_alive(empty_db, handlers, monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_heartbeat_seconds", 0.05)
    beats = []

    def long_running(ctx):
        first = load(ctx.id).heartbeat_at
        time.sleep(0.4)
        beats.append((first, load(ctx.id).heartbeat_at))

    handlers("test.long", long_running)
    enqueue("test.long")
    Worker(name="w").drain()
    first, later = beats[0]
    assert later > first


# --------------------------------------------------------------------------- checkpoints, cancel, shutdown


def items_handler(items, fail_on=None, before_save=None):
    """Writes one audit row per item and saves after each; optionally fails or acts mid-way."""

    def run(ctx):
        for name in items:
            if ctx.is_done(name):
                continue
            write_item(ctx, name)
            if fail_on and fail_on(ctx, name):
                raise RuntimeError(f"failed at {name}")
            ctx.result["count"] = ctx.result.get("count", 0) + 1
            ctx.mark_done(name)
            if before_save:
                before_save(ctx, name)
            ctx.save()

    return run


def test_retries_resume_from_the_last_checkpoint(empty_db, handlers):
    handlers("test.items", items_handler(["a", "b", "c"], fail_on=lambda ctx, name: name == "c" and ctx.attempt == 1))
    clock = Clock()
    w = Worker(name="w", clock=clock)
    job_id = enqueue("test.items")
    w.drain()
    job = load(job_id)
    assert (job.status, job.checkpoint, job.result) == ("queued", {"done": ["a", "b"]}, {"count": 2})
    assert audit_actions() == ["a", "b"]  # c's write was rolled back with the failure
    clock.advance(hours=1)
    w.drain()
    job = load(job_id)
    assert (job.status, job.result) == ("done", {"count": 3})
    assert audit_actions() == ["a", "b", "c"]  # nothing repeated


def test_cancelling_queued_running_and_finished_jobs(empty_db, handlers, worker):
    def cancel_now(ctx, name):
        if name == "a":
            with SessionLocal() as staff:
                service.cancel(staff, ctx.id)
                staff.commit()

    handlers("test.items", items_handler(["a", "b", "c"], before_save=cancel_now))
    queued = enqueue("test.items")
    with SessionLocal() as db:
        assert service.cancel(db, queued).status == "cancelled"
        db.commit()
    assert worker.drain() == 0 and audit_actions() == []

    running = enqueue("test.items")
    worker.drain()
    job = load(running)
    assert (job.status, job.result, job.error) == ("cancelled", {"count": 1}, "Cancelled")  # stopped at the checkpoint
    assert audit_actions() == ["a"]  # work saved before the cancel is kept
    with SessionLocal() as db, pytest.raises(Conflict, match="already cancelled"):
        service.cancel(db, running)


def test_retrying_a_failed_job_resumes_where_it_stopped(empty_db, handlers, worker):
    fail = {"on": True}
    handlers("test.items", items_handler(["a", "b"], fail_on=lambda ctx, name: name == "b" and fail["on"]), max_attempts=1)
    job_id = enqueue("test.items")
    worker.drain()
    assert load(job_id).status == "failed"
    fail["on"] = False
    with SessionLocal() as db:
        job = service.retry(db, job_id)
        db.commit()
        assert (job.status, job.attempts, job.error) == ("queued", 0, "")
    worker.drain()
    assert load(job_id).status == "done" and audit_actions() == ["a", "b"]
    with SessionLocal() as db, pytest.raises(Conflict):
        service.retry(db, job_id)


def test_shutdown_hands_the_job_back_without_using_an_attempt(empty_db, handlers):
    first = Worker(name="first")
    handlers("test.items", items_handler(["a", "b"], before_save=lambda ctx, name: first.stop()))
    job_id = enqueue("test.items")
    first.run_once()
    job = load(job_id)
    assert (job.status, job.attempts, job.checkpoint) == ("queued", 0, {"done": ["a"]})
    Worker(name="second").drain()
    job = load(job_id)
    assert (job.status, job.attempts) == ("done", 1) and audit_actions() == ["a", "b"]


# --------------------------------------------------------------------------- periodic jobs and maintenance


def test_periodic_jobs_are_enqueued_once_per_interval(empty_db, handlers):
    handlers("test.tick", lambda ctx: None, every=60)
    t0 = datetime(2026, 10, 13, 9, 0, 5, tzinfo=UTC)

    def ticks():
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(Job).where(Job.kind == "test.tick"))

    a, b = Worker(name="a"), Worker(name="b")
    a.schedule_periodic(t0)
    b.schedule_periodic(t0 + timedelta(seconds=30))  # same minute: the dedupe key stops a second job
    a.schedule_periodic(t0 + timedelta(seconds=40))
    assert ticks() == 1
    b.schedule_periodic(t0 + timedelta(seconds=60))
    assert ticks() == 2
    Worker(["content"], name="c").schedule_periodic(t0 + timedelta(seconds=120))
    assert ticks() == 2  # a worker only schedules jobs for queues it serves


def test_prune_deletes_old_jobs_and_expired_tokens(empty_db, handlers, worker):
    handlers("test.noop", lambda ctx: None)
    now = utcnow()
    old_done, recent_done, old_queued = enqueue("test.noop"), enqueue("test.noop"), enqueue("test.noop")
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id.in_([old_done, recent_done])).values(status="done", finished_at=now - timedelta(days=40)))
        db.execute(update(Job).where(Job.id == recent_done).values(finished_at=now - timedelta(days=1)))
        user = identity.create_user(db, "prune@example.com", "password-123", "P")
        identity.issue_tokens(db, user)
        identity.issue_tokens(db, user)
        db.execute(update(RefreshToken).where(RefreshToken.id == db.scalars(select(RefreshToken.id)).first()).values(expires_at=now - timedelta(days=1)))
        identity.issue_account_token(db, user, "reset", "", timedelta(minutes=30))  # still valid: kept
        identity.issue_account_token(db, user, "verify", "", timedelta(hours=-50))  # long expired: deleted
        db.commit()
    prune = enqueue("maintenance.prune")
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == old_queued).values(status="queued", run_at=now + timedelta(days=1)))
        db.commit()
    worker.drain()
    assert load(prune).result == {"jobs_deleted": 1, "refresh_tokens_deleted": 1, "account_tokens_deleted": 1}
    assert load(old_done) is None and load(recent_done) and load(old_queued)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RefreshToken)) == 1


# --------------------------------------------------------------------------- the worker loop


def test_an_idle_worker_picks_up_new_jobs(empty_db, handlers, monkeypatch):
    # The idle worker sleeps for a long poll; the commit must wake it (NOTIFY on PostgreSQL, an
    # in-process signal on SQLite).
    monkeypatch.setattr(get_settings(), "jobs_poll_seconds", 30)
    handlers("test.echo", lambda ctx: None)
    w = Worker(name="loop")
    thread = threading.Thread(target=w.run, daemon=True)
    thread.start()
    try:
        time.sleep(0.5)  # idle, waiting
        job_id = enqueue("test.echo")
        deadline = time.monotonic() + 5
        while load(job_id).status != "done" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert load(job_id).status == "done"
    finally:
        w.stop()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_the_api_runs_jobs_itself_with_the_embedded_worker(seeded_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_embedded_worker", True)
    with TestClient(app) as client:
        admin = make_actor(client, "admin")
        job_id = admin.post(f"{API}/admin/generate", json={"kind": "lessons", "concept_ids": [str(concept_id("discount"))], "levels": [3]}).json()["job_id"]
        deadline = time.monotonic() + 10
        while admin.get(f"{API}/admin/jobs/{job_id}").json()["status"] != "done" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert admin.get(f"{API}/admin/jobs/{job_id}").json()["status"] == "done"


def test_worker_command_line(empty_db, handlers, monkeypatch, tmp_path):
    monkeypatch.setattr(signal, "signal", lambda *_: None)  # keep pytest's own handlers
    handlers("test.echo", lambda ctx: None)
    job_id = enqueue("test.echo")
    assert worker_cli.main(["--once", "--queues", "test"]) == 0
    assert load(job_id).status == "done"
    health = tmp_path / "alive"
    monkeypatch.setattr(get_settings(), "jobs_health_file", str(health))
    assert worker_cli.main(["--healthcheck"]) == 1  # never touched
    Worker(name="w").touch()
    assert worker_cli.main(["--healthcheck"]) == 0 and healthy()
    os.utime(health, (time.time() - 3600, time.time() - 3600))
    assert not healthy()


def test_misconfigured_heartbeat_is_refused(monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_stale_after_seconds", 20)
    with pytest.raises(ValueError, match="twice"):
        Worker()


# --------------------------------------------------------------------------- generation jobs and the admin API


def test_a_retried_generation_job_does_not_duplicate_drafts(admin, worker, monkeypatch):
    real = content.generate_lesson
    calls = []

    def flaky(db, concept, level, *args, **kw):
        calls.append(level)
        if len(calls) == 2:
            raise RuntimeError("provider timeout")
        return real(db, concept, level, *args, **kw)

    monkeypatch.setattr(content, "generate_lesson", flaky)
    cid = concept_id("discount")
    job_id = admin.post(f"{API}/admin/generate", json={"kind": "lessons", "concept_ids": [str(cid)], "levels": [3, 4]}).json()["job_id"]
    worker.drain()
    job = admin.get(f"{API}/admin/jobs/{job_id}").json()
    assert (job["status"], len(job["result"]["created"]), job["error"]) == ("queued", 1, "provider timeout")
    worker.clock = lambda: utcnow() + timedelta(hours=1)
    worker.drain()
    job = admin.get(f"{API}/admin/jobs/{job_id}").json()
    assert job["status"] == "done" and [c["level"] for c in job["result"]["created"]] == [3, 4]
    assert calls == [3, 4, 4]  # level 3 was not generated again
    with SessionLocal() as db:
        drafts = db.scalars(select(Lesson.level).where(Lesson.concept_id == cid, Lesson.status == "in_review")).all()
    assert sorted(drafts) == [3, 4]


def test_admin_job_endpoints(admin, learner, worker):
    cid = str(concept_id("discount"))
    first = admin.post(f"{API}/admin/generate", json={"kind": "flashcards", "concept_ids": [cid], "count": 2}).json()["job_id"]
    second = admin.post(f"{API}/admin/generate", json={"kind": "flashcards", "concept_ids": [cid], "count": 2}).json()["job_id"]

    cancelled = admin.post(f"{API}/admin/jobs/{second}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert admin.post(f"{API}/admin/jobs/{second}/cancel").status_code == 409
    worker.drain()

    rows = admin.get(f"{API}/admin/jobs", params={"queue": "content"}).json()
    assert {r["id"]: r["status"] for r in rows} == {first: "done", second: "cancelled"}
    row = next(r for r in rows if r["id"] == first)
    assert row["kind"] == "generate.flashcards" and row["attempts"] == 1 and row["payload"]["count"] == 2 and row["result"]["created"]
    assert [r["id"] for r in admin.get(f"{API}/admin/jobs", params={"status": "cancelled"}).json()] == [second]
    assert admin.get(f"{API}/admin/jobs", params={"kind": "generate.lessons"}).json() == []
    assert admin.get(f"{API}/admin/jobs", params={"status": "sleeping"}).status_code == 422

    retried = admin.post(f"{API}/admin/jobs/{second}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert admin.post(f"{API}/admin/jobs/{second}/retry").status_code == 409
    assert admin.post(f"{API}/admin/jobs/{first}/retry").status_code == 409  # done jobs stay done
    worker.drain()
    assert admin.get(f"{API}/admin/jobs/{second}").json()["status"] == "done"

    assert admin.get(f"{API}/admin/jobs/{uuid.uuid4()}").status_code == 404
    assert admin.post(f"{API}/admin/jobs/{uuid.uuid4()}/cancel").status_code == 404
    assert learner.get(f"{API}/admin/jobs").status_code == 403
    assert learner.post(f"{API}/admin/jobs/{first}/cancel").status_code == 403
    with SessionLocal() as db:
        actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_id == second)).all()
    assert sorted(actions) == ["generate", "job_cancel", "job_retry"]


def test_job_rows_are_utc_iso_timestamps(admin, worker):
    job_id = admin.post(f"{API}/admin/generate", json={"kind": "lessons", "concept_ids": [str(concept_id("discount"))], "levels": [1]}).json()["job_id"]
    worker.drain()
    row = admin.get(f"{API}/admin/jobs/{job_id}").json()
    for key in ("created_at", "run_at", "started_at", "finished_at"):
        assert datetime.fromisoformat(row[key]).utcoffset() == timedelta(0), key
