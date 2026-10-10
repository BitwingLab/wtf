import json
from collections.abc import Callable

import httpx
import pytest

from huh.llm import OpenAIResponsesProvider, ProviderAPIError, ProviderNetworkError


def sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def text_delta(text: str) -> dict:
    return {"type": "response.output_text.delta", "item_id": "msg_1", "delta": text}


STREAM = sse(
    {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}},
    {"type": "response.output_item.added", "item": {"type": "message"}},
    text_delta("<diagnosis>Hi"),
    text_delta(" there.</diagnosis>"),
    {"type": "response.output_text.done", "text": "<diagnosis>Hi there.</diagnosis>"},
    {"type": "response.completed", "response": {"id": "resp_1", "status": "completed"}},
)


def provider(
    handler: Callable[[httpx.Request], httpx.Response],
    model: str = "gpt-5-mini",
    endpoint: str = "https://api.openai.com/v1/responses",
    api_key: str | None = "test-key",
) -> OpenAIResponsesProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIResponsesProvider(api_key=api_key, model=model, endpoint=endpoint, client=client)


def ok(body: bytes = STREAM) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, content=body)


def test_streams_text_and_sends_expected_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=STREAM, headers={"content-type": "text/event-stream"})

    chunks = list(provider(handler).stream("SYS", "USER"))
    assert chunks == ["<diagnosis>Hi", " there.</diagnosis>"]
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["headers"]["authorization"] == "Bearer test-key"
    body = seen["body"]
    assert body["model"] == "gpt-5-mini"
    assert body["instructions"] == "SYS"
    assert body["input"] == "USER"
    assert body["stream"] is True
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "low"}
    assert "messages" not in body


def test_non_reasoning_model_has_no_reasoning_param() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=STREAM)

    list(provider(handler, model="llama3.1").stream("s", "u"))
    assert "reasoning" not in seen["body"]


def test_custom_endpoint_without_key() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        return httpx.Response(200, content=STREAM)

    p = provider(handler, endpoint="http://localhost:11434/v1/responses", api_key=None)
    assert list(p.stream("s", "u")) == ["<diagnosis>Hi", " there.</diagnosis>"]
    assert seen["url"] == "http://localhost:11434/v1/responses"
    assert "authorization" not in seen["headers"]


def test_ignores_other_events_and_done_marker() -> None:
    body = (
        sse(
            {"type": "response.reasoning_summary_text.delta", "delta": "thinking"},
            text_delta("ok"),
        )
        + b"data: [DONE]\n\n"
    )
    assert list(provider(ok(body)).stream("s", "u")) == ["ok"]


def test_refusal() -> None:
    body = sse({"type": "response.refusal.delta", "delta": "I can't help"})
    with pytest.raises(ProviderAPIError, match="declined"):
        list(provider(ok(body)).stream("s", "u"))


def test_response_failed() -> None:
    body = sse(
        text_delta("<diagnosis>par"),
        {
            "type": "response.failed",
            "response": {"error": {"code": "server_error", "message": "Something broke"}},
        },
    )
    stream = provider(ok(body)).stream("s", "u")
    assert next(stream) == "<diagnosis>par"
    with pytest.raises(ProviderAPIError, match=r"server_error.*Something broke"):
        next(stream)


def test_error_event() -> None:
    body = sse({"type": "error", "code": "rate_limit_exceeded", "message": "Slow down"})
    with pytest.raises(ProviderAPIError, match="Slow down"):
        list(provider(ok(body)).stream("s", "u"))


@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "rejected by api.openai.com.*OPENAI_API_KEY"),
        (404, "Check the endpoint URL"),
        (429, "Rate limited by api.openai.com"),
        (503, "api.openai.com is having trouble"),
    ],
)
def test_http_errors(status: int, needle: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope", "type": "x"}})

    with pytest.raises(ProviderAPIError, match=needle):
        list(provider(handler).stream("s", "u"))


def test_400_includes_api_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Unsupported parameter: 'reasoning'"}}
        )

    with pytest.raises(ProviderAPIError, match="Unsupported parameter"):
        list(provider(handler).stream("s", "u"))


def test_connect_error_names_custom_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    p = provider(handler, endpoint="http://localhost:9/v1/responses")
    with pytest.raises(ProviderNetworkError, match="Couldn't reach localhost"):
        list(p.stream("s", "u"))
