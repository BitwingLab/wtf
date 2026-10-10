import pytest

from huh.context import Context
from huh.prompt import DiagnosisStream, build_user_message, parse_reply

GOOD = (
    "<diagnosis>Python can't find the package `requests`; it isn't installed "
    "in this environment.</diagnosis>\n<fix>uv add requests</fix>"
)


def test_parse_good_reply() -> None:
    r = parse_reply(GOOD)
    assert r.diagnosis is not None and r.diagnosis.startswith("Python can't find")
    assert r.fix == "uv add requests"
    assert r.runnable


@pytest.mark.parametrize("fix", ["none", "None", " NONE. ", "", "n/a"])
def test_no_fix(fix: str) -> None:
    r = parse_reply(f"<diagnosis>Needs a code change.</diagnosis><fix>{fix}</fix>")
    assert r.fix is None
    assert not r.runnable


def test_missing_fix_tag() -> None:
    r = parse_reply("<diagnosis>Just this.</diagnosis>")
    assert r.diagnosis == "Just this."
    assert r.fix is None


def test_backticks_and_prompt_stripped() -> None:
    r = parse_reply("<diagnosis>x</diagnosis><fix>`$ npm install`</fix>")
    assert r.fix == "npm install"
    r = parse_reply("<diagnosis>x</diagnosis><fix>\n```\npip install foo\n```\n</fix>")
    assert r.fix == "pip install foo"


def test_unparseable_reply_keeps_raw() -> None:
    raw = "Sure! The problem is that the module is missing. Run pip install foo."
    r = parse_reply(raw)
    assert r.diagnosis is None
    assert r.fix is None
    assert r.raw == raw
    assert not r.runnable


def test_fix_without_diagnosis_not_runnable() -> None:
    r = parse_reply("<fix>rm -rf node_modules</fix>")
    assert not r.runnable


@pytest.mark.parametrize(
    "fix",
    ["git clone <repo-url>", "export API_KEY=[REDACTED]", "echo YOUR_API_KEY", "a\nb"],
)
def test_placeholders_and_multiline_not_runnable(fix: str) -> None:
    r = parse_reply(f"<diagnosis>x</diagnosis><fix>{fix}</fix>")
    assert not r.runnable


def test_unclosed_diagnosis_still_parsed() -> None:
    r = parse_reply("<diagnosis>Cut off mid-sentence")
    assert r.diagnosis == "Cut off mid-sentence"


def test_case_insensitive_tags() -> None:
    r = parse_reply("<Diagnosis>Hi.</Diagnosis><FIX>ls</FIX>")
    assert r.diagnosis == "Hi."
    assert r.fix == "ls"


def _stream(chunks: list[str]) -> tuple[str, DiagnosisStream]:
    s = DiagnosisStream()
    shown = "".join(s.feed(c) for c in chunks) + s.flush()
    return shown, s


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7, 13, 1000])
def test_stream_any_chunking(size: int) -> None:
    chunks = [GOOD[i : i + size] for i in range(0, len(GOOD), size)]
    shown, s = _stream(chunks)
    assert shown == parse_reply(GOOD).diagnosis
    assert s.result().fix == "uv add requests"


def test_stream_strips_leading_whitespace_across_chunks() -> None:
    shown, _ = _stream(["<diagnosis>", "\n  ", "Hello", " world.\n", "</diagnosis>"])
    assert shown == "Hello world."


def test_stream_never_shows_fix_or_tags() -> None:
    shown, _ = _stream(list(GOOD))
    assert "<" not in shown
    assert "uv add" not in shown


def test_stream_without_tags_shows_nothing() -> None:
    shown, s = _stream(["Just plain ", "text."])
    assert shown == ""
    assert not s.started
    assert s.result().raw == "Just plain text."


def test_stream_unclosed_flushes() -> None:
    shown, _ = _stream(["<diagnosis>abc", "def"])
    assert shown == "abcdef"


def test_build_user_message() -> None:
    ctx = Context(
        os="macOS 15",
        shell="zsh",
        cwd="/proj",
        tool_versions={"python3 --version": "Python 3.12.1"},
        project_files={"pyproject.toml": "[project]\nname='x'"},
    )
    msg = build_user_message("boom", ctx, command="python app.py")
    assert msg.index("<command>") < msg.index("<environment>") < msg.index("<output>")
    assert "python app.py" in msg
    assert "Python 3.12.1" in msg
    assert '<file name="pyproject.toml">' in msg
    assert msg.rstrip().endswith("boom\n</output>")


def test_build_user_message_minimal() -> None:
    msg = build_user_message("boom", Context(os="Linux", shell="bash", cwd="/"))
    assert "<command>" not in msg
    assert "<project_files>" not in msg


# --- response language ---------------------------------------------------------

from huh.prompt import LANGUAGES, normalize_language, system_prompt  # noqa: E402


def test_system_prompt_english_default() -> None:
    sp = system_prompt()
    assert "Write the diagnosis in English." in sp
    assert "简体中文" not in sp
    assert "<diagnosis>" in sp and "<fix>" in sp


def test_system_prompt_chinese() -> None:
    sp = system_prompt("zh-CN")
    assert "Simplified Chinese (简体中文)" in sp
    assert "untranslated" in sp
    # The reply format the parser depends on is unchanged.
    assert "<diagnosis>1-3 plain sentences" in sp
    assert "<fix>ONE shell command" in sp


def test_system_prompt_unknown_falls_back_to_english() -> None:
    assert system_prompt("xx") == system_prompt("en")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("en", "en"),
        ("English", "en"),
        ("en_US", "en"),
        ("en_US.UTF-8", "en"),
        ("zh-CN", "zh-CN"),
        ("zh_cn", "zh-CN"),
        ("zh", "zh-CN"),
        ("zh-Hans", "zh-CN"),
        ("zh_CN.UTF-8", "zh-CN"),
        ("中文", "zh-CN"),
        (" 简体中文 ", "zh-CN"),
        ("fr", None),
        ("", None),
    ],
)
def test_normalize_language(value: str, expected: str | None) -> None:
    assert normalize_language(value) == expected


def test_every_language_has_a_rule() -> None:
    for code in LANGUAGES:
        assert system_prompt(code) != "" and normalize_language(code) == code


def test_stream_chinese_diagnosis() -> None:
    raw = "<diagnosis>缺少 `requests` 包，当前环境未安装。</diagnosis>\n<fix>uv add requests</fix>"
    shown, s = _stream([raw[i : i + 3] for i in range(0, len(raw), 3)])
    assert shown == "缺少 `requests` 包，当前环境未安装。"
    assert s.result().fix == "uv add requests"
    assert s.result().runnable
