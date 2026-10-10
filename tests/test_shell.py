"""Shell hook tests: syntax, and real zsh/bash runs with a fake `wtf` on PATH."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from huh.shell import init_line, init_script, rc_file


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """A fake `wtf` that prints its arguments, one per line."""
    script = tmp_path / "wtf"
    script.write_text('#!/bin/sh\nfor a in "$@"; do echo "ARG:$a"; done\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return tmp_path


def run_with_tty_stdin(argv: list[str], fake_bin: Path) -> list[str]:
    """Run with stdin attached to a pseudo-terminal, as in a real interactive shell."""
    main_fd, sub_fd = os.openpty()
    try:
        proc = subprocess.run(
            argv,
            stdin=sub_fd,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        )
    finally:
        os.close(sub_fd)
        os.close(main_fd)
    assert proc.returncode == 0, proc.stderr
    return [line[4:] for line in proc.stdout.splitlines() if line.startswith("ARG:")]


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_syntax(shell: str) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    proc = subprocess.run([shell, "-n"], input=init_script(shell), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh not installed")
def test_zsh_hook_passes_last_failed_command(fake_bin: Path) -> None:
    script = init_script("zsh") + (
        '__huh_preexec "make build"; (exit 3); __huh_precmd\n'
        # Running wtf itself must not overwrite the remembered command or status.
        '__huh_preexec "wtf"; (exit 0); __huh_precmd\n'
        "wtf --model x\n"
    )
    args = run_with_tty_stdin(["zsh", "-f", "-c", script], fake_bin)
    assert args == ["--last-cmd", "make build", "--last-status", "3", "--model", "x"]


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh not installed")
def test_zsh_hook_pipe_mode_passes_through(fake_bin: Path) -> None:
    script = init_script("zsh") + '__huh_preexec "make"; (exit 2); __huh_precmd\necho hi | wtf\n'
    args = run_with_tty_stdin(["zsh", "-f", "-c", script], fake_bin)
    assert args == []


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_bash_hook_passes_last_failed_command(fake_bin: Path) -> None:
    script = (
        "set -o history\n"
        + init_script("bash")
        + "history -s 'npm run build'; (exit 1); __huh_prompt\n"
        + "history -s 'wtf'; (exit 0); __huh_prompt\n"
        + "wtf\n"
    )
    args = run_with_tty_stdin(["bash", "--norc", "-c", script], fake_bin)
    assert args == ["--last-cmd", "npm run build", "--last-status", "1"]


def test_bash_prompt_command_not_duplicated() -> None:
    if not shutil.which("bash"):
        pytest.skip("bash not installed")
    script = init_script("bash") * 2 + 'echo "$PROMPT_COMMAND"\n'
    out = subprocess.run(["bash", "--norc", "-c", script], capture_output=True, text=True)
    assert out.stdout.strip() == "__huh_prompt"


def test_unsupported_shell() -> None:
    with pytest.raises(ValueError, match="Unsupported shell"):
        init_script("fish")


def test_init_line_and_rc() -> None:
    assert init_line("zsh") == 'eval "$(wtf init zsh)"'
    assert rc_file("zsh") == "~/.zshrc"
