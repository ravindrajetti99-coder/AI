from dataclasses import dataclass
from typing import Literal, Protocol

Tier = Literal["heavy", "standard", "light"]


@dataclass
class ProviderResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    pass


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def model_for(self, tier: Tier) -> str: ...

    def complete(self, system: str, messages: list[dict], tier: Tier, max_tokens: int) -> ProviderResult: ...
