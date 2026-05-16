from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dict import paste as paste_mod


def test_paste_text_saves_copies_pastes_then_schedules_restore():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = "OLD"
    mock_keyboard = MagicMock()
    mock_timer = MagicMock()

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", return_value=mock_timer) as timer_ctor:
        ok = paste_mod.paste_text("NEW")

    assert ok is True
    # Order matters: read saved -> copy new -> send paste -> schedule restore
    mock_pyperclip.paste.assert_called_once_with()
    mock_pyperclip.copy.assert_called_once_with("NEW")
    mock_keyboard.send.assert_called_once_with("ctrl+v")
    timer_ctor.assert_called_once()
    mock_timer.start.assert_called_once()


def test_paste_text_releases_hotkey_before_sending_ctrl_v():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = ""
    mock_keyboard = MagicMock()

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", return_value=MagicMock()):
        paste_mod.paste_text("X", current_hotkey="ctrl+shift+v")

    # release must come BEFORE send
    call_order = [c[0] for c in mock_keyboard.method_calls]
    assert call_order.index("release") < call_order.index("send")
    mock_keyboard.release.assert_called_once_with("ctrl+shift+v")


def test_paste_text_returns_false_when_send_fails():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = "OLD"
    mock_keyboard = MagicMock()
    mock_keyboard.send.side_effect = RuntimeError("no perms")

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer") as timer_ctor:
        ok = paste_mod.paste_text("NEW")

    assert ok is False
    timer_ctor.assert_not_called()  # do NOT restore — text stays in clipboard


def test_paste_text_release_failure_does_not_block_paste():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = ""
    mock_keyboard = MagicMock()
    mock_keyboard.release.side_effect = RuntimeError("hotkey unknown")

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", return_value=MagicMock()):
        ok = paste_mod.paste_text("X", current_hotkey="weird+combo")

    # release failed but send still happened
    assert ok is True
    mock_keyboard.send.assert_called_once_with("ctrl+v")


def test_paste_text_restore_timer_callback_swallows_failures():
    """The timer fires later; if pyperclip.copy raises during restore, no crash."""
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = "OLD"
    mock_keyboard = MagicMock()

    captured = {}

    def fake_timer(delay, fn):
        captured["fn"] = fn
        return MagicMock()

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", side_effect=fake_timer):
        paste_mod.paste_text("NEW")

    # Now make restore fail
    mock_pyperclip.copy.side_effect = RuntimeError("clip locked")
    captured["fn"]()  # must not raise
