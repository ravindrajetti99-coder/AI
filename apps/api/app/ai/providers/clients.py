"""Model provider adapters. Each is optional: it reports unavailable when its key is missing."""

from app.ai.providers.base import ProviderError, ProviderResult, Tier
from app.core.config import get_settings


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
        try:
            resp = self._get_client().messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
        except Exception as exc:  # network, auth, rate limit, overload
            raise ProviderError(f"anthropic: {exc}") from exc
        text = "".join(getattr(block, "text", "") for block in resp.content)
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            text=text,
            model=model,
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
        usage = getattr(resp, "usage", None)
        return ProviderResult(
            text=resp.choices[0].message.content or "",
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
