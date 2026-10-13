"""Email backends (console, SMTP, Amazon SES through the real boto3 client with a stubbed
transport) and the `mail.send` job: retries, permanent failures and payload redaction."""

import json
import smtplib

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from conftest import API
from sqlalchemy import select

from app.core import mail
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.mail import ConsoleMail, MailError, Message, SesMail, SmtpMail
from app.jobs.mail import queue_email
from app.jobs.models import Job

MESSAGE = Message(to="ravi@example.com", subject="Hello", text="Plain body", html="<p>HTML body</p>", tags={"category": "test"})


@pytest.fixture(autouse=True)
def _clean_outbox():
    mail.OUTBOX.clear()
    yield
    mail.OUTBOX.clear()


def test_console_backend_can_save_emails_for_development(tmp_path):
    message_id = ConsoleMail(str(tmp_path / "outbox")).send(MESSAGE)
    [saved] = (tmp_path / "outbox").iterdir()
    data = json.loads(saved.read_text())
    assert data["to"] == "ravi@example.com" and data["html"] == "<p>HTML body</p>" and data["message_id"] == message_id
    assert mail.OUTBOX == [MESSAGE]


# --------------------------------------------------------------------------- Amazon SES


def ses_client():
    return boto3.client("sesv2", region_name="ap-south-1", aws_access_key_id="test", aws_secret_access_key="test")


def test_ses_sends_text_and_html_with_reply_to_tags_and_configuration_set():
    client = ses_client()
    expected = {
        "FromEmailAddress": "EduVerse AI <no-reply@learn.example.com>",
        "Destination": {"ToAddresses": ["ravi@example.com"]},
        "Content": {
            "Simple": {
                "Subject": {"Data": "Hello", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "Plain body", "Charset": "UTF-8"}, "Html": {"Data": "<p>HTML body</p>", "Charset": "UTF-8"}},
            }
        },
        "ReplyToAddresses": ["help@learn.example.com"],
        "ConfigurationSetName": "eduverse-events",
        "EmailTags": [{"Name": "category", "Value": "test"}],
    }
    with Stubber(client) as stub:
        stub.add_response("send_email", {"MessageId": "ses-123"}, expected)
        backend = SesMail("ap-south-1", "EduVerse AI <no-reply@learn.example.com>", "help@learn.example.com", "eduverse-events", client=client)
        assert backend.send(MESSAGE) == "ses-123"
        stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    ("code", "permanent"),
    [("MessageRejected", True), ("MailFromDomainNotVerifiedException", True), ("TooManyRequestsException", False), ("InternalFailure", False)],
)
def test_ses_errors_say_whether_a_retry_can_help(code, permanent):
    client = ses_client()
    with Stubber(client) as stub:
        stub.add_client_error("send_email", service_error_code=code, service_message="nope", http_status_code=400 if permanent else 500)
        with pytest.raises(MailError, match=code) as err:
            SesMail("ap-south-1", "no-reply@example.com", client=client).send(MESSAGE)
    assert err.value.permanent is permanent


def test_ses_network_errors_are_transient():
    class Down:
        def send_email(self, **_):
            raise EndpointConnectionError(endpoint_url="https://email.ap-south-1.amazonaws.com")

    with pytest.raises(MailError, match="unavailable") as err:
        SesMail("ap-south-1", "no-reply@example.com", client=Down()).send(MESSAGE)
    assert not err.value.permanent


