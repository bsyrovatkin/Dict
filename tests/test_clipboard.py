from __future__ import annotations

from dict import clipboard


def test_set_text_calls_pyperclip(mocker):
    copy = mocker.patch("dict.clipboard.pyperclip.copy")
    ok = clipboard.set_text("hi")
    assert ok is True
    copy.assert_called_once_with("hi")


def test_set_text_returns_false_on_failure(mocker):
    mocker.patch("dict.clipboard.pyperclip.copy", side_effect=RuntimeError("nope"))
    ok = clipboard.set_text("hi")
    assert ok is False


def test_get_text_returns_pyperclip_paste(mocker):
    mocker.patch("dict.clipboard.pyperclip.paste", return_value="hello")
    assert clipboard.get_text() == "hello"


def test_get_text_returns_empty_on_pyperclip_failure(mocker):
    mocker.patch("dict.clipboard.pyperclip.paste", side_effect=RuntimeError("boom"))
    assert clipboard.get_text() == ""
