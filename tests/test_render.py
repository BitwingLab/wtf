import os
import pty
import sys

import pytest

from huh import render


def ask_in_child_terminal(typed: bytes) -> bytes:
    """Run _read_tty_answer in a child whose controlling terminal is a fresh pty."""
    pid, fd = pty.fork()
    if pid == 0:  # child
        answer = render._read_tty_answer("Run it? [y/N] ")
        os.write(1, f"\nANSWER={answer!r}\n".encode())  # fd 1 is the pty; sys.stdout is pytest's
        os._exit(0)
    out = b""
    sent = False
    while True:
        try:
            chunk = os.read(fd, 1024)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if not sent and b"[y/N]" in out:
            os.write(fd, typed)
            sent = True
    os.waitpid(pid, 0)
    return out


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pty")
@pytest.mark.parametrize(
    "typed,expected",
    [(b"y\r", "'y'"), (b"\r", "''"), (b"  YES \r", "'YES'"), (b"\x04", "''")],
)
def test_read_tty_answer_from_real_terminal(typed: bytes, expected: str) -> None:
    out = ask_in_child_terminal(typed)
    assert b"Run it? [y/N]" in out
    assert f"ANSWER={expected}".encode() in out


def test_ask_yes_no_only_explicit_yes() -> None:
    for answer, expected in [("y", True), ("YES", True), ("", False), ("yy", False)]:
        assert render.ask_yes_no("?", lambda p, a=answer: a) is expected
    assert render.ask_yes_no("?", lambda p: None) is None
