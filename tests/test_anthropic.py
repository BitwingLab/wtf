import json
from collections.abc import Callable

import httpx
import pytest

from huh.llm import (
    AnthropicProvider,
    ProviderAPIError,
    ProviderNetworkError,
)


def sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def text_delta(text: str) -> dict:
    return {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": text},
    }


STREAM = sse(
    {"type": "message_start", "message": {"id": "msg_1"}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "ping"},
    text_delta("<diagnosis>Hi"),
    text_delta(" there.</diagnosis>"),
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
    {"type": "message_stop"},
)


def provider(
    handler: Callable[[httpx.Request], httpx.Response], model: str = "claude-haiku-5-5"
) -> AnthropicProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AnthropicProvider(api_key="test-key", model=model, client=client)


def test_custom_endpoint_without_key_sends_no_auth() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        return httpx.Response(200, content=STREAM)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = AnthropicProvider(api_key=None, endpoint="http://proxy.local/v1/messages", client=client)
    list(p.stream("s", "u"))
    assert seen["url"] == "http://proxy.local/v1/messages"
    assert "x-api-key" not in seen["headers"]


def test_streams_text_and_sends_expected_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
        return httpx.Response(200, content=STREAM, headers={"content-type": "text/event-stream"})

    chunks = list(provider(handler).stream("SYS", "USER"))
    assert chunks == ["<diagnosis>Hi", " there.</diagnosis>"]
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "test-key"
    assert seen["headers"]["anthropic-version"]
    body = seen["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert body["stream"] is True
    assert body["system"] == "SYS"
    assert body["messages"] == [{"role": "user", "content": "USER"}]
    assert body["output_config"] == {"effort": "low"}
    assert "temperature" not in body


def test_other_models_get_plain_body() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=STREAM)

    list(provider(handler, model="claude-opus-5-5").stream("s", "u"))
    assert "thinking" not in seen["body"]
    assert "output_config" not in seen["body"]


def test_ignores_non_text_deltas() -> None:
    body = sse(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "hmm"},
        },
        text_delta("ok"),
    )
    chunks = list(provider(lambda r: httpx.Response(200, content=body)).stream("s", "u"))
    assert chunks == ["ok"]


@pytest.mark.parametrize(
    "status,needle",
    [(401, "rejected"), (429, "Rate limited"), (529, "having trouble"), (500, "having trouble")],
)
def test_http_errors(status: int, needle: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"type": "error", "error": {"message": "nope"}})

    with pytest.raises(ProviderAPIError, match=needle):
        list(provider(handler).stream("s", "u"))


def test_400_includes_api_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "bad model"},
            },
        )

    with pytest.raises(ProviderAPIError, match="bad model"):
        list(provider(handler).stream("s", "u"))


def test_error_event_mid_stream() -> None:
    body = sse(
        text_delta("<diagnosis>par"),
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    )
    stream = provider(lambda r: httpx.Response(200, content=body)).stream("s", "u")
    assert next(stream) == "<diagnosis>par"
    with pytest.raises(ProviderAPIError, match="Overloaded"):
        next(stream)


def test_refusal() -> None:
    body = sse({"type": "message_delta", "delta": {"stop_reason": "refusal"}})
    with pytest.raises(ProviderAPIError, match="declined"):
        list(provider(lambda r: httpx.Response(200, content=body)).stream("s", "u"))


def test_connect_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    with pytest.raises(ProviderNetworkError, match="Couldn't reach"):
        list(provider(handler).stream("s", "u"))


def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderNetworkError, match="Timed out"):
        list(provider(handler).stream("s", "u"))
