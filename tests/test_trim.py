from huh.trim import MAX_LINE_CHARS, trim


def numbered(n: int) -> list[str]:
    return [f"line {i}" for i in range(n)]


def test_short_output_unchanged() -> None:
    text = "\n".join(numbered(100))
    assert trim(text) == text


def test_long_output_keeps_tail_with_marker() -> None:
    out = trim("\n".join(numbered(500))).splitlines()
    assert out[0] == "… [450 lines omitted] …"
    assert out[1:] == [f"line {i}" for i in range(450, 500)]


def test_keeps_early_error_lines() -> None:
    lines = numbered(500)
    lines[10] = "Traceback (most recent call last):"
    lines[200] = "npm ERR! missing script: build"
    out = trim("\n".join(lines)).splitlines()
    assert out == [
        "… [10 lines omitted] …",
        "Traceback (most recent call last):",
        "… [189 lines omitted] …",
        "npm ERR! missing script: build",
        "… [249 lines omitted] …",
        *[f"line {i}" for i in range(450, 500)],
    ]


def test_contiguous_errors_have_no_marker_between() -> None:
    lines = numbered(300)
    lines[0] = "error: one"
    lines[1] = "error: two"
    out = trim("\n".join(lines)).splitlines()
    assert out[:3] == ["error: one", "error: two", "… [248 lines omitted] …"]


def test_caps_number_of_head_errors() -> None:
    lines = [f"error {i}" for i in range(400)]
    out = trim("\n".join(lines), max_head_errors=5).splitlines()
    assert out[:5] == [f"error {i}" for i in range(5)]
    assert out[5] == "… [345 lines omitted] …"
    assert len(out) == 5 + 1 + 50


def test_singular_marker() -> None:
    lines = numbered(200)
    lines[148] = "fatal: thing"
    out = trim("\n".join(lines)).splitlines()
    assert "… [1 line omitted] …" in out


def test_long_lines_clipped() -> None:
    out = trim("x" * (MAX_LINE_CHARS + 100))
    assert out.startswith("x" * MAX_LINE_CHARS)
    assert out.endswith("[100 chars omitted]")
