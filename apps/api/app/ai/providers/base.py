from dataclasses import dataclass
from typing import Literal, Protocol

Tier = Literal["heavy", "standard", "light"]


@dataclass
class ProviderResult:
    text: str
    model: str  # the model that answered (differs from requested_model after a server-side fallback)
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requested_model: str = ""
    request_id: str = ""
    stop_reason: str = ""


class ProviderError(Exception):
    """A provider could not produce a usable answer; the gateway falls back to the next one."""

    def __init__(self, message: str, *, request_id: str = "", refusal_category: str = "", stop_reason: str = "", model: str = ""):
        super().__init__(message)
        self.request_id, self.refusal_category, self.stop_reason, self.model = request_id, refusal_category, stop_reason, model


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def model_for(self, tier: Tier) -> str: ...

    def complete(
        self, system: str, messages: list[dict], tier: Tier, max_tokens: int, *, effort: str = "", schema: dict | None = None, cache_system: bool = False
    ) -> ProviderResult:
        """`effort` tunes thinking depth, `schema` constrains the answer to JSON (when supported),
        `cache_system` asks the provider to cache the system prompt. Providers ignore what they lack."""

    def check(self, tier: Tier, live: bool = False) -> dict:
        """Prove the key and the tier's model work: a free call by default, a tiny real one with `live`."""
