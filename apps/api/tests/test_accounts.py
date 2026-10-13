"""Account access: email verification, password reset, password change (with every old session
ended), invite-only registration, and the guarantees behind them: no account enumeration,
single-use hashed tokens, per-account email limits, and no secrets left in the jobs table."""

import re
import threading
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import API, make_actor
from sqlalchemy import select, update

from app.core import mail
from app.core.config import get_settings
from app.core.db import SessionLocal, utcnow
from app.core.errors import AppError
from app.core.security import create_access_token, hash_token
from app.jobs.models import Job
from app.modules.identity import service as identity
from app.modules.identity.models import AccountToken, AuditLog, Invite, User

PASSWORD = "password-123"


@pytest.fixture(autouse=True)
def _clean_outbox():
    mail.OUTBOX.clear()
    yield
    mail.OUTBOX.clear()


def emails_to(address: str) -> list[mail.Message]:
    return [m for m in mail.OUTBOX if m.to == address]


def token_from(message: mail.Message, path: str) -> str:
    url = re.search(r"https?://\S+", message.text).group(0)
    parts = urlsplit(url)
    assert parts.path == path, url
    return parse_qs(parts.query)["token"][0]


def register(client, email, invite_code=None, locale="en", name="Ravi"):
    body = {"email": email, "password": PASSWORD, "name": name, "preferred_locale": locale}
    if invite_code:
        body["invite_code"] = invite_code
    return client.post(f"{API}/auth/register", json=body)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def user_by_email(email) -> User:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.email == email))


# --------------------------------------------------------------------------- email verification


def test_registration_sends_a_verification_link_that_confirms_the_address(client, worker):
    r = register(client, "ravi@example.com")
    assert r.status_code == 201 and r.json()["user"]["email_verified"] is False
    access = r.json()["access_token"]
    assert mail.OUTBOX == []  # sent by a worker, not inside the request
    worker.drain()
    [message] = emails_to("ravi@example.com")
    assert message.subject == "Confirm your email for EduVerse AI" and message.tags == {"category": "verify_email"}
    token = token_from(message, "/verify-email")

    verified = client.post(f"{API}/auth/email/verify", json={"token": token})
    assert verified.status_code == 200 and verified.json()["email_verified"] is True
    assert client.get(f"{API}/me", headers=bearer(access)).json()["email_verified"] is True
    again = client.post(f"{API}/auth/email/verify", json={"token": token})  # the link clicked twice
    assert again.status_code == 200
    assert client.post(f"{API}/auth/email/verify", json={"token": "x" * 43}).status_code == 400
    assert client.post(f"{API}/auth/email/resend", headers=bearer(access)).status_code == 409


def test_emails_follow_the_learners_language_and_escape_html(client, worker):
    register(client, "sita@example.com", locale="te", name="<b>Sita</b>")
    worker.drain()
    [message] = emails_to("sita@example.com")
    assert "నిర్ధారించండి" in message.subject and "నమస్కారం <b>Sita</b>," in message.text
    assert "&lt;b&gt;Sita&lt;/b&gt;" in message.html and "<b>Sita</b>" not in message.html


def test_resend_replaces_the_old_link_and_stops_at_the_hourly_limit(client, worker):
    access = register(client, "ravi@example.com").json()["access_token"]
    worker.drain()
    first = token_from(emails_to("ravi@example.com")[0], "/verify-email")
    for _ in range(3):
        assert client.post(f"{API}/auth/email/resend", headers=bearer(access)).status_code == 202
        worker.drain()
    assert len(emails_to("ravi@example.com")) == 3  # 3 per hour, then the requests are ignored
    with SessionLocal() as db:
        last = db.scalars(select(Job).where(Job.kind == "account.verify_email").order_by(Job.created_at.desc())).first()
        assert last.result == {"sent": False, "reason": "hourly limit reached"}
    assert client.post(f"{API}/auth/email/verify", json={"token": first}).status_code == 400  # superseded
    latest = token_from(emails_to("ravi@example.com")[-1], "/verify-email")
    assert client.post(f"{API}/auth/email/verify", json={"token": latest}).status_code == 200


