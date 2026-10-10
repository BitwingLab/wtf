"""Shrink long command output while keeping the parts that explain the failure."""

from __future__ import annotations

import re

ERROR_MARKERS = re.compile(
    r"error|traceback|exception|fatal|failed|failure|panic|ERR!|cannot|not found|denied",
    re.IGNORECASE,
)

MAX_LINES = 120
TAIL_LINES = 50
MAX_HEAD_ERRORS = 20
MAX_LINE_CHARS = 500


def _omitted(n: int) -> str:
    return f"… [{n} line{'s' if n != 1 else ''} omitted] …"


def _clip(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return line[:MAX_LINE_CHARS] + f"… [{len(line) - MAX_LINE_CHARS} chars omitted]"


def trim(
    text: str,
    max_lines: int = MAX_LINES,
    tail: int = TAIL_LINES,
    max_head_errors: int = MAX_HEAD_ERRORS,
) -> str:
    """Keep error-marker lines from before the tail, plus the last ``tail`` lines.

    Output at or under ``max_lines`` lines is returned unchanged (apart from
    clipping very long lines). Gaps are replaced with an "omitted" marker.
    """
    lines = [_clip(line) for line in text.splitlines()]
    if len(lines) <= max_lines:
        return "\n".join(lines)

    tail_start = len(lines) - tail
    keep = [i for i in range(tail_start) if ERROR_MARKERS.search(lines[i])][:max_head_errors]
    keep.extend(range(tail_start, len(lines)))

    out: list[str] = []
    prev = -1
    for i in keep:
        if i - prev > 1:
            out.append(_omitted(i - prev - 1))
        out.append(lines[i])
        prev = i
    return "\n".join(out)
