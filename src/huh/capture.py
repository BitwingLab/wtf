"""Getting the failed command's output: from a pipe, or by re-running it."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

MAX_INPUT_CHARS = 2_000_000
RERUN_TIMEOUT = 120.0

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def strip_ansi(text: str) -> str:
    """Remove terminal colour/cursor escape codes and normalise carriage returns."""
    text = _ANSI.sub("", text)
    # Progress bars redraw with \r; keep only the final state of each line.
    return "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n"))


def read_piped_input(stream: TextIO | None = None) -> str | None:
    """Return piped stdin, or ``None`` if stdin is a terminal or the input is blank.

    Very large input keeps only its end, since that is where failures usually are.
    """
    stream = stream if stream is not None else sys.stdin
    if stream is None or stream.isatty():
        return None
    data = strip_ansi(stream.read())
    if not data.strip():
        return None
    return data[-MAX_INPUT_CHARS:]


@dataclass
class RerunResult:
    output: str
    exit_code: int | None  # None if it timed out
    timed_out: bool = False


def rerun(command: str, cwd: Path | None = None, timeout: float = RERUN_TIMEOUT) -> RerunResult:
    """Run ``command`` in the user's shell and capture stdout+stderr together.

    stdin is closed so interactive programs fail fast instead of hanging. Callers
    must get the user's confirmation and check the deny-list first.
    """
    shell = os.environ.get("SHELL") or "/bin/sh"
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "CLICOLOR": "0"}
    try:
        proc = subprocess.run(
            [shell, "-c", command],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        partial = e.output.decode("utf-8", "replace") if e.output else ""
        return RerunResult(strip_ansi(partial)[-MAX_INPUT_CHARS:], None, timed_out=True)
    output = proc.stdout.decode("utf-8", "replace")
    return RerunResult(strip_ansi(output)[-MAX_INPUT_CHARS:], proc.returncode)
