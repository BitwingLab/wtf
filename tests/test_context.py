import subprocess
from pathlib import Path

import pytest

from huh import context
from huh.context import detect_tools, gather_context, project_snippets, tool_versions


@pytest.mark.parametrize(
    "text,expected",
    [
        ("npm ERR! code ELIFECYCLE", ["node"]),
        ("Traceback (most recent call last):\nModuleNotFoundError", ["python"]),
        ("uv run pytest", ["python", "uv"]),
        ("error[E0425]: cannot find value", ["cargo"]),
        ("docker: Cannot connect to the Docker daemon", ["docker"]),
        ("fatal: not a git repository", ["git"]),
        ("something unrelated broke", []),
    ],
)
def test_detect_tools(text: str, expected: list[str]) -> None:
    assert detect_tools(text) == expected


def test_project_snippets(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "app"}\n')
    (tmp_path / "Dockerfile").write_text("\n".join(f"RUN step {i}" for i in range(100)))
    (tmp_path / "README.md").write_text("ignored")
    snippets = project_snippets(tmp_path)
    assert set(snippets) == {"package.json", "Dockerfile"}
    assert snippets["package.json"] == '{"name": "app"}'
    assert snippets["Dockerfile"].count("\n") == context.SNIPPET_LINES - 1


def test_project_snippets_char_cap(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("x" * 10_000)
    assert len(project_snippets(tmp_path)["requirements.txt"]) == context.SNIPPET_CHARS


def test_project_snippets_empty_dir(tmp_path: Path) -> None:
    assert project_snippets(tmp_path) == {}


def test_tool_versions_uses_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == context.VERSION_TIMEOUT
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{cmd[0]} 1.2.3\nextra\n", stderr="")

    monkeypatch.setattr(context.subprocess, "run", fake_run)
    assert tool_versions(["node"]) == {"node -v": "node 1.2.3", "npm -v": "npm 1.2.3"}


def test_tool_versions_skips_missing_and_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        context.shutil, "which", lambda name: None if name == "rustc" else f"/bin/{name}"
    )

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 1.5)

    monkeypatch.setattr(context.subprocess, "run", fake_run)
    assert tool_versions(["cargo"]) == {}


def test_tool_versions_stderr_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context.shutil, "which", lambda name: "/bin/java")
    monkeypatch.setattr(
        context.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr='openjdk "21"\n'),
    )
    assert tool_versions(["java"]) == {"java -version": 'openjdk "21"'}


def test_tool_versions_nonzero_exit_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context.shutil, "which", lambda name: "/bin/go")
    monkeypatch.setattr(
        context.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="oops", stderr=""),
    )
    assert tool_versions(["go"]) == {}


def test_gather_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(context, "tool_versions", lambda tools: {"probed": ",".join(tools)})
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    ctx = gather_context("python app.py", "ModuleNotFoundError: x", cwd=tmp_path)
    assert ctx.shell == "zsh"
    assert ctx.cwd == str(tmp_path)
    assert ctx.tool_versions == {"probed": "python"}
    assert "pyproject.toml" in ctx.project_files
    rendered = ctx.render()
    assert "Shell: zsh" in rendered and f"cwd: {tmp_path}" in rendered
    assert ctx.os
