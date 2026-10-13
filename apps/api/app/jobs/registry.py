"""Job handlers by kind. Handler modules register on import; `load()` imports all of them."""

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.errors import AppError

if TYPE_CHECKING:
    from app.jobs.context import JobContext

# Every module that defines handlers. Workers and `enqueue` import these before looking up a kind.
HANDLER_MODULES = ("app.modules.ingest.jobs", "app.modules.identity.jobs", "app.jobs.maintenance", "app.jobs.mail")


@dataclass(frozen=True)
class Spec:
    kind: str
    fn: "Callable[[JobContext], None]"
    queue: str = "default"
    max_attempts: int = 3
    every: float | None = None  # seconds; periodic jobs are enqueued by workers serving `queue`


_HANDLERS: dict[str, Spec] = {}


def handler(kind: str, *, queue: str = "default", max_attempts: int = 3, every: float | None = None):
    """Register `fn(ctx)` as the handler for `kind`."""

    def register(fn):
        _HANDLERS[kind] = Spec(kind, fn, queue, max_attempts, every)
        return fn

    return register


def load() -> dict[str, Spec]:
    for module in HANDLER_MODULES:
        importlib.import_module(module)
    return _HANDLERS


def get(kind: str) -> Spec:
    spec = load().get(kind)
    if not spec:
        raise AppError(f"Unknown job kind {kind}")
    return spec
