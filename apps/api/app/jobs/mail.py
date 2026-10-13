"""Email delivery as jobs: a provider outage becomes a retry with backoff, not a lost email."""

import dataclasses
import uuid

from sqlalchemy.orm import Session

from app.core import mail
from app.core.mail import MailError, Message
from app.jobs import service
from app.jobs.context import JobContext, PermanentJobError
from app.jobs.models import Job
from app.jobs.registry import handler

QUEUE = "mail"


def queue_email(db: Session, message: Message, created_by: uuid.UUID | None = None) -> Job:
    """Send `message` from a worker once the caller's transaction commits."""
    return service.enqueue(db, "mail.send", {"message": dataclasses.asdict(message)}, created_by=created_by)


def deliver(ctx: JobContext, message: Message) -> None:
    """Send now; a permanent provider refusal fails the job, anything else retries it."""
    try:
        ctx.result.update(message_id=mail.send_now(message), backend=mail.backend().name, to=message.to)
    except MailError as exc:
        if exc.permanent:
            raise PermanentJobError(str(exc)) from exc
        raise


@handler("mail.send", queue=QUEUE, max_attempts=5)
def send(ctx: JobContext) -> None:
    message = Message(**ctx.payload["message"])
    # The body can carry a link or invite code: keep only the envelope once the job ends.
    ctx.final_payload = {"message": {"to": message.to, "subject": message.subject, "tags": message.tags}}
    deliver(ctx, message)
