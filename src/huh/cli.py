"""Typer entry point: `wtf` after a failed command, or `some-command 2>&1 | wtf`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from huh import __version__, shell
from huh.capture import read_piped_input, rerun
from huh.config import Config, load_config
from huh.context import gather_context
from huh.denylist import check_rerun
from huh.llm import (
    AnthropicProvider,
    MissingAPIKeyError,
    OpenAIResponsesProvider,
    Provider,
    ProviderError,
)
from huh.prompt import build_user_message, system_prompt
from huh.redact import redact
from huh.render import ask_yes_no, confirm_and_run, show_fix, stream_reply
from huh.trim import trim

app = typer.Typer(
    add_completion=False,
    help="Explain a failed command in plain English and suggest a fix.",
    no_args_is_help=False,
)


def prog_name() -> str:
    name = Path(sys.argv[0]).name
    return name if name in ("wtf", "huh") else "wtf"


def usage() -> str:
    p = prog_name()
    return f"""\
[bold]{p}[/bold] explains a failed command and suggests a fix.

After a command fails, just type [cyan]{p}[/cyan].
  First time? Run [cyan]{p} setup[/cyan] (sets your endpoint and key, and adds the
  shell hook that lets {p} see your last command).

Or pipe output in directly:
  [cyan]npm run build 2>&1 | {p}[/cyan]"""


def _stdin_is_tty() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def _version(value: bool) -> None:
    if value:
        print(f"{prog_name()} {__version__}")
        raise typer.Exit()


def provider_for(config: Config) -> Provider:
    if not config.api_key and config.is_default_endpoint:
        raise MissingAPIKeyError(
            f"No API key found. Run `{prog_name()} setup`, or set {config.key_hint}."
        )
    cls = AnthropicProvider if config.api_format == "anthropic" else OpenAIResponsesProvider
    return cls(
        api_key=config.api_key,
        model=config.model,
        endpoint=config.endpoint,
        key_hint=config.key_hint,
    )


def make_provider(config: Config) -> Provider:
    return provider_for(config)


def _output_from_last_command(
    console: Console, err: Console, last_cmd: str | None, last_status: int | None
) -> tuple[str, int | None]:
    """Re-run the hook-recorded last command, with confirmation. Exits on refusal."""
    p = prog_name()
    if not last_cmd:
        err.print(usage())
        raise typer.Exit(2)
    shown = escape(last_cmd)
    if last_status == 0:
        console.print(f"[dim]Your last command ([/dim]{shown}[dim]) succeeded.[/dim]")
        console.print(f"[dim]To explain its output anyway: [cyan]{shown} 2>&1 | {p}[/cyan][/dim]")
        raise typer.Exit(0)

    reason = check_rerun(last_cmd)
    if reason:
        console.print(f"[yellow]Not re-running[/yellow] {shown}: {reason}.")
        console.print(f"To explain it, pipe its output in:  [cyan]{shown} 2>&1 | {p}[/cyan]")
        raise typer.Exit(1)

    status = f" (exit {last_status})" if last_status is not None else ""
    console.print(f"Last command{status}: [bold]{shown}[/bold]")
    answer = ask_yes_no("Re-run it to capture the error? [y/N] ")
    if answer is None:
        console.print("[dim]No terminal to confirm on, so not re-running.[/dim]")
        raise typer.Exit(1)
    if not answer:
        console.print(f"[dim]Not re-run. You can also pipe it: {shown} 2>&1 | {p}[/dim]")
        raise typer.Exit(0)

    with console.status("Re-running… (Ctrl-C to stop)"):
        result = rerun(last_cmd)
    if result.exit_code == 0:
        console.print("[green]It succeeded this time[/green] (exit 0), so there's nothing to fix.")
        raise typer.Exit(0)
    output = result.output if result.output.strip() else "(the command printed nothing)"
    if result.timed_out:
        output += "\n(huh: stopped after 120s; output above is partial)"
    return output, result.exit_code


@app.callback(invoke_without_command=True)
def explain(
    ctx: typer.Context,
    cmd: Annotated[
        str | None,
        typer.Option("--cmd", "-c", help="The command that failed, for better context."),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="Model to use (or set HUH_MODEL).")
    ] = None,
    endpoint: Annotated[
        str | None,
        typer.Option("--endpoint", "-e", help="Request URL or base URL (or set HUH_ENDPOINT)."),
    ] = None,
    api_format: Annotated[
        str | None,
        typer.Option(
            "--api-format",
            help="Request format: openai-responses (default) or anthropic (or HUH_API_FORMAT).",
        ),
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Answer language: en or zh-CN (or set HUH_LANGUAGE)."),
    ] = None,
    last_cmd: Annotated[str | None, typer.Option("--last-cmd", hidden=True)] = None,
    last_status: Annotated[int | None, typer.Option("--last-status", hidden=True)] = None,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    if ctx.invoked_subcommand:
        return
    console = Console(highlight=False)
    err = Console(stderr=True, highlight=False)

    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(errors="replace")
    output = read_piped_input()
    if output is None and not _stdin_is_tty():
        err.print("[yellow]Nothing was piped in.[/yellow] Did the command print anything?\n")
        err.print(usage())
        raise typer.Exit(2)
    if output is None and not last_cmd:
        err.print(usage())
        raise typer.Exit(2)

    # Check config before re-running anything, so a bad setup fails fast.
    try:
        config = load_config(api_format=api_format, endpoint=endpoint, model=model, language=lang)
        provider = make_provider(config)
    except ProviderError as e:
        err.print(f"[red]{prog_name()}:[/red] {e}")
        raise typer.Exit(1) from e

    exit_code = None
    if output is None:
        try:
            output, exit_code = _output_from_last_command(console, err, last_cmd, last_status)
        except KeyboardInterrupt:
            raise typer.Exit(130) from None
        cmd = cmd or last_cmd

    command = redact(cmd) if cmd else None
    clean_output = trim(redact(output))
    context = gather_context(command, clean_output)
    user_message = redact(build_user_message(clean_output, context, command, exit_code))

    try:
        reply = stream_reply(console, provider.stream(system_prompt(config.language), user_message))
    except ProviderError as e:
        err.print(f"\n[red]{prog_name()}:[/red] {e}")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        raise typer.Exit(130) from None

    show_fix(console, reply)
    if reply.fix and reply.runnable:
        code = confirm_and_run(console, reply.fix)
        if code is not None:
            raise typer.Exit(code)
    elif reply.fix:
        console.print(
            "[dim]This one needs editing before it can run; not offering to run it.[/dim]"
        )


@app.command()
def setup() -> None:
    """Configure endpoint, model and key, and install the shell hook."""
    from huh.wizard import run_setup

    raise typer.Exit(run_setup(Console(highlight=False)))


@app.command()
def init(
    shell_name: Annotated[
        str | None, typer.Argument(metavar="SHELL", help="zsh or bash (default: $SHELL).")
    ] = None,
) -> None:
    """Print the shell hook. Add `eval "$(wtf init zsh)"` to your shell's rc file."""
    name = shell_name or Path(os.environ.get("SHELL", "")).name
    try:
        print(shell.init_script(name), end="")
    except ValueError as e:
        Console(stderr=True).print(f"[red]{prog_name()}:[/red] {e}")
        raise typer.Exit(2) from e


def main() -> None:
    app(prog_name=prog_name())
