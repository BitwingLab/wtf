from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from huh import cli, render
from huh.context import Context
from huh.llm import ProviderNetworkError

runner = CliRunner()

REPLY = "<diagnosis>The module isn't installed.</diagnosis>\n<fix>pip install nonexistent_pkg</fix>"


class FakeProvider:
    def __init__(self, reply: str = REPLY, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def stream(self, system: str, user: str) -> Iterator[str]:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        for i in range(0, len(self.reply), 4):
            yield self.reply[i : i + 4]


def _fake_context(command: str | None, output: str) -> Context:
    return Context(os="TestOS", shell="zsh", cwd="/tmp/x")


@pytest.fixture
def use_provider(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def install(p: FakeProvider) -> FakeProvider:
        monkeypatch.setattr(cli, "make_provider", lambda config: p)
        monkeypatch.setattr(cli, "gather_context", _fake_context)
        return p

    return install


@pytest.fixture
def fake(use_provider) -> FakeProvider:  # type: ignore[no-untyped-def]
    return use_provider(FakeProvider())


class Tty:
    """Stands in for the user at /dev/tty and records commands that would run."""

    def __init__(self) -> None:
        self.answer: str | None = "n"
        self.ran: list[str] = []


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> Tty:
    t = Tty()
    monkeypatch.setattr(render, "_read_tty_answer", lambda prompt: t.answer)

    def fake_run(cmd: str) -> int:
        t.ran.append(cmd)
        return 0

    monkeypatch.setattr(render, "run_command", fake_run)
    return t


def test_empty_input_prints_usage(fake: FakeProvider) -> None:
    result = runner.invoke(cli.app, [], input="")
    assert result.exit_code == 2
    assert "2>&1 | wtf" in result.output
    assert fake.calls == []


def test_whitespace_input_is_empty(fake: FakeProvider) -> None:
    result = runner.invoke(cli.app, [], input="  \n\n")
    assert result.exit_code == 2


def test_missing_api_key_default_is_openai() -> None:
    result = runner.invoke(cli.app, [], input="boom\n")
    assert result.exit_code == 1
    assert "OPENAI_API_KEY" in result.output


def test_missing_api_key_anthropic_format() -> None:
    result = runner.invoke(cli.app, ["--api-format", "anthropic"], input="boom\n")
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_unknown_api_format() -> None:
    result = runner.invoke(cli.app, ["--api-format", "nope"], input="boom\n")
    assert result.exit_code == 1
    assert "Unknown API format" in result.output


def test_provider_for_selects_format() -> None:
    from huh.config import load_config
    from huh.llm import AnthropicProvider, OpenAIResponsesProvider

    p = cli.provider_for(load_config(endpoint="http://localhost:8080/v1/responses"))
    assert isinstance(p, OpenAIResponsesProvider)
    assert p.endpoint == "http://localhost:8080/v1/responses"
    assert p.api_key is None
    p = cli.provider_for(load_config(api_format="anthropic", endpoint="http://localhost:1/m"))
    assert isinstance(p, AnthropicProvider)


def test_network_error(use_provider) -> None:  # type: ignore[no-untyped-def]
    use_provider(FakeProvider(error=ProviderNetworkError("Couldn't reach api.anthropic.com")))
    result = runner.invoke(cli.app, [], input="boom\n")
    assert result.exit_code == 1
    assert "Couldn't reach" in result.output


def test_diagnosis_and_fix_shown_default_no(fake: FakeProvider, tty: Tty) -> None:
    tty.answer = ""  # just pressed Enter
    result = runner.invoke(
        cli.app, ["--cmd", "python -c 'import x'"], input="ModuleNotFoundError\n"
    )
    assert result.exit_code == 0, result.output
    assert "The module isn't installed." in result.output
    assert "pip install nonexistent_pkg" in result.output
    assert "Not run." in result.output
    assert tty.ran == []


@pytest.mark.parametrize("reply", ["n", "no", "N", "sure", "yy"])
def test_only_explicit_yes_runs(fake: FakeProvider, tty: Tty, reply: str) -> None:
    tty.answer = reply
    runner.invoke(cli.app, [], input="boom\n")
    assert tty.ran == []


@pytest.mark.parametrize("reply", ["y", "Y", "yes"])
def test_yes_runs_fix(fake: FakeProvider, tty: Tty, reply: str) -> None:
    tty.answer = reply
    result = runner.invoke(cli.app, [], input="boom\n")
    assert tty.ran == ["pip install nonexistent_pkg"]
    assert result.exit_code == 0


def test_no_tty_never_runs(fake: FakeProvider, tty: Tty) -> None:
    tty.answer = None
    result = runner.invoke(cli.app, [], input="boom\n")
    assert tty.ran == []
    assert "not running" in result.output


def test_secrets_redacted_before_sending(fake: FakeProvider, tty: Tty) -> None:
    secret = "sk-ant-api03-" + "Q" * 40
    runner.invoke(
        cli.app,
        ["--cmd", f"curl -H 'Authorization: Bearer {secret}'"],
        input=f"401 Unauthorized\nANTHROPIC_API_KEY={secret}\n",
    )
    _, user = fake.calls[0]
    assert secret not in user
    assert "[REDACTED]" in user


def test_unparseable_reply_shows_raw_and_no_prompt(use_provider, tty: Tty) -> None:  # type: ignore[no-untyped-def]
    use_provider(FakeProvider(reply="I think you should reinstall things."))
    tty.answer = "y"
    result = runner.invoke(cli.app, [], input="boom\n")
    assert "I think you should reinstall things." in result.output
    assert "Run it?" not in result.output
    assert tty.ran == []


def test_no_fix(use_provider, tty: Tty) -> None:  # type: ignore[no-untyped-def]
    use_provider(FakeProvider(reply="<diagnosis>Edit line 3.</diagnosis><fix>none</fix>"))
    tty.answer = "y"
    result = runner.invoke(cli.app, [], input="boom\n")
    assert "Edit line 3." in result.output
    assert "No command to suggest" in result.output
    assert tty.ran == []


def test_placeholder_fix_not_offered(use_provider, tty: Tty) -> None:  # type: ignore[no-untyped-def]
    use_provider(FakeProvider(reply="<diagnosis>Clone it.</diagnosis><fix>git clone <url></fix>"))
    tty.answer = "y"
    result = runner.invoke(cli.app, [], input="boom\n")
    assert "git clone <url>" in result.output
    assert tty.ran == []


def test_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


# --- `wtf` with no pipe: the shell hook passes the last command -------------------


@pytest.fixture
def at_terminal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Pretend stdin is a terminal; record (and fake) any re-runs."""
    from huh.capture import RerunResult

    reruns: list[str] = []
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)

    def fake_rerun(command: str) -> RerunResult:
        reruns.append(command)
        return RerunResult("ModuleNotFoundError: No module named 'nope'\n", 1)

    monkeypatch.setattr(cli, "rerun", fake_rerun)
    return reruns


def hook_args(cmd: str, status: int = 1) -> list[str]:
    return ["--last-cmd", cmd, "--last-status", str(status)]


def test_no_pipe_no_hook_shows_setup_help(fake: FakeProvider, at_terminal: list[str]) -> None:
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2
    assert "wtf setup" in result.output
    assert fake.calls == []


def test_last_command_rerun_after_yes(fake: FakeProvider, at_terminal: list[str], tty: Tty) -> None:
    tty.answer = "y"
    result = runner.invoke(cli.app, hook_args("python -c 'import nope'"))
    assert at_terminal == ["python -c 'import nope'"]
    _, user = fake.calls[0]
    assert "<command>\npython -c 'import nope'\n</command>" in user
    assert "<exit_code>1</exit_code>" in user
    assert "No module named 'nope'" in user
    assert "The module isn't installed." in result.output


@pytest.mark.parametrize("answer", ["", "n", "no", "sure"])
def test_last_command_not_rerun_without_yes(
    fake: FakeProvider, at_terminal: list[str], tty: Tty, answer: str
) -> None:
    tty.answer = answer
    result = runner.invoke(cli.app, hook_args("npm run build"))
    assert at_terminal == []
    assert fake.calls == []
    assert result.exit_code == 0
    assert "Not re-run" in result.output


def test_last_command_no_tty_to_confirm(
    fake: FakeProvider, at_terminal: list[str], tty: Tty
) -> None:
    tty.answer = None
    runner.invoke(cli.app, hook_args("npm run build"))
    assert at_terminal == []
    assert fake.calls == []


def test_denylisted_command_never_rerun(
    fake: FakeProvider, at_terminal: list[str], tty: Tty
) -> None:
    tty.answer = "y"
    result = runner.invoke(cli.app, hook_args("git push origin main"))
    assert at_terminal == []
    assert fake.calls == []
    assert "Not re-running" in result.output
    assert "2>&1 | wtf" in result.output


def test_last_command_succeeded(fake: FakeProvider, at_terminal: list[str], tty: Tty) -> None:
    tty.answer = "y"
    result = runner.invoke(cli.app, hook_args("ls", status=0))
    assert at_terminal == []
    assert "succeeded" in result.output
    assert result.exit_code == 0


def test_rerun_succeeds_this_time(
    fake: FakeProvider, at_terminal: list[str], tty: Tty, monkeypatch: pytest.MonkeyPatch
) -> None:
    from huh.capture import RerunResult

    monkeypatch.setattr(cli, "rerun", lambda c: RerunResult("all good\n", 0))
    tty.answer = "y"
    result = runner.invoke(cli.app, hook_args("flaky-test"))
    assert "succeeded this time" in result.output
    assert fake.calls == []


def test_pipe_wins_over_hook(fake: FakeProvider, at_terminal: list[str], tty: Tty) -> None:
    runner.invoke(cli.app, hook_args("make"), input="piped error\n")
    assert at_terminal == []
    assert "piped error" in fake.calls[0][1]


def test_missing_config_fails_before_rerun(at_terminal: list[str], tty: Tty) -> None:
    tty.answer = "y"
    result = runner.invoke(cli.app, hook_args("npm run build"))
    assert result.exit_code == 1
    assert "wtf setup" in result.output
    assert at_terminal == []


def test_init_prints_hook() -> None:
    result = runner.invoke(cli.app, ["init", "zsh"])
    assert result.exit_code == 0
    assert "add-zsh-hook preexec __huh_preexec" in result.output


def test_init_unknown_shell() -> None:
    result = runner.invoke(cli.app, ["init", "fish"])
    assert result.exit_code == 2


# --- response language -----------------------------------------------------------


def test_lang_flag_sets_system_prompt(fake: FakeProvider, tty: Tty) -> None:
    runner.invoke(cli.app, ["--lang", "zh-CN"], input="boom\n")
    system, _ = fake.calls[0]
    assert "Simplified Chinese (简体中文)" in system


def test_language_from_env(fake: FakeProvider, tty: Tty, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUH_LANGUAGE", "zh")
    runner.invoke(cli.app, [], input="boom\n")
    assert "简体中文" in fake.calls[0][0]


def test_default_language_english(fake: FakeProvider, tty: Tty) -> None:
    runner.invoke(cli.app, [], input="boom\n")
    assert "Write the diagnosis in English." in fake.calls[0][0]


def test_unknown_language_flag(fake: FakeProvider) -> None:
    result = runner.invoke(cli.app, ["--lang", "fr"], input="boom\n")
    assert result.exit_code == 1
    assert "Unknown language" in result.output
    assert fake.calls == []


def test_chinese_diagnosis_rendered(use_provider, tty: Tty) -> None:  # type: ignore[no-untyped-def]
    use_provider(
        FakeProvider(
            reply="<diagnosis>当前环境没有安装 requests。</diagnosis><fix>uv add requests</fix>"
        )
    )
    result = runner.invoke(cli.app, ["-l", "zh-CN"], input="boom\n")
    assert "当前环境没有安装 requests。" in result.output
    assert "uv add requests" in result.output
