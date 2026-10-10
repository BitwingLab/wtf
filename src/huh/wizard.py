"""`wtf setup`: one-time interactive configuration."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt

from huh import shell
from huh.config import (
    FORMATS,
    complete_endpoint,
    config_path,
    load_config,
    read_config_file,
    write_config,
)
from huh.llm.base import ProviderError
from huh.prompt import DEFAULT_LANGUAGE, LANGUAGES, normalize_language

_ENV_OVERRIDES = ("HUH_API_FORMAT", "HUH_ENDPOINT", "HUH_MODEL", "HUH_LANGUAGE", "HUH_API_KEY")


def _ask_endpoint(console: Console, default: str, api_format: str) -> str:
    while True:
        url = complete_endpoint(Prompt.ask("Endpoint URL", default=default).strip(), api_format)
        if url.startswith(("http://", "https://")):
            return url
        console.print("[red]Enter a full URL starting with https:// (or http:// for local).[/red]")


def _ask_key(console: Console, has_existing: bool) -> str | None:
    hint = "Enter keeps the saved key" if has_existing else "Enter to skip"
    try:
        key = getpass.getpass(f"API key (typing is hidden; {hint}): ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None
    return key or None


def _install_hook(console: Console) -> None:
    sh = Path(os.environ.get("SHELL", "")).name
    if sh not in shell.SUPPORTED:
        console.print(
            f"[yellow]Shell hook not available for {sh or 'your shell'} yet.[/yellow] "
            "Piping still works: [cyan]cmd 2>&1 | wtf[/cyan]"
        )
        return
    rc = Path(os.path.expanduser(shell.rc_file(sh)))
    line = shell.init_line(sh)
    try:
        current = rc.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if line in current:
        console.print(f"[green]✓[/green] Shell hook already in {rc}")
        return
    if not Confirm.ask(
        f"Add [cyan]{line}[/cyan] to {rc}? (lets you type just [bold]wtf[/bold])", default=True
    ):
        console.print(f"Skipped. To add it later, put this line in {rc}:\n  {line}")
        return
    sep = "" if current.endswith("\n") or not current else "\n"
    with rc.open("a", encoding="utf-8") as f:
        f.write(f"{sep}\n# huh / wtf: explain failed commands\n{line}\n")
    console.print(f"[green]✓[/green] Added to {rc}")


def _test_request(console: Console) -> bool:
    from huh.cli import make_provider

    try:
        provider = make_provider(load_config())
        with console.status("Testing the connection…"):
            reply = "".join(provider.stream("Reply with exactly: OK", "ping"))
    except ProviderError as e:
        console.print(f"[red]✗ Test failed:[/red] {e}")
        return False
    console.print(f"[green]✓[/green] Connected. The model replied: {reply.strip()[:60]!r}")
    return True


def _default_language(saved: dict[str, object]) -> str:
    if saved.get("language"):
        return normalize_language(str(saved["language"])) or DEFAULT_LANGUAGE
    # Follow the system locale on first setup, e.g. LANG=zh_CN.UTF-8 -> zh-CN.
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if value := os.environ.get(var):
            return normalize_language(value) or DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE


def run_setup(console: Console) -> int:
    console.print("[bold]wtf setup[/bold] — saves settings to " + str(config_path()) + "\n")
    saved = read_config_file()

    fmt = Prompt.ask(
        "API format",
        choices=list(FORMATS),
        default=str(saved.get("api_format", "openai-responses")),
    )
    endpoint = _ask_endpoint(
        console, str(saved.get("endpoint", FORMATS[fmt].default_endpoint)), fmt
    )
    model = Prompt.ask("Model", default=str(saved.get("model", FORMATS[fmt].default_model)))
    key = _ask_key(console, has_existing=bool(saved.get("api_key"))) or saved.get("api_key")
    language = Prompt.ask(
        "Answer language (en = English, zh-CN = 简体中文)",
        choices=list(LANGUAGES),
        default=_default_language(saved),
    )

    path = write_config(
        {
            "api_format": fmt,
            "endpoint": endpoint,
            "model": model,
            "language": language,
            "api_key": key or "",
        }
    )
    console.print(f"[green]✓[/green] Saved {path} (readable only by you)")

    overridden = [name for name in _ENV_OVERRIDES if os.environ.get(name)]
    if overridden:
        console.print(
            f"[yellow]Note:[/yellow] {', '.join(overridden)} is set in your environment and "
            "overrides the saved settings. Unset it to use them."
        )

    try:
        load_config()
    except ProviderError as e:
        console.print(f"[red]✗[/red] {e}")
        return 1

    _install_hook(console)

    if Confirm.ask("Send a tiny test request to check it works?", default=True):
        _test_request(console)

    console.print(
        "\nDone. Open a new terminal tab (or run [cyan]exec zsh[/cyan]), then after any "
        "failed command just type [bold]wtf[/bold]."
    )
    return 0
