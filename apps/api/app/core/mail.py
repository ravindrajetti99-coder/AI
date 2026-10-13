"""Outgoing email behind one small interface, so the provider can change without touching callers.

Backends (EDU_MAIL_BACKEND):
- `console` (development): logs the message and keeps it in `OUTBOX` (and, with
  EDU_MAIL_OUTBOX_DIR, writes it there as JSON); production refuses it.
- `smtp`: any SMTP relay, from EDU_SMTP_URL (smtp://user:pass@host:587 uses STARTTLS,
  smtps://user:pass@host:465 uses TLS from the start).
- `ses`: Amazon SES v2 `SendEmail` in EDU_SES_REGION. Credentials come from the standard AWS
  chain (environment, shared config, or the task/instance role on ECS/EC2).

Callers normally send through jobs (`mail.send`, or a handler that creates a token and sends
directly) so a provider outage becomes a retry instead of a lost email. Backends raise
`MailError(permanent=...)`: permanent failures (rejected address, unverified sender) are not
retried; throttling and network errors are.
"""

import dataclasses
import json
import logging
import os
import smtplib
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from functools import lru_cache
from typing import Protocol
from urllib.parse import unquote, urlsplit

from app.core.config import get_settings

log = logging.getLogger("eduverse.mail")


@dataclass
class Message:
    to: str
    subject: str
    text: str
    html: str = ""
    tags: dict[str, str] = field(default_factory=dict)  # e.g. {"category": "password_reset"}


class MailError(Exception):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class MailBackend(Protocol):
    name: str

    def send(self, message: Message) -> str:
        """Deliver the message (or raise MailError); returns the provider's message id."""


# --------------------------------------------------------------------------- console


OUTBOX: list[Message] = []  # what the console backend "sent" (development and tests)
_outbox_lock = threading.Lock()


class ConsoleMail:
    name = "console"

    def __init__(self, outbox_dir: str = ""):
        self.outbox_dir = outbox_dir  # also write each email there as JSON (development, e2e tests)

    def send(self, message: Message) -> str:
        message_id = make_msgid(domain="console.local")
        with _outbox_lock:
            OUTBOX.append(message)
        if self.outbox_dir:
            os.makedirs(self.outbox_dir, exist_ok=True)
            path = os.path.join(self.outbox_dir, f"{time.time_ns()}-{uuid.uuid4().hex[:8]}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({**dataclasses.asdict(message), "message_id": message_id}, f, ensure_ascii=False)
        log.info("email to %s: %s\n%s", message.to, message.subject, message.text)
        return message_id


# --------------------------------------------------------------------------- SMTP


class SmtpMail:
    name = "smtp"

    def __init__(self, url: str, sender: str, reply_to: str = "", timeout: float = 20.0):
        parts = urlsplit(url)
        if parts.scheme not in ("smtp", "smtps") or not parts.hostname:
            raise ValueError("EDU_SMTP_URL must look like smtp://user:pass@host:587 or smtps://user:pass@host:465")
        self.tls = parts.scheme == "smtps"
        self.host, self.port = parts.hostname, parts.port or (465 if self.tls else 587)
        self.user, self.password = unquote(parts.username or ""), unquote(parts.password or "")
        self.sender, self.reply_to, self.timeout = sender, reply_to, timeout

    def _mime(self, message: Message) -> EmailMessage:
        mime = EmailMessage()
        mime["From"] = self.sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime["Message-ID"] = make_msgid(domain=parseaddr(self.sender)[1].rpartition("@")[2] or None)
        if self.reply_to:
            mime["Reply-To"] = self.reply_to
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")
        return mime

    def send(self, message: Message) -> str:
        mime = self._mime(message)
        context = ssl.create_default_context()
        try:
            if self.tls:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with server:
                if not self.tls:
                    server.starttls(context=context)
                if self.user:
                    server.login(self.user, self.password)
                server.send_message(mime)
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(f"recipient refused: {exc.recipients}", permanent=True) from exc
        except smtplib.SMTPResponseException as exc:  # 5xx: the server will not take it; 4xx: try later
            raise MailError(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}", permanent=exc.smtp_code >= 500) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"SMTP unavailable: {exc}") from exc
        return mime["Message-ID"]


# --------------------------------------------------------------------------- Amazon SES


# SES error codes that retrying cannot fix (bad address, unverified sender, account blocked).
SES_PERMANENT = {
    "MessageRejected",
    "MailFromDomainNotVerifiedException",
    "AccountSuspendedException",
    "SendingPausedException",
    "NotFoundException",
    "BadRequestException",
}


class SesMail:
    name = "ses"

    def __init__(self, region: str, sender: str, reply_to: str = "", configuration_set: str = "", client=None):
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "sesv2", region_name=region, config=Config(retries={"mode": "standard", "max_attempts": 3}, connect_timeout=5, read_timeout=20)
            )
        self.client = client
        self.sender, self.reply_to, self.configuration_set = sender, reply_to, configuration_set

    def send(self, message: Message) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        body = {"Text": {"Data": message.text, "Charset": "UTF-8"}}
        if message.html:
            body["Html"] = {"Data": message.html, "Charset": "UTF-8"}
        request = {
            "FromEmailAddress": self.sender,
            "Destination": {"ToAddresses": [message.to]},
            "Content": {"Simple": {"Subject": {"Data": message.subject, "Charset": "UTF-8"}, "Body": body}},
        }
        if self.reply_to:
            request["ReplyToAddresses"] = [self.reply_to]
        if self.configuration_set:
            request["ConfigurationSetName"] = self.configuration_set
        if message.tags:
            request["EmailTags"] = [{"Name": k, "Value": v} for k, v in message.tags.items()]
        try:
            return self.client.send_email(**request)["MessageId"]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            raise MailError(f"SES {code}: {exc.response.get('Error', {}).get('Message', '')}", permanent=code in SES_PERMANENT) from exc
        except BotoCoreError as exc:  # network, credentials, endpoint: try again later
            raise MailError(f"SES unavailable: {exc}") from exc


# --------------------------------------------------------------------------- selection


def sender_address() -> str:
    s = get_settings()
    name, addr = parseaddr(s.mail_from)
    return formataddr((name, addr)) if addr else s.mail_from


def make_backend() -> MailBackend:
    s = get_settings()
    if s.mail_backend == "smtp":
        return SmtpMail(s.smtp_url, sender_address(), s.mail_reply_to)
    if s.mail_backend == "ses":
        return SesMail(s.ses_region, sender_address(), s.mail_reply_to, s.ses_configuration_set)
    return ConsoleMail(s.mail_outbox_dir)


@lru_cache
def backend() -> MailBackend:
    return make_backend()


def send_now(message: Message) -> str:
    """Send synchronously through the configured backend (jobs call this)."""
    return backend().send(message)
