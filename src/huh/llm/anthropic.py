"""Anthropic Messages API over httpx, with server-sent-event streaming."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from huh.llm.base import ProviderAPIError
from huh.llm.http import TIMEOUT, stream_post

DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"
API_VERSION = "2023-06-01"
MAX_TOKENS = 1024


class AnthropicProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        client: httpx.Client | None = None,
        key_hint: str = "ANTHROPIC_API_KEY",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.key_hint = key_hint
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def _body(self, system: str, user: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "stream": True,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if self.model.startswith("claude-haiku-5"):
            # Short, latency-sensitive task: skip thinking and keep effort low.
            body["thinking"] = {"type": "disabled"}
            body["output_config"] = {"effort": "low"}
        return body

    def stream(self, system: str, user: str) -> Iterator[str]:
        headers = {"anthropic-version": API_VERSION, "content-type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return stream_post(
            self._client,
            self.endpoint,
            headers,
            self._body(system, user),
            parse_events,
            self.key_hint,
        )


def parse_events(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """Yield text deltas from Anthropic stream events; raise on error events."""
    for event in events:
        kind = event.get("type")
        if kind == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                yield delta.get("text", "")
        elif kind == "message_delta":
            if event.get("delta", {}).get("stop_reason") == "refusal":
                raise ProviderAPIError("The model declined to answer this one.")
        elif kind == "error":
            err = event.get("error", {})
            raise ProviderAPIError(
                f"API error ({err.get('type', 'unknown')}): {err.get('message', '')}".rstrip(": ")
            )