def test_expired_or_wrong_address_verification_links_are_refused(client, worker):
    register(client, "ravi@example.com")
    worker.drain()
    token = token_from(emails_to("ravi@example.com")[0], "/verify-email")
    with SessionLocal() as db:
        db.execute(update(AccountToken).values(expires_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    assert client.post(f"{API}/auth/email/verify", json={"token": token}).status_code == 400

    register(client, "kiran@example.com")
    worker.drain()
    token = token_from(emails_to("kiran@example.com")[0], "/verify-email")
    with SessionLocal() as db:
        db.execute(update(User).where(User.email == "kiran@example.com").values(email="kiran.new@example.com"))
        db.commit()
    assert client.post(f"{API}/auth/email/verify", json={"token": token}).status_code == 400  # sent to the old address


# --------------------------------------------------------------------------- password reset


def test_forgot_password_answers_the_same_for_unknown_addresses(client, worker):
    register(client, "ravi@example.com")
    worker.drain()
    mail.OUTBOX.clear()
    known = client.post(f"{API}/auth/password/forgot", json={"email": "Ravi@Example.com"})
    unknown = client.post(f"{API}/auth/password/forgot", json={"email": "nobody@example.com"})
    assert (known.status_code, unknown.status_code) == (202, 202) and known.json() == unknown.json()
    worker.drain()
    assert [m.to for m in mail.OUTBOX] == ["ravi@example.com"]
    with SessionLocal() as db:
        results = {j.payload["email"]: j.result for j in db.scalars(select(Job).where(Job.kind == "account.password_reset"))}
    assert results["nobody@example.com"] == {"sent": False, "reason": "no active account"}
    assert results["ravi@example.com"]["sent"] is True and results["ravi@example.com"]["backend"] == "console"


def test_reset_sets_a_new_password_and_ends_every_session(client, worker):
    r = register(client, "ravi@example.com")
    old_access, old_refresh = r.json()["access_token"], r.json()["refresh_token"]
    client.post(f"{API}/auth/password/forgot", json={"email": "ravi@example.com"})
    worker.drain()
    reset = [m for m in emails_to("ravi@example.com") if m.tags["category"] == "password_reset"][0]
    assert "30 minutes" in reset.text
    token = token_from(reset, "/reset-password")

    assert client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "short"}).status_code == 422
    assert client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "a-brand-new-password"}).status_code == 204
    assert client.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "another-password"}).status_code == 400  # single use

    assert client.get(f"{API}/me", headers=bearer(old_access)).status_code == 401  # access token dead at once
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "ravi@example.com", "password": PASSWORD}).status_code == 401
    login = client.post(f"{API}/auth/login", json={"email": "ravi@example.com", "password": "a-brand-new-password"})
    assert login.status_code == 200 and login.json()["user"]["email_verified"] is True  # the mailbox is proven
    worker.drain()
    assert emails_to("ravi@example.com")[-1].tags["category"] == "password_changed"
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog.action).where(AuditLog.action == "password_reset")) == "password_reset"


