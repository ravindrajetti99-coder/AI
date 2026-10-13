"""Model provider adapters. Each is optional: it reports unavailable when its key is missing."""

import logging
import time

from app.ai.providers.base import ProviderError, ProviderResult, Tier
from app.core.config import get_settings, reveal

log = logging.getLogger("eduverse.ai")

THINKING_HEADROOM_TOKENS = 16_000
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
CHECK_PROMPT = [{"role": "user", "content": "Reply with the single word OK."}]


def key_hint(key: str) -> str:
    """Enough of a key to tell which one is loaded (e.g. during rotation), never the key itself."""
    return f"…{key[-4:]}" if len(key) >= 12 else ("set" if key else "")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self._client = None
        self.http_client = None  # tests plug in a mock transport here
        self._using_secondary = False
        self._schemas_rejected: set[str] = set()  # schema titles the API refused as structured outputs

    def available(self) -> bool:
        return bool(reveal(get_settings().anthropic_api_key))

    def model_for(self, tier: Tier) -> str:
        s = get_settings()
        return {"heavy": s.anthropic_model_heavy, "standard": s.anthropic_model_standard, "light": s.anthropic_model_light}[tier]

    def effort_for(self, tier: Tier) -> str:
        s = get_settings()
        return {"heavy": s.anthropic_effort_heavy, "standard": s.anthropic_effort_standard, "light": s.anthropic_effort_light}[tier]

    def _get_client(self):
        if self._client is None:
            import anthropic

            s = get_settings()
            key = reveal(s.anthropic_api_key_secondary if self._using_secondary else s.anthropic_api_key)
            extra = {"http_client": self.http_client} if self.http_client is not None else {}
            self._client = anthropic.Anthropic(api_key=key, timeout=s.ai_timeout_seconds, max_retries=2, **extra)
        return self._client

    def _switch_to_secondary(self) -> bool:
        """After the primary key is rejected: use the secondary one, if configured, from now on."""
        if self._using_secondary or not reveal(get_settings().anthropic_api_key_secondary):
            return False
        log.warning("Anthropic rejected the primary API key; switching to EDU_ANTHROPIC_API_KEY_SECONDARY")
        self._using_secondary, self._client = True, None
        return True

    def _create(self, params: dict, model: str):
        if get_settings().anthropic_server_fallbacks and "haiku" not in model:
            # On a safety decline the API re-runs the request on Anthropic's recommended model for
            # that refusal category (Claude API only; Haiku has no server-side fallback).
            return self._get_client().beta.messages.create(**params, betas=[SERVER_FALLBACK_BETA], fallbacks="default")
        return self._get_client().messages.create(**params)

    def _send(self, params: dict, model: str, schema_title: str):
        import anthropic

        for _ in range(3):  # at most: one key switch and one retry without the schema
            try:
                return self._create(params, model)
            except anthropic.AuthenticationError as exc:
                if not self._switch_to_secondary():
                    raise ProviderError(f"anthropic: API key rejected ({exc.status_code})", request_id=_request_id(exc)) from exc
            except anthropic.BadRequestError as exc:
                fmt = params.get("output_config", {}).get("format")
                if not fmt:
                    raise ProviderError(f"anthropic: bad request: {exc.message}", request_id=_request_id(exc)) from exc
                # Structured outputs reject some schemas; answer this request without one and stop
                # sending this schema (the gateway still validates and repairs the JSON).
                log.warning("Anthropic refused the %s schema as a structured output (%s); sending it as plain JSON", schema_title, exc.message)
                self._schemas_rejected.add(schema_title)
                params = {**params, "output_config": {k: v for k, v in params["output_config"].items() if k != "format"}}
                if not params["output_config"]:
                    params.pop("output_config")
            except anthropic.APIError as exc:  # rate limit, overload, network, timeout (after SDK retries)
                raise ProviderError(f"anthropic: {exc}", request_id=_request_id(exc)) from exc
        raise ProviderError("anthropic: request kept failing")

    def complete(
        self, system: str, messages: list[dict], tier: Tier, max_tokens: int, *, effort: str = "", schema: dict | None = None, cache_system: bool = False
    ) -> ProviderResult:
        s = get_settings()
        model = self.model_for(tier)
        params = {
            "model": model,
            # Current Claude models think before answering and thinking tokens count against
            # max_tokens, so leave headroom; prompts keep the visible answer short.
            "max_tokens": max(max_tokens, THINKING_HEADROOM_TOKENS),
            # A cache breakpoint on the system prompt: every call of the same task (and variant)
            # shares it, so later calls read it from the cache at a fraction of the input price.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache_system else system,
            "messages": messages,
        }
        output_config: dict = {}
        effort = effort or self.effort_for(tier)
        if effort:
            output_config["effort"] = effort
        schema_title = str((schema or {}).get("title", ""))
        if schema and s.ai_structured_outputs and schema_title not in self._schemas_rejected:
            from anthropic import transform_schema  # drops constraints the API can't enforce; the gateway validates them

            output_config["format"] = {"type": "json_schema", "schema": transform_schema(schema)}
        if output_config:
            params["output_config"] = output_config

        resp = self._send(params, model, schema_title)
        request_id = getattr(resp, "_request_id", None) or ""
        served = getattr(resp, "model", None) or model
        if resp.stop_reason == "refusal":
            category = getattr(getattr(resp, "stop_details", None), "category", None) or "unspecified"
            raise ProviderError(
                f"anthropic: request declined ({category})", request_id=request_id, refusal_category=category, stop_reason="refusal", model=served
            )
        if resp.stop_reason == "max_tokens":
            raise ProviderError("anthropic: response cut off at max_tokens", request_id=request_id, stop_reason="max_tokens", model=served)
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            text="".join(block.text for block in resp.content if block.type == "text"),
            model=served,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            requested_model=model,
            request_id=request_id,
            stop_reason=resp.stop_reason or "",
        )

    def check(self, tier: Tier, live: bool = False) -> dict:
        """Free by default: count_tokens proves the key and the model id. `live` sends a tiny real
        request (a few hundred tokens) through the same path as production calls."""
        import anthropic

        model = self.model_for(tier)
        started = time.monotonic()
        out = {"provider": self.name, "tier": tier, "model": model, "effort": self.effort_for(tier), "mode": "live" if live else "count_tokens"}
        try:
            if live:
                result = self.complete("You are a health check.", CHECK_PROMPT, tier, 1000, effort="low")
                out.update(ok="OK" in result.text.upper(), served_model=result.model, detail=result.text.strip()[:40], request_id=result.request_id)
            else:
                counted = self._get_client().messages.count_tokens(model=model, messages=CHECK_PROMPT)
                out.update(ok=True, detail=f"{counted.input_tokens} input tokens")
        except ProviderError as exc:
            out.update(ok=False, detail=str(exc), request_id=exc.request_id)
        except anthropic.APIError as exc:
            out.update(ok=False, detail=f"{type(exc).__name__}: {getattr(exc, 'message', exc)}", request_id=_request_id(exc))
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
        return out


