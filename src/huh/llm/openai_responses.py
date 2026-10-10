"""OpenAI Responses API (POST /v1/responses) over httpx, with streaming.

Also works with any server that implements the Responses API format.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx

from huh.llm.base import ProviderAPIError
from huh.llm.http import TIMEOUT, stream_post

DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-mini"
# Reasoning tokens count toward this limit, so leave headroom beyond the short reply.
MAX_OUTPUT_TOKENS = 2048
_REASONING_MODELS = re.compile(r"^(?:gpt-5|o\d)")


class OpenAIResponsesProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        client: httpx.Client | None = None,
        key_hint: str = "OPENAI_API_KEY",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.key_hint = key_hint
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def _body(self, system: str, user: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "stream": True,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "store": False,
        }
        if _REASONING_MODELS.match(self.model):
            # Short, latency-sensitive task: keep reasoning light.
            body["reasoning"] = {"effort": "low"}
        return body

    def stream(self, system: str, user: str) -> Iterator[str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return stream_post(
            self._client,
            self.endpoint,
            headers,
            self._body(system, user),
            parse_events,
            self.key_hint,
        )


def _error_text(err: Any) -> str:
    if isinstance(err, dict):
        code = err.get("code") or err.get("type")
        message = err.get("message") or ""
        return f"API error ({code}): {message}" if code else f"API error: {message}"
    return f"API error: {err}"


def parse_events(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """Yield output text deltas from Responses API stream events; raise on failures."""
    for event in events:
        kind = event.get("type")
        if kind == "response.output_text.delta":
            yield event.get("delta", "")
        elif kind in ("response.refusal.delta", "response.refusal.done"):
            raise ProviderAPIError("The model declined to answer this one.")
        elif kind == "response.failed":
            err = (event.get("response") or {}).get("error") or {}
            raise ProviderAPIError(_error_text(err).rstrip(": "))
        elif kind == "error":
            err = event.get("error", event)
            raise ProviderAPIError(_error_text(err).rstrip(": "))
