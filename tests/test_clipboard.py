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
