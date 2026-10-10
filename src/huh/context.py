"""Environment info sent alongside the error: OS, shell, cwd, tools, project files."""

from __future__ import annotations

import itertools
import os
import platform
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_FILES = ("package.json", "pyproject.toml", "requirements.txt", "Dockerfile")
SNIPPET_LINES = 40
SNIPPET_CHARS = 2000
VERSION_TIMEOUT = 1.5

# keyword in command/output -> version commands to run
TOOL_PROBES: dict[str, list[list[str]]] = {
    "node": [["node", "-v"], ["npm", "-v"]],
    "python": [["python3", "--version"]],
    "uv": [["uv", "--version"]],
    "cargo": [["cargo", "--version"], ["rustc", "--version"]],
    "go": [["go", "version"]],
    "docker": [["docker", "--version"]],
    "git": [["git", "--version"]],
    "ruby": [["ruby", "--version"]],
    "java": [["java", "-version"]],
}

# regex over command + output -> TOOL_PROBES key
_TOOL_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:npm|npx|node|yarn|pnpm)\b|ERR!|node_modules"), "node"),
    (re.compile(r"\b(?:python3?|pip3?|pytest)\b|Traceback|ModuleNotFoundError"), "python"),
    (re.compile(r"\buv\b"), "uv"),
    (re.compile(r"\b(?:cargo|rustc)\b|error\[E\d+\]"), "cargo"),
    (re.compile(r"\bgo (?:build|run|test|mod|get)\b"), "go"),
    (re.compile(r"\bdocker\b"), "docker"),
    (re.compile(r"\bgit\b"), "git"),
    (re.compile(r"\b(?:ruby|gem|bundle|rake)\b"), "ruby"),
    (re.compile(r"\b(?:java|javac|mvn|gradle)\b"), "java"),
]


@dataclass
class Context:
    os: str
    shell: str
    cwd: str
    tool_versions: dict[str, str] = field(default_factory=dict)
    project_files: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        lines = [f"OS: {self.os}", f"Shell: {self.shell}", f"cwd: {self.cwd}"]
        for cmd, version in self.tool_versions.items():
            lines.append(f"{cmd}: {version}")
        return "\n".join(lines)


def detect_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})".strip()
    if system == "Linux":
        try:
            info = platform.freedesktop_os_release()
            return f"{info.get('PRETTY_NAME', 'Linux')} ({platform.machine()})"
        except (OSError, AttributeError):
            return f"Linux {platform.release()} ({platform.machine()})"
    return f"{system} {platform.release()} ({platform.machine()})"


def detect_shell() -> str:
    return Path(os.environ.get("SHELL", "")).name or "unknown"


def detect_tools(text: str) -> list[str]:
    """Return TOOL_PROBES keys relevant to the command/output, in a stable order."""
    found = {key for pattern, key in _TOOL_HINTS if pattern.search(text)}
    return [key for key in TOOL_PROBES if key in found]


def _run_version(cmd: list[str], timeout: float) -> tuple[str, str] | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or proc.stderr).strip().splitlines()
    if proc.returncode != 0 or not out:
        return None
    return " ".join(cmd), out[0][:200]


def tool_versions(tools: list[str], timeout: float = VERSION_TIMEOUT) -> dict[str, str]:
    cmds = [cmd for tool in tools for cmd in TOOL_PROBES[tool]]
    if not cmds:
        return {}
    with ThreadPoolExecutor(max_workers=len(cmds)) as pool:
        results = pool.map(lambda c: _run_version(c, timeout), cmds)
    return dict(r for r in results if r is not None)


def project_snippets(cwd: Path) -> dict[str, str]:
    snippets: dict[str, str] = {}
    for name in PROJECT_FILES:
        path = cwd / name
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                lines = list(itertools.islice(f, SNIPPET_LINES))
        except OSError:
            continue
        snippet = "".join(lines)[:SNIPPET_CHARS].rstrip()
        if snippet:
            snippets[name] = snippet
    return snippets


def gather_context(command: str | None, output: str, cwd: Path | None = None) -> Context:
    cwd = cwd or Path.cwd()
    tools = detect_tools(f"{command or ''}\n{output}")
    return Context(
        os=detect_os(),
        shell=detect_shell(),
        cwd=str(cwd),
        tool_versions=tool_versions(tools),
        project_files=project_snippets(cwd),
    )