# --------------------------------------------------------------------------- SMTP


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail = [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_smtp_uses_starttls_and_sends_text_with_an_html_alternative(fake_smtp):
    backend = SmtpMail("smtp://apikey:p%40ss@smtp.example.com:2525", "EduVerse AI <no-reply@learn.example.com>", "help@learn.example.com")
    message_id = backend.send(MESSAGE)
    server = fake_smtp.instances[0]
    assert (server.host, server.port) == ("smtp.example.com", 2525)
    assert server.calls == ["starttls", ("login", "apikey", "p@ss"), "quit"]
    sent = server.sent[0]
    assert (sent["To"], sent["Subject"], sent["Reply-To"], sent["Message-ID"]) == ("ravi@example.com", "Hello", "help@learn.example.com", message_id)
    assert sent.get_body(("plain",)).get_content().strip() == "Plain body"
    assert sent.get_body(("html",)).get_content().strip() == "<p>HTML body</p>"


def test_smtps_connects_with_tls_and_defaults_to_port_465(fake_smtp):
    SmtpMail("smtps://u:p@smtp.example.com", "no-reply@example.com").send(MESSAGE)
    assert fake_smtp.instances[0].port == 465 and "starttls" not in fake_smtp.instances[0].calls


@pytest.mark.parametrize(
    ("error", "permanent"),
    [
        (smtplib.SMTPRecipientsRefused({"ravi@example.com": (550, b"no such user")}), True),
        (smtplib.SMTPDataError(554, b"rejected"), True),
        (smtplib.SMTPDataError(451, b"try later"), False),
        (smtplib.SMTPServerDisconnected("gone"), False),
        (ConnectionRefusedError(), False),
    ],
)
def test_smtp_errors_say_whether_a_retry_can_help(fake_smtp, error, permanent):
    fake_smtp.fail = error
    with pytest.raises(MailError) as err:
        SmtpMail("smtp://smtp.example.com", "no-reply@example.com").send(MESSAGE)
    assert err.value.permanent is permanent


def test_bad_smtp_url_is_refused():
    with pytest.raises(ValueError, match="EDU_SMTP_URL"):
        SmtpMail("http://smtp.example.com", "no-reply@example.com")


def test_backend_follows_the_settings(monkeypatch):
    s = get_settings()
    assert isinstance(mail.make_backend(), ConsoleMail)
    monkeypatch.setattr(s, "mail_backend", "smtp")
    monkeypatch.setattr(s, "smtp_url", "smtp://smtp.example.com:587")
    assert isinstance(mail.make_backend(), SmtpMail)
    monkeypatch.setattr(s, "mail_backend", "ses")
    monkeypatch.setattr(s, "mail_from", "EduVerse AI <no-reply@learn.example.com>")
    backend = mail.make_backend()
    assert isinstance(backend, SesMail) and backend.client.meta.region_name == "ap-south-1"
    assert backend.sender == "EduVerse AI <no-reply@learn.example.com>"


# --------------------------------------------------------------------------- the mail.send job


def queue(message=MESSAGE):
    with SessionLocal() as db:
        job = queue_email(db, message)
        db.commit()
        return job.id


def job_row(job_id) -> Job:
    with SessionLocal() as db:
        return db.get(Job, job_id)


def test_queued_email_is_sent_by_a_worker_and_its_body_is_dropped(empty_db, worker):
    job_id = queue()
    assert mail.OUTBOX == []  # nothing goes out inside the request
    worker.drain()
    assert [m.subject for m in mail.OUTBOX] == ["Hello"]
    job = job_row(job_id)
    assert job.status == "done" and job.result["backend"] == "console" and job.result["message_id"]
    assert job.payload == {"message": {"to": "ravi@example.com", "subject": "Hello", "tags": {"category": "test"}}}


def test_provider_outage_retries_and_a_rejection_fails(empty_db, worker, monkeypatch):
    calls = []

    def flaky(message):
        calls.append(message.to)
        raise MailError("SES TooManyRequestsException: slow down")

    monkeypatch.setattr(mail, "send_now", flaky)
    retried = queue()
    worker.drain()
    job = job_row(retried)
    assert (job.status, job.attempts) == ("queued", 1) and "TooManyRequests" in job.error
    assert job.payload["message"]["text"] == "Plain body"  # kept for the retry

    def rejected(message):
        raise MailError("SES MessageRejected: address is on the suppression list", permanent=True)

    monkeypatch.setattr(mail, "send_now", rejected)
    failed = queue()
    worker.drain()
    job = job_row(failed)
    assert (job.status, job.attempts) == ("failed", 1) and "suppression" in job.error
    assert "text" not in job.payload["message"]  # dropped once the job ended


def test_staff_do_not_see_mail_jobs_in_the_content_studio(admin, worker):
    queue()
    assert admin.get(f"{API}/admin/jobs", params={"queue": "content"}).json() == []
    assert [j["kind"] for j in admin.get(f"{API}/admin/jobs", params={"queue": "mail"}).json()] == ["mail.send"]
    with SessionLocal() as db:
        assert db.scalar(select(Job.queue).where(Job.kind == "mail.send")) == "mail"
