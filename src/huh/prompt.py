"""Builds the LLM prompt and parses the reply into a diagnosis and a fix."""

from __future__ import annotations

import re
from dataclasses import dataclass

from huh.context import Context

# Language code -> how the model is told to write the diagnosis.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh-CN": "Simplified Chinese (简体中文)",
}
DEFAULT_LANGUAGE = "en"

_LANGUAGE_ALIASES = {
    "en": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-sg": "zh-CN",
    "cn": "zh-CN",
    "chinese": "zh-CN",
    "中文": "zh-CN",
    "简体中文": "zh-CN",
}


def normalize_language(value: str) -> str | None:
    """Map user input like 'zh', 'zh_CN' or '中文' to a LANGUAGES key; None if unknown."""
    key = value.strip().replace("_", "-").lower()
    return _LANGUAGE_ALIASES.get(key) or _LANGUAGE_ALIASES.get(key.split(".")[0])


_SYSTEM_TEMPLATE = """\
You diagnose failed terminal commands for a developer. Be brief and concrete.

Reply in exactly this format and nothing else:
<diagnosis>1-3 plain sentences: what went wrong and why.</diagnosis>
<fix>ONE shell command that fixes it, on a single line, with no backticks or prose.</fix>

Rules:
- {language_rule}
- Give at most one command. If no single safe command fixes it (code changes needed, \
the cause is ambiguous, or the fix is destructive such as rm -rf, force-push, or \
dropping data), write <fix>none</fix> and say what to do in the diagnosis.
- Prefer the project's own tooling (e.g. `uv add` when pyproject.toml shows uv, \
`npm install` when package.json is present).
- The fix must be runnable as-is from the given cwd: no placeholders like <name> or \
YOUR_KEY. Values shown as [REDACTED] were removed for privacy; never ask for or echo them.
- Do not re-run the original command as the fix unless something else changes."""

_LANGUAGE_RULES = {
    "en": "Write the diagnosis in English.",
    "zh-CN": (
        "Write the diagnosis in Simplified Chinese (简体中文), even when the error output "
        "is in English. Keep commands, code, file paths, package names and quoted error "
        "messages untranslated. Keep the <diagnosis> and <fix> tags exactly as shown."
    ),
}


def system_prompt(language: str = DEFAULT_LANGUAGE) -> str:
    return _SYSTEM_TEMPLATE.format(
        language_rule=_LANGUAGE_RULES.get(language, _LANGUAGE_RULES[DEFAULT_LANGUAGE])
    )


OPEN_TAG = "<diagnosis>"
CLOSE_TAG = "</diagnosis>"
_FIX_RE = re.compile(r"<fix>(.*?)</fix>", re.DOTALL | re.IGNORECASE)
_DIAG_RE = re.compile(r"<diagnosis>(.*?)(?:</diagnosis>|$)", re.DOTALL | re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"<[A-Za-z_ -]+>|\[REDACTED\]|YOUR_[A-Z_]+")
_NO_FIX = {"", "none", "n/a", "no fix", "null"}


def build_user_message(
    output: str, context: Context, command: str | None = None, exit_code: int | None = None
) -> str:
    """Assemble the user turn. All inputs must already be redacted."""
    parts: list[str] = []
    if command:
        parts.append(f"<command>\n{command}\n</command>")
    if exit_code is not None:
        parts.append(f"<exit_code>{exit_code}</exit_code>")
    parts.append(f"<environment>\n{context.render()}\n</environment>")
    if context.project_files:
        files = "\n".join(
            f'<file name="{name}">\n{body}\n</file>' for name, body in context.project_files.items()
        )
        parts.append(f"<project_files>\n{files}\n</project_files>")
    parts.append(f"<output>\n{output}\n</output>")
    return "\n\n".join(parts)


@dataclass
class Reply:
    raw: str
    diagnosis: str | None
    fix: str | None
    runnable: bool = False


def _clean_fix(text: str) -> str:
    text = text.strip().strip("`").strip()
    if text.startswith("$ "):
        text = text[2:]
    return text.strip()


def parse_reply(raw: str) -> Reply:
    """Parse ``<diagnosis>``/``<fix>`` tags. Unparseable replies keep only ``raw``."""
    diag_match = _DIAG_RE.search(raw)
    diagnosis = diag_match.group(1).strip() if diag_match else None

    fix: str | None = None
    fix_match = _FIX_RE.search(raw)
    if fix_match:
        candidate = _clean_fix(fix_match.group(1))
        if candidate.lower().rstrip(".") not in _NO_FIX:
            fix = candidate

    runnable = (
        diagnosis is not None
        and fix is not None
        and "\n" not in fix
        and not _PLACEHOLDER_RE.search(fix)
    )
    return Reply(raw=raw, diagnosis=diagnosis or None, fix=fix, runnable=runnable)


class DiagnosisStream:
    """Incrementally extracts the text inside ``<diagnosis>`` for live display.

    ``feed`` returns the newly displayable diagnosis text. It holds back just
    enough characters to recognise a closing tag split across chunks.
    """

    def __init__(self) -> None:
        self.raw = ""
        self._state = "before"  # before -> inside -> after
        self._pending = ""
        self._emitted = False

    def feed(self, chunk: str) -> str:
        self.raw += chunk
        if self._state == "after":
            return ""
        self._pending += chunk
        out = ""
        if self._state == "before":
            idx = self._pending.lower().find(OPEN_TAG)
            if idx == -1:
                return ""
            self._pending = self._pending[idx + len(OPEN_TAG) :].lstrip()
            self._state = "inside"
        if self._state == "inside":
            if not self._emitted:
                self._pending = self._pending.lstrip()
            idx = self._pending.lower().find(CLOSE_TAG)
            if idx != -1:
                out += self._pending[:idx].rstrip()
                self._pending = ""
                self._state = "after"
            else:
                safe = len(self._pending) - (len(CLOSE_TAG) - 1)
                if safe > 0:
                    out += self._pending[:safe]
                    self._pending = self._pending[safe:]
        self._emitted = self._emitted or bool(out)
        return out

    @property
    def started(self) -> bool:
        return self._state != "before"

    def flush(self) -> str:
        """Return any held-back diagnosis text once the stream has ended."""
        if self._state != "inside":
            return ""
        out, self._pending = self._pending.rstrip(), ""
        return out

    def result(self) -> Reply:
        return parse_reply(self.raw)
