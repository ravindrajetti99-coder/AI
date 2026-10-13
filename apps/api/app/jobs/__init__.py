"""Persistent background jobs.

The API enqueues work with `service.enqueue(db, kind, payload)` inside its own transaction;
workers (`python -m app.worker`, or a thread in the API process) claim and run it. The `jobs`
table is the source of truth for status, results and errors; a `QueueBackend` only decides how
workers find and claim work, so the transport can move to Redis later without touching handlers.
"""
