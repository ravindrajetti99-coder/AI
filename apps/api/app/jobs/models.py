"""The job table shared by the API (enqueue, status) and workers (claim, heartbeat, results)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, utcnow

STATUSES = ("queued", "running", "done", "failed", "cancelled")
FINISHED = ("done", "failed", "cancelled")


class Job(IdMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "queue", "run_at"),)

    kind: Mapped[str] = mapped_column(String(60))  # handler name, e.g. generate.lessons
    queue: Mapped[str] = mapped_column(String(40), default="default")
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # see STATUSES
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher runs first
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # not before
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    # Set while running: the worker's name, and a fresh token per claim that every write must
    # match, so a worker that lost the job (reaped as stale) cannot overwrite the new owner.
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease: Mapped[str | None] = mapped_column(String(32), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSONType, default=dict)  # shown to staff
    checkpoint: Mapped[dict] = mapped_column(JSONType, default=dict)  # handler resume state
    error: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
