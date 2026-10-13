"""Provider adapters driven through the real Anthropic and OpenAI SDKs over a mock HTTP transport.

Catches what stub objects cannot: wrong request parameters, wrong endpoints or headers, and
response shapes the adapters misread. Then every AI engine task goes through the gateway's live
path (prompt -> SDK -> JSON -> schema) instead of its offline fallback.
"""

import json

import anthropic
import httpx2
import openai
import pytest
from sqlalchemy import select

from app.ai import gateway
from app.ai.engines import code_review, examiner, language, mentor, questions, teacher
from app.ai.providers import clients
from app.ai.providers.base import ProviderError
from app.core.config import get_settings
from app.modules.catalog.models import Concept
from app.modules.content import service as content


class FakeAnthropicAPI:
    """Answers /v1/messages like the Messages API and records what the SDK sent."""

    def __init__(self):
        self.requests: list[httpx2.Request] = []
        self.reply_text = '{"text": "ok"}'
        self.stop_reason = "end_turn"
        self.status = 200

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx2.Response(self.status, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        body = json.loads(request.content)
        content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
        if self.stop_reason != "refusal":
            content.append({"type": "text", "text": self.reply_text})
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": content,
                "stop_reason": self.stop_reason,
                "stop_sequence": None,
                "stop_details": {"type": "refusal", "category": "bio", "explanation": "declined"} if self.stop_reason == "refusal" else None,
                "usage": {"input_tokens": 120, "output_tokens": 45},
            },
        )

    @property
    def last(self) -> tuple[httpx2.Request, dict]:
        return self.requests[-1], json.loads(self.requests[-1].content)


@pytest.fixture
def anthropic_api(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    fake = FakeAnthropicAPI()
    provider = clients.AnthropicProvider()
    provider._client = anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(fake)))
    clients.register_provider("anthropic", provider)
    return fake, provider


def test_heavy_and_standard_tiers_use_server_side_fallbacks(anthropic_api):
    fake, provider = anthropic_api
    out = provider.complete("system prompt", [{"role": "user", "content": "hi"}], "heavy", 300)
    request, body = fake.last
    assert request.url.path == "/v1/messages" and request.url.params.get("beta") == "true"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    assert body["fallbacks"] == "default" and body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] >= 16000 and body["system"] == "system prompt" and "thinking" not in body
    assert (out.text, out.model, out.input_tokens, out.output_tokens) == ('{"text": "ok"}', "claude-opus-5-5", 120, 45)


def test_light_tier_uses_the_plain_endpoint(anthropic_api):
    fake, provider = anthropic_api
    provider.complete("s", [{"role": "user", "content": "hi"}], "light", 300)
    request, body = fake.last
    assert request.url.params.get("beta") is None and "anthropic-beta" not in request.headers
    assert body["model"] == "claude-haiku-5-5" and "fallbacks" not in body


def test_fallbacks_can_be_switched_off(anthropic_api, monkeypatch):
    fake, provider = anthropic_api
    monkeypatch.setattr(get_settings(), "anthropic_server_fallbacks", False)
    provider.complete("s", [{"role": "user", "content": "hi"}], "heavy", 300)
    assert "fallbacks" not in fake.last[1]


@pytest.mark.parametrize(("stop_reason", "message"), [("refusal", r"declined \(bio\)"), ("max_tokens", "cut off")])
def test_refusals_and_truncation_become_provider_errors(anthropic_api, stop_reason, message):
    fake, provider = anthropic_api
    fake.stop_reason = stop_reason
    with pytest.raises(ProviderError, match=message):
        provider.complete("s", [{"role": "user", "content": "hi"}], "standard", 300)


def test_http_errors_become_provider_errors(anthropic_api):
    fake, provider = anthropic_api
    fake.status = 529
    with pytest.raises(ProviderError, match="anthropic"):
        provider.complete("s", [{"role": "user", "content": "hi"}], "standard", 300)


