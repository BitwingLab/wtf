"""Shared HTTP plumbing for providers: streaming POST, SSE parsing, error messages."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx

from huh.llm.base import ProviderAPIError, ProviderNetworkError

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def host_of(url: str) -> str:
    return urlsplit(url).hostname or url


def sse_events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yield the JSON payload of each ``data:`` line, skipping anything unparseable."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def stream_post(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    parse: Callable[[Iterator[dict[str, Any]]], Iterator[str]],
    key_hint: str,
) -> Iterator[str]:
    """POST ``body`` and yield text chunks produced by ``parse`` from the SSE stream."""
    host = host_of(url)
    try:
        with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                resp.read()
                raise ProviderAPIError(http_error_message(resp, url, key_hint))
            yield from parse(sse_events(resp.iter_lines()))
    except httpx.TimeoutException as e:
        raise ProviderNetworkError(f"Timed out talking to {host}.") from e
    except httpx.TransportError as e:
        raise ProviderNetworkError(
            f"Couldn't reach {host} ({type(e).__name__}). "
            "Check your internet connection and the endpoint URL."
        ) from e


def http_error_message(resp: httpx.Response, url: str, key_hint: str) -> str:
    host = host_of(url)
    try:
        err = resp.json().get("error", {})
        detail = (err.get("message") if isinstance(err, dict) else str(err)) or resp.text
    except (ValueError, AttributeError):
        detail = resp.text
    status = resp.status_code
    if status in (401, 403):
        return f"Your API key was rejected by {host} ({status}). Check {key_hint}."
    if status == 404:
        return f"{host} returned 404 for {url}. Check the endpoint URL and model name."
    if status == 429:
        return f"Rate limited by {host} (429). Try again in a moment."
    if status >= 500:
        return f"{host} is having trouble ({status}). Try again shortly."
    return f"API error {status} from {host}: {detail.strip()[:300]}"
