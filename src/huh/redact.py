"""Secret redaction. Runs on everything before it is sent to an LLM."""

from __future__ import annotations

import re
from collections.abc import Callable

REDACTED = "[REDACTED]"

# --- Names that mark a variable/field as holding a secret --------------------
# Three spellings are recognised; CamelCase *type* names like KeyError or
# TokenError are deliberately not matched so error messages survive.
_UPPER_WORD = r"(?:PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIALS?|APIKEY|API_KEY)"
_LOWER_WORD = r"(?:password|passwd|secret|token|credentials?|apikey|api[_-]key)"
_SECRET_NAME = rf"""
    (?:
        (?:[A-Z0-9]+_)*{_UPPER_WORD}(?:_[A-Z0-9]+)*       # GITHUB_TOKEN, DB_PASSWORD
      | (?:[A-Z0-9]+_)+(?:KEY|PWD)(?:_[A-Z0-9]+)*         # AWS_SECRET_ACCESS_KEY, DB_PWD
      | KEY(?:_[A-Z0-9]+)*                                 # KEY, KEY_ID
      | (?:[a-z0-9]+[_.-])*{_LOWER_WORD}(?:[_.-][a-z0-9]+)*  # password, access_token
      | (?:[a-z0-9]+[_.-])+key(?:[_.-][a-z0-9]+)*         # secret_key, signing-key
      | [a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)*(?:Key|Token|Secret|Password)  # apiKey
    )
"""

_ASSIGNMENT = re.compile(
    rf"""(?x)
    (?<![A-Za-z0-9_.-])
    (?P<name>{_SECRET_NAME})
    (?P<sep>["']?[ \t]*[:=][ \t]*)   # separator, never crosses a newline
    (?P<quote>["']?)
    (?!\[REDACTED\]|=)               # skip already-redacted values and `==`
    (?P<value>[^\s"',;]+)
    """
)

# Names matched above that are not secrets.
_SAFE_NAMES = {
    "primary_key",
    "foreign_key",
    "sort_key",
    "partition_key",
    "primarykey",
    "foreignkey",
    "sortkey",
    "partitionkey",
    "public_key",
    "publickey",
    "keyboard",
}


def _redact_assignment(m: re.Match[str]) -> str:
    if m.group("name").lower() in _SAFE_NAMES:
        return m.group(0)
    return f"{m.group('name')}{m.group('sep')}{m.group('quote')}{REDACTED}"


_Replacement = str | Callable[[re.Match[str]], str]

# Order matters: specific formats first, generic patterns last.
_PATTERNS: list[tuple[re.Pattern[str], _Replacement]] = [
    # PEM private keys (multi-line).
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED,
    ),
    # Anthropic keys: sk-ant-api03-..., sk-ant-admin01-...
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"), REDACTED),
    # OpenAI keys: sk-..., sk-proj-..., sk-svcacct-...
    (re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"), REDACTED),
    # GitHub tokens.
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    # AWS access key IDs.
    (re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA)[A-Z0-9]{16}\b"), REDACTED),
    # Slack tokens.
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), REDACTED),
    # Authorization headers: Bearer / Basic / Token.
    (
        re.compile(r"(?i)\b(authorization[ \t]*[:=][ \t]*(?:bearer|basic|token)[ \t]+)[^\s'\"]+"),
        rf"\1{REDACTED}",
    ),
    (re.compile(r"(?i)\b(bearer[ \t]+)(?!\[REDACTED\])[A-Za-z0-9._~+/=-]{8,}"), rf"\1{REDACTED}"),
    # Credentials in URLs: scheme://user:pass@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+(@)"),
        rf"\1{REDACTED}\2",
    ),
    # CLI flags: --password foo, --token=foo.
    (
        re.compile(
            r"(?i)(--(?:password|passwd|token|api-key|apikey|secret|auth-token)(?:=|[ \t]+))"
            r"(?!\[REDACTED\])([^\s'\"]+)"
        ),
        rf"\1{REDACTED}",
    ),
    # KEY=value / KEY: value / "key": "value" where the name looks secret.
    (_ASSIGNMENT, _redact_assignment),
]


def redact(text: str) -> str:
    """Return ``text`` with common secret formats replaced by ``[REDACTED]``."""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
