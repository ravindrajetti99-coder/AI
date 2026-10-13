"""Production AI configuration: secrets, per-tier effort, prompt caching, structured outputs, key
rotation, cost tracking (cache reads and writes, refusals, server-side fallbacks), spend cap and
prompt-size limits, task overrides, the smoke check and its admin endpoints. The Anthropic adapter
runs through the real SDK over a mock HTTP transport."""

import json
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from conftest import API, make_actor
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from test_gateway import FakeProvider, task

from app.ai import check as ai_check
from app.ai import gateway
from app.ai.providers import clients
from app.ai.providers.base import ProviderError, ProviderResult
from app.core import mail
from app.core.config import Settings, TaskOverride, get_settings, reveal, secrets_dir
from app.core.db import SessionLocal
from app.jobs.backends import DatabaseQueue
from app.jobs.models import Job
from app.modules.identity import service as identity
from app.modules.ingest.models import LlmCall

PRIMARY_KEY = "sk-ant-primary-key-0001"
SECONDARY_KEY = "sk-ant-secondary-key-0002"


@pytest.fixture(autouse=True)
def _fresh_spend():
    gateway.reset_spend_cache()
    gateway._alerted_days.clear()
    yield
    gateway.reset_spend_cache()
    gateway._alerted_days.clear()


