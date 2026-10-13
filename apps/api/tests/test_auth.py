from conftest import API, make_actor
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password, verify_password
from app.modules.identity.models import AuditLog, RefreshToken, User


def register(client, email="anu@example.com", password="password-123", name="Anu"):
    return client.post(f"{API}/auth/register", json={"email": email, "password": password, "name": name})


def test_register_login_and_me(client):
    r = register(client, email="Anu@Example.com ".strip())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "anu@example.com" and body["user"]["role"] == "learner"
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert "edu_refresh" in r.cookies
    me = client.get(f"{API}/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["profile"]["daily_minutes_goal"] == 60

    login = client.post(f"{API}/auth/login", json={"email": "ANU@example.com", "password": "password-123"})
    assert login.status_code == 200


def test_duplicate_and_bad_credentials(client):
    assert register(client).status_code == 201
    dup = register(client)
    assert dup.status_code == 409 and dup.headers["content-type"].startswith("application/problem+json")
    assert client.post(f"{API}/auth/login", json={"email": "anu@example.com", "password": "nope-nope"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"}).status_code == 401
    short = register(client, email="b@example.com", password="short")
    assert short.status_code == 422 and short.json()["title"] == "Validation error"


def test_protected_routes_need_a_valid_token(client):
    assert client.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_refresh_rotates_and_reuse_revokes_the_family(client):
    first = register(client).json()["refresh_token"]
    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first

    # Replaying the spent token is treated as theft: the whole session family dies.
    replay = client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401 and "reuse" in replay.json()["detail"]
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": second}).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "refresh_reuse_detected"))
        assert all(t.revoked_at for t in db.scalars(select(RefreshToken)).all())


def test_refresh_and_logout_with_the_cookie(client):
    register(client)  # TestClient keeps the httpOnly cookie for the /auth path
    r = client.post(f"{API}/auth/refresh")
    assert r.status_code == 200
    token = r.json()["refresh_token"]
    out = client.post(f"{API}/auth/logout")
    assert out.status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": token}).status_code == 401
    client.cookies.clear()
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_suspended_users_are_locked_out(client):
    reg = register(client).json()
    admin = make_actor(client, "admin")
    r = admin.patch(f"{API}/admin/users/{reg['user']['id']}", json={"status": "suspended"})
    assert r.status_code == 200
    me = client.get(f"{API}/me", headers={"Authorization": f"Bearer {reg['access_token']}"})
    assert me.status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "anu@example.com", "password": "password-123"}).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": reg["refresh_token"]}).status_code == 401


def test_admin_user_management_is_admin_only(client):
    learner = make_actor(client, "learner")
    reviewer = make_actor(client, "reviewer")
    admin = make_actor(client, "admin")
    assert learner.get(f"{API}/admin/users").status_code == 403
    assert reviewer.get(f"{API}/admin/users").status_code == 403
    users = admin.get(f"{API}/admin/users", params={"q": "reviewer"}).json()
    assert [u["email"] for u in users] == [reviewer.email]
    promoted = admin.patch(f"{API}/admin/users/{learner.id}", json={"role": "reviewer"})
    assert promoted.json()["role"] == "reviewer"
    assert admin.patch(f"{API}/admin/users/{learner.id}", json={"role": "superuser"}).status_code == 422


def test_profile_update(client):
    me = make_actor(client)
    r = me.patch(f"{API}/me", json={"name": "Ravi K", "preferred_locale": "te", "daily_minutes_goal": 90, "target_exams": ["ssc-cgl-tier1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Ravi K" and body["preferred_locale"] == "te"
    assert body["profile"]["daily_minutes_goal"] == 90 and body["profile"]["target_exams"] == ["ssc-cgl-tier1"]
    assert me.patch(f"{API}/me", json={"daily_minutes_goal": 5}).status_code == 422


def test_auth_endpoints_are_rate_limited(client):
    codes = [client.post(f"{API}/auth/login", json={"email": "x@example.com", "password": "whatever1"}).status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429


def test_long_passphrases_stay_fully_significant():
    base = "correct horse battery staple " * 4  # > 72 bytes, bcrypt's own limit
    hashed = hash_password(base + "A")
    assert verify_password(base + "A", hashed)
    assert not verify_password(base + "B", hashed)
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_passwords_are_not_stored_in_plain_text(client):
    register(client)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "anu@example.com"))
        assert "password-123" not in user.password_hash and user.password_hash.startswith("$2")