def test_openai_adapter(monkeypatch):
    sent = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        finish = "length" if len(sent) > 1 else "stop"
        return httpx2.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4.1-mini",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"text": "ok"}'}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
            },
        )

    provider = clients.OpenAIProvider()
    provider._client = openai.OpenAI(api_key="test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    out = provider.complete("sys", [{"role": "user", "content": "hi"}], "standard", 300)
    assert (out.text, out.input_tokens, out.output_tokens) == ('{"text": "ok"}', 9, 4)
    assert sent[0]["messages"][0] == {"role": "system", "content": "sys"} and sent[0]["model"] == "gpt-4.1-mini"
    with pytest.raises(ProviderError, match="cut off"):
        provider.complete("sys", [{"role": "user", "content": "hi"}], "standard", 300)


# --------------------------------------------------------------------------- every engine, live path


def engine_tasks(db) -> dict[str, gateway.Task]:
    concept = db.scalar(select(Concept).where(Concept.slug == "compound-interest"))
    lesson = content.find_lesson(db, concept.id, 1, "en").body
    _, course_id = content.exam_context_for(db, concept.id)
    rubric = [{"criterion": "Definition", "max_marks": 2, "expected_points": ["interest on interest"]}]
    progress = {"title": "SSC", "readiness": 0.4, "weak": [{"title": "Discount"}], "strong": []}
    return {
        "teacher.lesson": teacher.lesson_task(db, concept, 3, "te", course_id, "SSC CGL"),
        "tutor.chat": teacher.tutor_task(
            db, concept, lesson, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], "Why is CI bigger?", "en", course_id
        ),
        "teacher.flashcards": teacher.flashcards_task(db, concept, lesson, 4),
        "teacher.notes": teacher.notes_task(db, "Interest notes", "Compound interest is interest on interest. It grows faster than simple interest."),
        "questions.generate": questions.generate_task(db, concept, "mcq", "hard", 3, "SSC CGL", lesson, course_id),
        "solution.mistake_note": questions.mistake_note_task("CI on 1000 at 10% for 2 years?", "(b) 210", "(a) 200", "A = 1210", "Using SI"),
        "examiner.evaluate": examiner.evaluate_task("Define CI", rubric, "CI is interest on interest.", "It is interest on interest.", 50),
        "code.review": code_review.review_task("def f(x):\n    return x", "python", "Return x", "passed 1 of 1"),
        "language.chat": language.chat_task(
            "English", "A2", "interview", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}], "i am agree", "te"
        ),
        "mentor.note": mentor.mentor_task("Ravi", progress, [{"title": "Revise: Discount"}], {"accuracy": 0.6}),
        "career.guide": mentor.career_task("python developer", "B.Com", [], [{"slug": "python-fundamentals", "title": "Python", "domain": "technology"}]),
    }


def test_every_engine_task_runs_live_through_the_sdk(sdb, anthropic_api, monkeypatch):
    fake, _ = anthropic_api
    monkeypatch.setattr(get_settings(), "ai_primary", "anthropic")
    monkeypatch.setattr(get_settings(), "ai_fallback", "offline")
    tasks = engine_tasks(sdb)
    assert len(tasks) == 11
    for name, task in tasks.items():
        assert task.name == name
        fake.reply_text = "```json\n" + json.dumps(task.schema.model_validate(task.offline()).model_dump(mode="json")) + "\n```"
        res = gateway.run(sdb, task)
        assert res.provider == "anthropic" and not res.offline, name
        _, body = fake.last
        roles = [m["role"] for m in body["messages"]]
        assert roles[0] == "user" and roles[-1] == "user", (name, roles)
        assert all(a != b for a, b in zip(roles, roles[1:], strict=False)), (name, roles)  # strictly alternating turns
        assert all(isinstance(m["content"], str) and m["content"].strip() for m in body["messages"]), name
        assert body["system"].startswith(gateway.SYSTEM_PREAMBLE) and "JSON schema" in body["system"], name
        assert body["model"] == clients.AnthropicProvider().model_for(task.tier), name
    assert len(fake.requests) == 11  # no repair round trips were needed
