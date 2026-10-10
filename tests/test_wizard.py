import pytest

from huh.wizard import _default_language


@pytest.fixture(autouse=True)
def no_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)


def test_default_language_from_saved_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert _default_language({"language": "zh_CN"}) == "zh-CN"


def test_default_language_from_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    assert _default_language({}) == "zh-CN"


def test_default_language_unknown_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert _default_language({}) == "en"


def test_default_language_nothing_set() -> None:
    assert _default_language({}) == "en"
