"""Configuration: ~/.config/huh/config.toml, overridden by env vars, overridden by flags."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from huh.llm import anthropic, openai_responses
from huh.llm.base import ProviderError
from huh.prompt import DEFAULT_LANGUAGE, LANGUAGES, normalize_language


@dataclass(frozen=True)
class ApiFormat:
    name: str
    default_endpoint: str
    default_model: str
    vendor_key_env: str  # only sent to default_endpoint's host


FORMATS: dict[str, ApiFormat] = {
    "openai-responses": ApiFormat(
        "openai-responses",
        openai_responses.DEFAULT_ENDPOINT,
        openai_responses.DEFAULT_MODEL,
        "OPENAI_API_KEY",
    ),
    "anthropic": ApiFormat(
        "anthropic",
        anthropic.DEFAULT_ENDPOINT,
        anthropic.DEFAULT_MODEL,
        "ANTHROPIC_API_KEY",
    ),
}
DEFAULT_FORMAT = "openai-responses"


@dataclass
class Config:
    api_format: str
    endpoint: str
    model: str
    api_key: str | None
    key_hint: str  # where the user should set the key, for error messages
    language: str = DEFAULT_LANGUAGE  # a LANGUAGES key; the diagnosis is written in it

    @property
    def is_default_endpoint(self) -> bool:
        return self.endpoint == FORMATS[self.api_format].default_endpoint


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "huh" / "config.toml"


def _read_file(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:  # Python 3.10: config file unsupported, env vars still work.
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _pick(flag: str | None, env: str, data: dict[str, Any], key: str) -> str | None:
    value = flag or os.environ.get(env) or data.get(key)
    return str(value).strip() if value else None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def complete_endpoint(url: str, api_format: str) -> str:
    """Fill in the standard path when given a base URL.

    ``https://gw.example`` and ``https://gw.example/v1`` both become
    ``https://gw.example/v1/responses`` (or ``/v1/messages`` for Anthropic).
    """
    default = urlsplit(FORMATS[api_format].default_endpoint).path  # /v1/responses
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path == "":
        path = default
    elif path.endswith("/v1"):
        path = path + "/" + default.rsplit("/", 1)[-1]
    else:
        return url
    return parts._replace(path=path).geturl()


def write_config(values: dict[str, str], path: Path | None = None) -> Path:
    """Write ``values`` as TOML, readable only by the owner (it may hold a key)."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON string escaping is valid TOML basic-string escaping.
    body = "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in values.items() if v)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Written by `wtf setup`. Env vars (HUH_*) override these.\n" + body)
    os.chmod(path, 0o600)
    return path


def read_config_file(path: Path | None = None) -> dict[str, Any]:
    return _read_file(path or config_path())


def load_config(
    path: Path | None = None,
    *,
    api_format: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    language: str | None = None,
) -> Config:
    """Resolve settings. Precedence: flag > env var > config file > default."""
    data = _read_file(path or config_path())

    fmt_name = (_pick(api_format, "HUH_API_FORMAT", data, "api_format") or DEFAULT_FORMAT).lower()
    if fmt_name not in FORMATS:
        raise ProviderError(f"Unknown API format {fmt_name!r}. Use one of: {', '.join(FORMATS)}.")
    fmt = FORMATS[fmt_name]

    url = _pick(endpoint, "HUH_ENDPOINT", data, "endpoint") or fmt.default_endpoint
    url = complete_endpoint(url, fmt_name)
    if urlsplit(url).scheme not in ("http", "https") or not _host(url):
        raise ProviderError(
            f"Invalid endpoint {url!r}: expected a full URL like {fmt.default_endpoint}"
        )

    # The vendor's own key env var is only used for the vendor's own host, so a
    # custom endpoint never silently receives e.g. your OpenAI key.
    api_key = os.environ.get("HUH_API_KEY") or data.get("api_key")
    key_hint = "HUH_API_KEY"
    if _host(url) == _host(fmt.default_endpoint):
        api_key = api_key or os.environ.get(fmt.vendor_key_env)
        key_hint = fmt.vendor_key_env

    lang_value = _pick(language, "HUH_LANGUAGE", data, "language") or DEFAULT_LANGUAGE
    lang = normalize_language(lang_value)
    if lang is None:
        raise ProviderError(f"Unknown language {lang_value!r}. Use one of: {', '.join(LANGUAGES)}.")

    return Config(
        api_format=fmt_name,
        endpoint=url,
        model=_pick(model, "HUH_MODEL", data, "model") or fmt.default_model,
        api_key=str(api_key) if api_key else None,
        key_hint=key_hint,
        language=lang,
    )