class FakeClaude:
    """Answers the Messages and token-counting endpoints like the Claude API, with knobs."""

    def __init__(self):
        self.requests: list[httpx2.Request] = []
        self.reply = '{"text": "4"}'
        self.stop_reason = "end_turn"
        self.category = None
        self.served_model = None
        self.usage = {"input_tokens": 120, "output_tokens": 45, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.reject_schemas = False
        self.bad_keys: set[str] = set()

    def bodies(self, path="/v1/messages") -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        n = len(self.requests)
        if request.headers.get("x-api-key") in self.bad_keys:
            return httpx2.Response(
                401, headers={"request-id": f"req_auth{n}"}, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
            )
        body = json.loads(request.content)
        if request.url.path == "/v1/messages/count_tokens":
            return httpx2.Response(200, headers={"request-id": f"req_count{n}"}, json={"input_tokens": 14})
        if self.reject_schemas and "format" in body.get("output_config", {}):
            error = {"type": "invalid_request_error", "message": "output_config.format.schema: recursive schemas are not supported"}
            return httpx2.Response(400, headers={"request-id": f"req_bad{n}"}, json={"type": "error", "error": error})
        content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
        if self.stop_reason != "refusal":
            content.append({"type": "text", "text": self.reply})
        refusal = {"type": "refusal", "category": self.category, "explanation": "declined"} if self.stop_reason == "refusal" else None
        message = {
            "id": f"msg_{n}",
            "type": "message",
            "role": "assistant",
            "model": self.served_model or body["model"],
            "content": content,
            "stop_reason": self.stop_reason,
            "stop_sequence": None,
            "stop_details": refusal,
            "usage": self.usage,
        }
        return httpx2.Response(200, headers={"request-id": f"req_msg{n}"}, json=message)


@pytest.fixture
def claude(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", SecretStr(PRIMARY_KEY))
    monkeypatch.setattr(s, "ai_primary", "anthropic")
    monkeypatch.setattr(s, "ai_fallback", "offline")
    fake = FakeClaude()
    provider = clients.AnthropicProvider()
    provider.http_client = httpx2.Client(transport=httpx2.MockTransport(fake))
    clients.register_provider("anthropic", provider)
    return fake, provider


def calls(db) -> list[LlmCall]:
    return db.scalars(select(LlmCall).order_by(LlmCall.created_at)).all()


# --------------------------------------------------------------------------- secrets


def test_secrets_never_appear_in_settings_output():
    s = Settings(anthropic_api_key=PRIMARY_KEY, secret_key="jwt-secret-value-0123456789", smtp_url="smtp://u:smtp-pass@h:587", admin_password="admin-pass-123")
    shown = f"{s!r} {s} {s.model_dump_json()}"
    for secret in (PRIMARY_KEY, "jwt-secret-value-0123456789", "smtp-pass", "admin-pass-123"):
        assert secret not in shown
    assert reveal(s.anthropic_api_key) == PRIMARY_KEY and reveal(s.smtp_url).endswith("@h:587")
    assert reveal("plain") == "plain" and reveal(None) == ""


def test_secrets_can_come_from_files(tmp_path, monkeypatch):
    (tmp_path / "EDU_ANTHROPIC_API_KEY").write_text(PRIMARY_KEY)
    (tmp_path / "EDU_SECRET_KEY").write_text("jwt-secret-from-a-file-0123456789")
    monkeypatch.setenv("EDU_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("EDU_ANTHROPIC_API_KEY")  # the test harness sets it empty, and a set variable wins
    assert secrets_dir() == str(tmp_path)
    s = Settings(_secrets_dir=secrets_dir())
    assert reveal(s.anthropic_api_key) == PRIMARY_KEY and reveal(s.secret_key) == "jwt-secret-from-a-file-0123456789"
    monkeypatch.setenv("EDU_ANTHROPIC_API_KEY", SECONDARY_KEY)  # the environment wins over files
    assert reveal(Settings(_secrets_dir=secrets_dir()).anthropic_api_key) == SECONDARY_KEY
    monkeypatch.setenv("EDU_SECRETS_DIR", str(tmp_path / "missing"))
    assert secrets_dir() is None


def test_task_overrides_are_parsed_and_validated(monkeypatch):
    monkeypatch.setenv("EDU_AI_TASK_OVERRIDES", '{"examiner.evaluate": {"effort": "high", "max_tokens": 3000}}')
    assert Settings().ai_task_overrides["examiner.evaluate"] == TaskOverride(effort="high", max_tokens=3000)
    with pytest.raises(ValidationError):
        Settings(ai_task_overrides={"x": {"tier": "huge"}})
    with pytest.raises(ValidationError):
        Settings(ai_task_overrides={"x": {"temperature": 0.2}})  # unknown fields are typos, not silently ignored


# --------------------------------------------------------------------------- the Anthropic adapter


def test_effort_prompt_cache_and_schema_are_sent_and_usage_is_read(claude):
    fake, provider = claude
    fake.usage = {"input_tokens": 30, "output_tokens": 45, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0}
    schema = {"title": "Answer", "type": "object", "properties": {"text": {"type": "string", "maxLength": 50}}, "required": ["text"]}
    out = provider.complete("static system prompt", [{"role": "user", "content": "hi"}], "standard", 300, schema=schema, cache_system=True)
    [body] = fake.bodies()
    assert body["system"] == [{"type": "text", "text": "static system prompt", "cache_control": {"type": "ephemeral"}}]
    assert body["output_config"]["effort"] == "medium" and body["model"] == "claude-sonnet-5-5"
    sent = body["output_config"]["format"]
    assert sent["type"] == "json_schema" and sent["schema"]["additionalProperties"] is False
    assert "maxLength" not in sent["schema"]["properties"]["text"]  # the API can't enforce it; the gateway validates it
    assert (out.cache_read_tokens, out.cache_write_tokens, out.input_tokens, out.output_tokens) == (900, 0, 30, 45)
    assert out.request_id == "req_msg1" and out.requested_model == out.model == "claude-sonnet-5-5" and out.stop_reason == "end_turn"


def test_light_tier_effort_and_switches_for_caching_and_schemas(claude, monkeypatch):
    fake, provider = claude
    monkeypatch.setattr(get_settings(), "ai_structured_outputs", False)
    provider.complete("sys", [{"role": "user", "content": "hi"}], "light", 300, schema={"title": "A", "type": "object"}, cache_system=False)
    [body] = fake.bodies()
    assert body["system"] == "sys" and body["output_config"] == {"effort": "low"} and body["model"] == "claude-haiku-5-5"
    monkeypatch.setattr(get_settings(), "anthropic_effort_light", "")
    provider.complete("sys", [{"role": "user", "content": "hi"}], "light", 300)
    assert "output_config" not in fake.bodies()[-1]  # "" leaves effort to the model's default


def test_a_rejected_schema_is_retried_without_it_and_remembered(claude):
    fake, provider = claude
    fake.reject_schemas = True
    schema = {"title": "Tree", "type": "object"}
    out = provider.complete("sys", [{"role": "user", "content": "hi"}], "heavy", 300, schema=schema)
    assert out.text == '{"text": "4"}'
    first, retry = fake.bodies()
    assert "format" in first["output_config"] and retry["output_config"] == {"effort": "medium"}
    provider.complete("sys", [{"role": "user", "content": "hi"}], "heavy", 300, schema=schema)
    assert len(fake.bodies()) == 3 and "format" not in fake.bodies()[-1]["output_config"]  # not tried again


def test_a_rejected_primary_key_switches_to_the_secondary(claude, monkeypatch):
    fake, provider = claude
    fake.bad_keys = {PRIMARY_KEY}
    with pytest.raises(ProviderError, match="API key rejected") as err:
        provider.complete("sys", [{"role": "user", "content": "hi"}], "standard", 300)
    assert err.value.request_id == "req_auth1"
    monkeypatch.setattr(get_settings(), "anthropic_api_key_secondary", SecretStr(SECONDARY_KEY))
    assert provider.complete("sys", [{"role": "user", "content": "hi"}], "standard", 300).text == '{"text": "4"}'
    provider.complete("sys", [{"role": "user", "content": "hi"}], "standard", 300)
    assert [r.headers["x-api-key"] for r in fake.requests[1:]] == [PRIMARY_KEY, SECONDARY_KEY, SECONDARY_KEY]


# --------------------------------------------------------------------------- cost tracking


def test_cost_includes_cache_reads_and_writes():
    cost = gateway.estimate_cost("heavy", 1000, 500, "claude-opus-5-5", cache_read=2000, cache_write=3000)
    assert cost == pytest.approx((1000 * 4.0 + 500 * 20.0 + 2000 * 0.20 + 3000 * 4.0 * 1.25) / 1e6)
    assert gateway.estimate_cost("light", 1000, 100, "claude-haiku-5-5") == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)
    long_prompt = gateway.estimate_cost("light", 150_000, 100, "claude-haiku-5-5")  # above 100K: the long-context price
    assert long_prompt == pytest.approx((150_000 * 0.50 + 100 * 2.50) / 1e6)
    assert gateway.estimate_cost("heavy", 1000, 0, "unknown-model") == pytest.approx(1000 * 4.0 / 1e6)  # tier estimate


def test_calls_are_metered_with_cache_tokens_effort_and_request_ids(db, claude):
    fake, _ = claude
    fake.usage = {"input_tokens": 40, "output_tokens": 60, "cache_read_input_tokens": 1500, "cache_creation_input_tokens": 0}
    res = gateway.run(db, task())
    assert res.provider == "anthropic" and res.data.text == "4"
    [call] = calls(db)
    assert (call.input_tokens, call.output_tokens, call.cache_read_tokens, call.cache_write_tokens) == (40, 60, 1500, 0)
    assert (call.effort, call.request_id, call.stop_reason, call.status) == ("medium", "req_msg1", "end_turn", "ok")
    assert call.cost_usd == pytest.approx((40 * 2.0 + 60 * 10.0 + 1500 * 0.20) / 1e6)


def test_refusals_and_server_side_fallbacks_are_recorded(db, claude, admin):
    fake, _ = claude
    fake.stop_reason, fake.category = "refusal", "bio"
    assert gateway.run(db, task()).offline  # the whole chain declined: offline answer
    fake.stop_reason, fake.category, fake.served_model = "end_turn", None, "claude-opus-5"
    gateway.run(db, task())
    db.commit()
    refusal, offline, fallback = calls(db)
    assert (refusal.status, refusal.refusal_category, refusal.stop_reason, refusal.request_id) == ("refusal", "bio", "refusal", "req_msg1")
    assert offline.provider == "offline"
    assert (fallback.model, fallback.requested_model, fallback.status) == ("claude-opus-5", "claude-sonnet-5-5", "ok")
    day = admin.get(f"{API}/admin/ai/status").json()["last_24h"]
    assert (day["refusals"], day["fallbacks"], day["offline_answers"], day["calls"]) == (1, 1, 1, 3)


# --------------------------------------------------------------------------- limits


def test_cache_reads_do_not_use_up_the_daily_budget(db, claude, monkeypatch):
    fake, _ = claude
    user = identity.create_user(db, "budget@example.com", "password-123", "B")
    fake.usage = {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 70}
    gateway.run(db, task(), user.id)
    assert gateway.tokens_used_today(db, user.id) == 10 + 70 + 20


def test_spend_cap_switches_to_offline_and_alerts_admins_once(db, monkeypatch, worker):
    s = get_settings()
    monkeypatch.setattr(s, "ai_daily_spend_cap_usd", 1.0)
    monkeypatch.setattr(s, "ai_primary", "anthropic")
    monkeypatch.setattr(s, "ai_fallback", "offline")
    primary = FakeProvider("anthropic", ['{"text": "4"}'] * 3, model="claude-sonnet-5-5")
    clients.register_provider("anthropic", primary)
    identity.create_user(db, "boss@example.com", "password-123", "Boss", role="admin")
    db.add(LlmCall(feature="old", provider="anthropic", model="claude-opus-5-5", cost_usd=5.0, created_at=datetime.now(UTC) - timedelta(days=2)))
    db.add(LlmCall(feature="today", provider="anthropic", model="claude-opus-5-5", cost_usd=0.85))
    db.commit()
    assert not gateway.run(db, task()).offline  # 85% of the cap: still live, but admins are told
    assert not gateway.run(db, task()).offline
    db.add(LlmCall(feature="today", provider="anthropic", model="claude-opus-5-5", cost_usd=0.2))
    db.commit()
    gateway.reset_spend_cache()
    capped = gateway.run(db, task())
    assert capped.offline and "daily AI limit" in capped.note and len(primary.calls) == 2
    with SessionLocal() as other:
        alerts = other.scalars(select(Job).where(Job.kind == "mail.send")).all()
    assert [a.payload["message"]["to"] for a in alerts] == ["boss@example.com"]  # one email, not one per call
    db.commit()
    mail.OUTBOX.clear()
    worker.drain()
    assert [m.subject for m in mail.OUTBOX] == ["EduVerse AI: AI spend is close to the daily cap"]


def test_long_chat_history_is_trimmed_oldest_first():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "x" * 300} for i in range(10)]
    history.append({"role": "user", "content": "latest question"})
    kept = gateway.fit_messages("system", history, limit=400)
    assert kept[-1]["content"] == "latest question" and kept[0]["role"] == "user"
    assert all(a["role"] != b["role"] for a, b in zip(kept, kept[1:], strict=False))
    assert len(kept) < len(history) and kept == history[-len(kept) :]
    assert gateway.fit_messages("system", [{"role": "user", "content": "y" * 10_000}], limit=10)[0]["content"] == "y" * 10_000


