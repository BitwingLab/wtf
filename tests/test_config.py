from pathlib import Path

import pytest

from huh.config import config_path, load_config
from huh.llm.base import ProviderError

OPENAI = "https://api.openai.com/v1/responses"
ANTHROPIC = "https://api.anthropic.com/v1/messages"


def test_defaults_to_openai_responses() -> None:
    c = load_config()
    assert c.api_format == "openai-responses"
    assert c.endpoint == OPENAI
    assert c.model == "gpt-5-mini"
    assert c.api_key is None
    assert c.key_hint == "OPENAI_API_KEY"
    assert c.is_default_endpoint


def test_openai_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert load_config().api_key == "sk-openai"


def test_anthropic_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    c = load_config(api_format="anthropic")
    assert c.endpoint == ANTHROPIC
    assert c.model == "claude-haiku-5-5"
    assert c.api_key == "sk-ant"


def test_format_from_env_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUH_API_FORMAT", "Anthropic")
    assert load_config().api_format == "anthropic"


def test_unknown_format() -> None:
    with pytest.raises(ProviderError, match="Unknown API format"):
        load_config(api_format="grpc")


def test_custom_endpoint_does_not_get_vendor_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    c = load_config(endpoint="https://llm.example.com/v1/responses")
    assert c.api_key is None
    assert c.key_hint == "HUH_API_KEY"
    assert not c.is_default_endpoint


def test_custom_endpoint_uses_huh_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUH_API_KEY", "gateway-key")
    monkeypatch.setenv("HUH_ENDPOINT", "https://llm.example.com/v1/responses")
    c = load_config()
    assert c.endpoint == "https://llm.example.com/v1/responses"
    assert c.api_key == "gateway-key"


def test_vendor_host_with_other_path_still_gets_vendor_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    c = load_config(endpoint="https://api.openai.com/v2/responses")
    assert c.api_key == "sk-openai"
    assert not c.is_default_endpoint


def test_huh_key_beats_vendor_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("HUH_API_KEY", "sk-huh")
    assert load_config().api_key == "sk-huh"


@pytest.mark.parametrize("bad", ["api.openai.com/v1/responses", "ftp://x/y", "https://"])
def test_invalid_endpoint(bad: str) -> None:
    with pytest.raises(ProviderError, match="Invalid endpoint"):
        load_config(endpoint=bad)


def test_precedence_flag_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("tomllib")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'api_format = "anthropic"\n'
        'endpoint = "http://file.local/v1/messages"\n'
        'model = "from-file"\n'
        'api_key = "file-key"\n'
    )
    c = load_config(cfg)
    assert (c.api_format, c.endpoint, c.model, c.api_key) == (
        "anthropic",
        "http://file.local/v1/messages",
        "from-file",
        "file-key",
    )

    monkeypatch.setenv("HUH_MODEL", "from-env")
    monkeypatch.setenv("HUH_ENDPOINT", "http://env.local/v1/messages")
    c = load_config(cfg)
    assert (c.model, c.endpoint) == ("from-env", "http://env.local/v1/messages")

    c = load_config(cfg, model="from-flag", endpoint="http://flag.local/m")
    assert (c.model, c.endpoint) == ("from-flag", "http://flag.local/m")


def test_config_path_respects_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "huh" / "config.toml"


@pytest.mark.parametrize(
    "url,fmt,expected",
    [
        ("https://gw.example.com", "openai-responses", "https://gw.example.com/v1/responses"),
        ("https://gw.example/", "openai-responses", "https://gw.example/v1/responses"),
        ("https://gw.example/v1", "openai-responses", "https://gw.example/v1/responses"),
        ("https://gw.example/api/v1/", "anthropic", "https://gw.example/api/v1/messages"),
        ("https://gw.example/v1/responses", "openai-responses", "https://gw.example/v1/responses"),
        ("http://localhost:8080/custom", "openai-responses", "http://localhost:8080/custom"),
    ],
)
def test_complete_endpoint(url: str, fmt: str, expected: str) -> None:
    from huh.config import complete_endpoint

    assert complete_endpoint(url, fmt) == expected


def test_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUH_ENDPOINT", "https://gw.example")
    assert load_config().endpoint == "https://gw.example/v1/responses"


def test_write_config_roundtrip_and_permissions(tmp_path: Path) -> None:
    pytest.importorskip("tomllib")
    from huh.config import write_config

    path = write_config(
        {
            "api_format": "openai-responses",
            "endpoint": "https://gw.example/v1/responses",
            "model": 'odd "name" \\ here',
            "api_key": "k-123",
            "skipped": "",
        },
        tmp_path / "huh" / "config.toml",
    )
    assert path.stat().st_mode & 0o777 == 0o600
    c = load_config(path)
    assert (c.endpoint, c.model, c.api_key) == (
        "https://gw.example/v1/responses",
        'odd "name" \\ here',
        "k-123",
    )
    assert "skipped" not in path.read_text()


def test_language_default_english() -> None:
    assert load_config().language == "en"


def test_language_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("tomllib")
    cfg = tmp_path / "config.toml"
    cfg.write_text('language = "zh-CN"\n')
    assert load_config(cfg).language == "zh-CN"
    monkeypatch.setenv("HUH_LANGUAGE", "en")
    assert load_config(cfg).language == "en"
    assert load_config(cfg, language="中文").language == "zh-CN"


def test_unknown_language() -> None:
    with pytest.raises(ProviderError, match=r"Unknown language 'klingon'.*en, zh-CN"):
        load_config(language="klingon")