def _request_id(exc) -> str:
    return getattr(exc, "request_id", None) or ""


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self._client = None

    def available(self) -> bool:
        return bool(reveal(get_settings().openai_api_key))

    def model_for(self, tier: Tier) -> str:
        s = get_settings()
        return {"heavy": s.openai_model_heavy, "standard": s.openai_model_standard, "light": s.openai_model_light}[tier]

    def _get_client(self):
        if self._client is None:
            import openai

            s = get_settings()
            self._client = openai.OpenAI(api_key=reveal(s.openai_api_key), timeout=s.ai_timeout_seconds, max_retries=2)
        return self._client

    def complete(
        self, system: str, messages: list[dict], tier: Tier, max_tokens: int, *, effort: str = "", schema: dict | None = None, cache_system: bool = False
    ) -> ProviderResult:
        model = self.model_for(tier)  # OpenAI caches long prompts on its own; effort and schemas are Claude-specific here
        try:
            resp = self._get_client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, *messages],
            )
        except Exception as exc:
            raise ProviderError(f"openai: {exc}") from exc
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise ProviderError("openai: response cut off at max_tokens", stop_reason="length", model=model)
        usage = getattr(resp, "usage", None)
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        return ProviderResult(
            text=choice.message.content or "",
            model=getattr(resp, "model", None) or model,
            input_tokens=(getattr(usage, "prompt_tokens", 0) or 0) - cached,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cache_read_tokens=cached,
            requested_model=model,
            request_id=getattr(resp, "_request_id", None) or "",
            stop_reason=choice.finish_reason or "",
        )

    def check(self, tier: Tier, live: bool = False) -> dict:
        model = self.model_for(tier)
        started = time.monotonic()
        out = {"provider": self.name, "tier": tier, "model": model, "effort": "", "mode": "live" if live else "models.retrieve"}
        try:
            if live:
                result = self.complete("You are a health check.", CHECK_PROMPT, tier, 20)
                out.update(ok="OK" in result.text.upper(), served_model=result.model, detail=result.text.strip()[:40])
            else:
                self._get_client().models.retrieve(model)
                out.update(ok=True, detail="model available")
        except Exception as exc:
            out.update(ok=False, detail=f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
        return out


_REGISTRY = {"anthropic": AnthropicProvider(), "openai": OpenAIProvider()}


def get_provider(name: str):
    return _REGISTRY.get(name)


def register_provider(name: str, provider) -> None:
    """Used by tests to plug in a fake provider."""
    _REGISTRY[name] = provider
