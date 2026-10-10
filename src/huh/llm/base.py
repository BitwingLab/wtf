"""Provider interface shared by all LLM backends."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class ProviderError(Exception):
    """An error with a user-facing message."""


class MissingAPIKeyError(ProviderError):
    pass


class ProviderNetworkError(ProviderError):
    pass


class ProviderAPIError(ProviderError):
    pass


class Provider(Protocol):
    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield the model's reply as text chunks."""
        ...
