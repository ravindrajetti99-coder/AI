"""Model provider adapters. Each is optional: it reports unavailable when its key is missing."""

from app.ai.providers.base import ProviderError, ProviderResult, Tier
from app.core.config import get_settings

THINKING_HEADROOM_TOKENS = 16_000


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self._client = None

    def available(self) -> bool:
        return bool(get_settings().anthropic_api_key)

    def model_for(self, tier: Tier) -> str:
        s = get_settings()
        return {"heavy": s.anthropic_model_heavy, "standard": s.anthropic_model_standard, "light": s.anthropic_model_light}[tier]

    def _get_client(self):
        if self._client is None:
            import anthropic

            s = get_settings()
            self._client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.ai_timeout_seconds, max_retries=2)
        return self._client

    def complete(self, system: str, messages: list[dict], tier: Tier, max_tokens: int) -> ProviderResult:
        model = self.model_for(tier)
        params = {
            "model": model,
            # Current Claude models think before answering and thinking tokens count against
            # max_tokens, so leave headroom; prompts keep the visible answer short.
            "max_tokens": max(max_tokens, THINKING_HEADROOM_TOKENS),
            "system": system,
            "messages": messages,
        }
        try:
            if get_settings().anthropic_server_fallbacks and "haiku" not in model:
                # On a safety decline the API re-runs the request on Anthropic's recommended model
                # for that refusal category (Claude API only; Haiku has no server-side fallback).
                resp = self._get_client().beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                resp = self._get_client().messages.create(**params)
        except Exception as exc:  # network, auth, rate limit, overload
            raise ProviderError(f"anthropic: {exc}") from exc
        if resp.stop_reason == "refusal":
            category = getattr(getattr(resp, "stop_details", None), "category", None)
            raise ProviderError(f"anthropic: request declined ({category or 'refusal'})")
        if resp.stop_reason == "max_tokens":
            raise ProviderError("anthropic: response cut off at max_tokens")
        text = "".join(block.text for block in resp.content if block.type == "text")
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            text=text,
            model=getattr(resp, "model", None) or model,  # the served model, which differs after a fallback
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self._client = None

    def available(self) -> bool:
        return bool(get_settings().openai_api_key)

    def model_for(self, tier: Tier) -> str:
        s = get_settings()
        return {"heavy": s.openai_model_heavy, "standard": s.openai_model_standard, "light": s.openai_model_light}[tier]

    def _get_client(self):
        if self._client is None:
            import openai

            s = get_settings()
            self._client = openai.OpenAI(api_key=s.openai_api_key, timeout=s.ai_timeout_seconds, max_retries=2)
        return self._client

    def complete(self, system: str, messages: list[dict], tier: Tier, max_tokens: int) -> ProviderResult:
        model = self.model_for(tier)
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
            raise ProviderError("openai: response cut off at max_tokens")
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            text=choice.message.content or "",
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


_REGISTRY = {"anthropic": AnthropicProvider(), "openai": OpenAIProvider()}


def get_provider(name: str):
    return _REGISTRY.get(name)


def register_provider(name: str, provider) -> None:
    """Used by tests to plug in a fake provider."""
    _REGISTRY[name] = provider
