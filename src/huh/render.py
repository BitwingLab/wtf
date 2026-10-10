"""Rich output: streamed diagnosis, highlighted fix, and the run confirmation."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterable
from contextlib import suppress

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from huh.prompt import DiagnosisStream, Reply

TTY_PATH = "/dev/tty"


def stream_reply(console: Console, chunks: Iterable[str]) -> Reply:
    """Print the diagnosis as it streams in and return the parsed reply."""
    parser = DiagnosisStream()
    printed_header = False

    def emit(text: str) -> None:
        nonlocal printed_header
        if not text:
            return
        if not printed_header:
            console.print(Text("huh? ", style="bold magenta"), end="")
            printed_header = True
        console.print(text, end="", markup=False, highlight=False, soft_wrap=True)

    with console.status("[dim]Thinking…[/dim]", spinner="dots") as status:
        for chunk in chunks:
            out = parser.feed(chunk)
            if out or parser.started:
                status.stop()
            emit(out)
    emit(parser.flush())

    reply = parser.result()
    if printed_header:
        console.print()
    elif reply.raw.strip():
        # The model ignored the format: show what it said, offer nothing to run.
        console.print(reply.raw.strip(), markup=False, highlight=False)
    return reply


def show_fix(console: Console, reply: Reply) -> None:
    if not reply.fix:
        if reply.diagnosis:
            console.print("[dim]No command to suggest for this one.[/dim]")
        return
    console.print()
    console.print(
        Panel(
            Syntax(reply.fix, "bash", theme="ansi_dark", background_color="default"),
            title="[bold green]Suggested fix[/bold green]",
            title_align="left",
            border_style="green",
            expand=False,
        )
    )


def _read_tty_answer(prompt: str) -> str | None:
    """Ask on the controlling terminal (stdin is the pipe). None if there isn't one."""
    # Separate read and write handles: a terminal isn't seekable, so "r+" text
    # mode fails with UnsupportedOperation.
    try:
        with (
            open(TTY_PATH, "w", encoding="utf-8") as out,
            open(TTY_PATH, encoding="utf-8", errors="replace") as tty_in,
        ):
            out.write(prompt)
            out.flush()
            line = tty_in.readline()
    except OSError:
        return None
    if not line:  # EOF (Ctrl-D): treat as "no"
        return ""
    return line.strip()


def confirm_and_run(
    console: Console,
    fix: str,
    ask: Callable[[str], str | None] | None = None,
) -> int | None:
    """Ask "Run it? [y/N]". Runs ``fix`` only on an explicit yes.

    Returns the command's exit code, or None if it was not run.
    """
    answer = ask_yes_no("Run it? [y/N] ", ask)
    if answer is None:
        console.print("[dim]No terminal to confirm on, so not running it.[/dim]")
        return None
    if not answer:
        console.print("[dim]Not run.[/dim]")
        return None
    return run_command(fix)


def ask_yes_no(prompt: str, ask: Callable[[str], str | None] | None = None) -> bool | None:
    """True only for an explicit y/yes. None if there is no terminal to ask on."""
    answer = (ask or _read_tty_answer)(prompt)
    if answer is None:
        return None
    return answer.strip().lower() in {"y", "yes"}


def run_command(command: str) -> int:
    shell = os.environ.get("SHELL") or "/bin/sh"
    stdin = None
    with suppress(OSError):
        stdin = open(TTY_PATH, encoding="utf-8")  # noqa: SIM115 - closed below
    try:
        return subprocess.run([shell, "-c", command], stdin=stdin).returncode
    finally:
        if stdin is not None:
            stdin.close()