def test_task_overrides_change_tier_effort_tokens_and_caching(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_primary", "anthropic")
    monkeypatch.setattr(s, "ai_task_overrides", {"test.answer": TaskOverride(tier="heavy", effort="high", max_tokens=5000, prompt_cache=False)})
    primary = FakeProvider("anthropic", ['{"text": "4"}'], model="claude-opus-5-5")
    clients.register_provider("anthropic", primary)
    gateway.run(db, task())
    [opts] = primary.options
    assert (opts["tier"], opts["effort"], opts["max_tokens"], opts["cache_system"]) == ("heavy", "high", 5000, False)
    assert opts["schema"]["title"] == "Answer"
    assert calls(db)[0].effort == "high"


# --------------------------------------------------------------------------- smoke check


def test_smoke_check_uses_free_token_counting(claude):
    fake, _ = claude
    rows = ai_check.run_checks()
    assert [(r["tier"], r["model"], r["ok"], r["mode"]) for r in rows] == [
        ("heavy", "claude-opus-5-5", True, "count_tokens"),
        ("standard", "claude-sonnet-5-5", True, "count_tokens"),
        ("light", "claude-haiku-5-5", True, "count_tokens"),
    ]
    assert {r.url.path for r in fake.requests} == {"/v1/messages/count_tokens"}  # no billed calls


def test_live_smoke_check_and_failures(claude, capsys):
    fake, _ = claude
    fake.reply = "OK"
    assert all(r["ok"] and r["mode"] == "live" for r in ai_check.run_checks(live=True))
    assert len(fake.bodies()) == 3 and all(b["output_config"]["effort"] == "low" for b in fake.bodies())
    fake.bad_keys = {PRIMARY_KEY}
    rows = ai_check.run_checks()
    assert not any(r["ok"] for r in rows) and rows[0]["request_id"].startswith("req_auth")
    assert ai_check.main([]) == 1
    printed = capsys.readouterr().out
    assert "FAIL" in printed and PRIMARY_KEY not in printed and "…0001" in printed  # a hint, never the key


def test_smoke_check_without_keys(monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "ai_fallback", "openai")
    rows = ai_check.run_checks()
    assert [(r["provider"], r["ok"]) for r in rows] == [("anthropic", None), ("openai", None)]
    assert ai_check.main([]) == 0 and ai_check.main(["--require"]) == 1
    assert "offline engines" in capsys.readouterr().out


def test_ai_admin_endpoints(admin, learner, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", SecretStr(PRIMARY_KEY))
    reviewer = make_actor(admin.client, "reviewer")
    status = admin.get(f"{API}/admin/ai/status").json()
    assert status["config"]["keys"]["anthropic"] == "…0001" and status["config"]["effort"]["light"] == "low"
    assert status["config"]["models"]["heavy"] == "claude-opus-5-5" and status["last_24h"]["spend_cap_usd"] == 0.0
    assert PRIMARY_KEY not in json.dumps(status)
    assert "keys" not in reviewer.get(f"{API}/admin/ai/status").json()["config"]  # hints are for admins
    assert learner.get(f"{API}/admin/ai/status").status_code == 403
    assert reviewer.post(f"{API}/admin/ai/check").status_code == 403

    provider = clients.AnthropicProvider()
    fake = FakeClaude()
    provider.http_client = httpx2.Client(transport=httpx2.MockTransport(fake))
    clients.register_provider("anthropic", provider)
    checked = admin.post(f"{API}/admin/ai/check").json()
    assert checked["ok"] and checked["configured"]
    assert [r["tier"] for r in checked["results"] if r["ok"]] == ["heavy", "standard", "light"]
    usage = admin.get(f"{API}/admin/ai-usage").json()
    assert usage["rows"] == [] or {"cache_read_tokens", "cache_write_tokens"} <= set(usage["rows"][0])


# --------------------------------------------------------------------------- job concurrency


def test_queue_concurrency_cap_holds_back_extra_jobs(empty_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_queue_concurrency", {"content": 1})
    with SessionLocal() as db:
        for queue in ("content", "content", "mail"):
            db.add(Job(kind="x", queue=queue, payload={}))
        db.commit()
    backend = DatabaseQueue()
    now = datetime.now(UTC) + timedelta(seconds=1)
    first = backend.claim("w1", None, now)
    second = backend.claim("w2", None, now)
    assert first and second and backend.claim("w3", None, now) is None  # the second content job waits
    with SessionLocal() as db:
        running = sorted(db.scalars(select(Job.queue).where(Job.status == "running")))
    assert running == ["content", "mail"]


def test_provider_results_default_to_no_cache_tokens():
    r = ProviderResult(text="x", model="m")
    assert (r.cache_read_tokens, r.cache_write_tokens, r.request_id) == (0, 0, "")