def test_reset_links_expire_and_are_limited_per_hour(client, worker):
    register(client, "ravi@example.com")
    for _ in range(4):
        client.post(f"{API}/auth/password/forgot", json={"email": "ravi@example.com"})
    worker.drain()
    resets = [m for m in emails_to("ravi@example.com") if m.tags["category"] == "password_reset"]
    assert len(resets) == 3
    latest = token_from(resets[-1], "/reset-password")
    assert (
        client.post(f"{API}/auth/password/reset", json={"token": token_from(resets[0], "/reset-password"), "new_password": "a-brand-new-password"}).status_code
        == 400
    )
    with SessionLocal() as db:
        db.execute(update(AccountToken).where(AccountToken.purpose == "reset").values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert client.post(f"{API}/auth/password/reset", json={"token": latest, "new_password": "a-brand-new-password"}).status_code == 400


def test_suspended_accounts_get_no_reset_email(client, worker):
    register(client, "ravi@example.com")
    with SessionLocal() as db:
        db.execute(update(User).values(status="suspended"))
        db.commit()
    client.post(f"{API}/auth/password/forgot", json={"email": "ravi@example.com"})
    worker.drain()
    assert all(m.tags["category"] != "password_reset" for m in mail.OUTBOX)


def test_secret_links_never_reach_the_database_in_clear(client, worker, admin_actor):
    register(client, "ravi@example.com")
    client.post(f"{API}/auth/password/forgot", json={"email": "ravi@example.com"})
    created = admin_actor.post(f"{API}/admin/invites", json={"email": "new@example.com", "send_email": True}).json()
    worker.drain()
    secrets_sent = [token_from(m, "/reset-password") for m in mail.OUTBOX if m.tags["category"] == "password_reset"]
    secrets_sent += [token_from(m, "/verify-email") for m in mail.OUTBOX if m.tags["category"] == "verify_email"]
    secrets_sent.append(created["code"])
    with SessionLocal() as db:
        stored = " ".join(f"{j.payload} {j.result} {j.checkpoint}" for j in db.scalars(select(Job)))
        hashes = set(db.scalars(select(AccountToken.token_hash))) | set(db.scalars(select(Invite.code_hash)))
    assert len(secrets_sent) == 3  # reset link, verification link, invite code
    assert not [s for s in secrets_sent if s in stored]
    assert {hash_token(s) for s in secrets_sent[:2]} <= hashes and identity.invite_hash(created["code"]) in hashes


# --------------------------------------------------------------------------- password change


def test_changing_the_password_keeps_this_session_and_ends_the_others(client, worker):
    first = register(client, "ravi@example.com").json()
    other = client.post(f"{API}/auth/login", json={"email": "ravi@example.com", "password": PASSWORD}).json()
    wrong = client.post(f"{API}/me/password", headers=bearer(first["access_token"]), json={"current_password": "nope", "new_password": "a-brand-new-password"})
    assert wrong.status_code == 400  # not 401: the session itself is fine
    changed = client.post(
        f"{API}/me/password", headers=bearer(first["access_token"]), json={"current_password": PASSWORD, "new_password": "a-brand-new-password"}
    )
    assert changed.status_code == 200
    assert client.get(f"{API}/me", headers=bearer(changed.json()["access_token"])).status_code == 200  # this tab continues
    assert client.get(f"{API}/me", headers=bearer(first["access_token"])).status_code == 401
    assert client.get(f"{API}/me", headers=bearer(other["access_token"])).status_code == 401  # the other device
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": changed.json()["refresh_token"]}).status_code == 200
    worker.drain()
    assert emails_to("ravi@example.com")[-1].subject == "Your EduVerse AI password was changed"


def test_access_tokens_from_before_token_versions_still_work(client):
    user_id = uuid.UUID(register(client, "ravi@example.com").json()["user"]["id"])
    legacy = create_access_token(user_id, "learner")  # version 0, like tokens issued before this change
    assert client.get(f"{API}/me", headers=bearer(legacy)).status_code == 200


# --------------------------------------------------------------------------- invites


@pytest.fixture
def admin_actor(client):
    return make_actor(client, "admin", name="Asha Admin")


def invite(admin_actor, **body) -> dict:
    r = admin_actor.post(f"{API}/admin/invites", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_invite_only_registration(client, admin_actor, monkeypatch):
    assert client.get(f"{API}/auth/options").json() == {"registration": "open"}
    assert register(client, "open@example.com").status_code == 201
    monkeypatch.setattr(get_settings(), "registration_mode", "invite")
    assert client.get(f"{API}/auth/options").json() == {"registration": "invite"}
    refused = register(client, "walkin@example.com")
    assert refused.status_code == 403 and "invitation" in refused.json()["detail"]
    created = invite(admin_actor, note="Pilot cohort 1", max_uses=2)
    assert re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", created["code"]) and created["link"].endswith(f"/register?invite={created['code']}")
    typed = created["code"].lower().replace("-", " ")  # people retype codes loosely
    assert register(client, "one@example.com", typed).status_code == 201
    assert register(client, "two@example.com", created["code"]).status_code == 201
    used_up = register(client, "three@example.com", created["code"])
    assert used_up.status_code == 400 and "not valid" in used_up.json()["detail"]
    assert register(client, "four@example.com", "AAAA-BBBB-CCCC-DDDD").status_code == 400
    assert user_by_email("three@example.com") is None
    with SessionLocal() as db:
        detail = db.scalar(
            select(AuditLog.detail).join(User, User.id == AuditLog.actor_id).where(User.email == "one@example.com", AuditLog.action == "register")
        )
    assert detail == {"invite": created["id"]}


def test_invites_can_be_bound_to_an_email_and_grant_the_reviewer_role(client, admin_actor):
    created = invite(admin_actor, email="Reviewer@Example.com", role="reviewer")
    assert register(client, "someone.else@example.com", created["code"]).status_code == 400
    r = register(client, "reviewer@example.com", created["code"])
    assert r.status_code == 201 and r.json()["user"]["role"] == "reviewer"
    assert admin_actor.post(f"{API}/admin/invites", json={"role": "admin"}).status_code == 422  # admins only via the seed


def test_expired_and_revoked_invites_are_refused_and_listed_with_their_status(client, admin_actor):
    expired, revoked, active = invite(admin_actor, note="expired"), invite(admin_actor, note="revoked"), invite(admin_actor, note="active")
    with SessionLocal() as db:
        db.execute(update(Invite).where(Invite.id == uuid.UUID(expired["id"])).values(expires_at=utcnow() - timedelta(days=1)))
        db.commit()
    r = admin_actor.delete(f"{API}/admin/invites/{revoked['id']}")
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert register(client, "a@example.com", expired["code"]).status_code == 400
    assert register(client, "b@example.com", revoked["code"]).status_code == 400
    assert register(client, "c@example.com", active["code"]).status_code == 201
    rows = {row["note"]: row for row in admin_actor.get(f"{API}/admin/invites").json()}
    assert {note: row["status"] for note, row in rows.items()} == {"expired": "expired", "revoked": "revoked", "active": "used"}
    assert all("code" not in row for row in rows.values())  # shown once, at creation
    assert admin_actor.delete(f"{API}/admin/invites/{uuid.uuid4()}").status_code == 404


def test_invites_can_be_emailed(client, admin_actor, worker):
    assert admin_actor.post(f"{API}/admin/invites", json={"send_email": True}).status_code == 400  # no address
    created = invite(admin_actor, email="friend@example.com", note="Pilot cohort 1", send_email=True)
    assert created["emailed"] is True
    worker.drain()
    [message] = emails_to("friend@example.com")
    assert created["code"] in message.text and created["link"] in message.text
    assert "Asha Admin invited you" in message.text and "ఆహ్వానించారు" in message.text


def test_only_admins_manage_invites(client):
    reviewer = make_actor(client, "reviewer")
    learner = make_actor(client, "learner")
    for actor in (reviewer, learner):
        assert actor.post(f"{API}/admin/invites", json={}).status_code == 403
        assert actor.get(f"{API}/admin/invites").status_code == 403


def test_two_sign_ups_racing_for_the_last_use_get_one_account(client, admin_actor):
    code = invite(admin_actor, max_uses=1)["code"]
    barrier, outcomes = threading.Barrier(2), []

    def sign_up(n):
        with SessionLocal() as db:
            barrier.wait()
            try:
                identity.register(db, f"racer{n}@example.com", PASSWORD, "Racer", "en", code, "127.0.0.1")
                outcomes.append("ok")
            except AppError:
                db.rollback()
                outcomes.append("refused")

    threads = [threading.Thread(target=sign_up, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["ok", "refused"]
    with SessionLocal() as db:
        assert db.scalar(select(Invite.uses)) == 1
