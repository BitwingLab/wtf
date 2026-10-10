import io
from pathlib import Path

import pytest

from huh.capture import read_piped_input, rerun, strip_ansi


@pytest.fixture(autouse=True)
def plain_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")


def test_rerun_captures_stdout_and_stderr_in_order() -> None:
    r = rerun("echo out; echo err >&2; exit 3")
    assert r.output == "out\nerr\n"
    assert r.exit_code == 3
    assert not r.timed_out


def test_rerun_uses_cwd(tmp_path: Path) -> None:
    assert rerun("pwd", cwd=tmp_path).output.strip() == str(tmp_path.resolve())


def test_rerun_stdin_is_closed() -> None:
    r = rerun("read line; echo got:$?")
    assert r.output.strip() != "got:0"


def test_rerun_asks_for_no_colour() -> None:
    assert rerun('echo "$NO_COLOR $TERM"').output.strip() == "1 dumb"


def test_rerun_timeout() -> None:
    r = rerun("echo started; sleep 5", timeout=0.5)
    assert r.timed_out
    assert r.exit_code is None
    assert "started" in r.output


def test_strip_ansi() -> None:
    assert strip_ansi("\x1b[31merror\x1b[0m: bad") == "error: bad"
    assert strip_ansi("\x1b]8;;http://x\x07link\x1b]8;;\x07") == "link"
    assert strip_ansi("10%\r50%\r100% done\nnext") == "100% done\nnext"


class FakeStdin(io.StringIO):
    def isatty(self) -> bool:
        return False


def test_read_piped_input_strips_ansi() -> None:
    assert read_piped_input(FakeStdin("\x1b[1mModuleNotFoundError\x1b[0m")) == "ModuleNotFoundError"


def test_read_piped_input_keeps_tail_of_huge_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("huh.capture.MAX_INPUT_CHARS", 10)
    assert read_piped_input(FakeStdin("a" * 50 + "0123456789")) == "0123456789"
