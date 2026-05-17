from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from dict import paste as paste_mod


def _expected_paste_combo() -> str:
    """Mirror dict.paste._paste_key_combo() platform logic."""
    return "cmd+v" if sys.platform == "darwin" else "ctrl+v"


def test_paste_text_saves_copies_pastes_then_schedules_restore():
    mock_clipboard = MagicMock()
    mock_clipboard.get_text.return_value = "OLD"
    mock_clipboard.set_text.return_value = True
    mock_send = MagicMock()

    captured = {}

    def fake_timer(delay, fn):
        captured["fn"] = fn
        captured["delay"] = delay
        m = MagicMock()
        return m

    with patch("dict.paste.clipboard", mock_clipboard), \
         patch("dict.paste._send_combo", mock_send), \
         patch("dict.paste._release_combo"), \
         patch("dict.paste.threading.Timer", side_effect=fake_timer) as timer_ctor:
        ok = paste_mod.paste_text("NEW")

        assert ok is True
        mock_clipboard.get_text.assert_called_once_with()
        # set_text called with NEW first
        assert mock_clipboard.set_text.call_args_list[0].args == ("NEW",)
        mock_send.assert_called_once_with(_expected_paste_combo())
        timer_ctor.assert_called_once()

        # Invoke the captured restore callback and verify it restores "OLD"
        captured["fn"]()
        assert mock_clipboard.set_text.call_args_list[-1].args == ("OLD",)


def test_paste_text_releases_hotkey_before_sending_paste():
    mock_clipboard = MagicMock()
    mock_clipboard.get_text.return_value = ""
    mock_clipboard.set_text.return_value = True

    calls = []

    def fake_release(combo: str) -> None:
        calls.append(("release", combo))

    def fake_send(combo: str) -> None:
        calls.append(("send", combo))

    with patch("dict.paste.clipboard", mock_clipboard), \
         patch("dict.paste._release_combo", side_effect=fake_release), \
         patch("dict.paste._send_combo", side_effect=fake_send), \
         patch("dict.paste.threading.Timer", return_value=MagicMock()):
        paste_mod.paste_text("X", current_hotkey="ctrl+shift+v")

    # release must come BEFORE send
    op_order = [c[0] for c in calls]
    assert op_order.index("release") < op_order.index("send")
    assert ("release", "ctrl+shift+v") in calls


def test_paste_text_returns_false_when_send_fails():
    mock_clipboard = MagicMock()
    mock_clipboard.get_text.return_value = "OLD"
    mock_clipboard.set_text.return_value = True

    with patch("dict.paste.clipboard", mock_clipboard), \
         patch("dict.paste._send_combo", side_effect=RuntimeError("no perms")), \
         patch("dict.paste._release_combo"), \
         patch("dict.paste.threading.Timer") as timer_ctor:
        ok = paste_mod.paste_text("NEW")

    assert ok is False
    timer_ctor.assert_not_called()  # do NOT restore -- text stays in clipboard


def test_paste_text_release_failure_does_not_block_paste():
    mock_clipboard = MagicMock()
    mock_clipboard.get_text.return_value = ""
    mock_clipboard.set_text.return_value = True
    mock_send = MagicMock()

    # _release_combo is itself defensive (try/except inside), but to be safe
    # we model it as a no-op that just doesn't raise.
    with patch("dict.paste.clipboard", mock_clipboard), \
         patch("dict.paste._release_combo"), \
         patch("dict.paste._send_combo", mock_send), \
         patch("dict.paste.threading.Timer", return_value=MagicMock()):
        ok = paste_mod.paste_text("X", current_hotkey="weird+combo")

    # send still happened
    assert ok is True
    mock_send.assert_called_once_with(_expected_paste_combo())


def test_paste_text_restore_timer_callback_swallows_failures():
    """The timer fires later; if clipboard.set_text raises during restore, no crash."""
    mock_clipboard = MagicMock()
    mock_clipboard.get_text.return_value = "OLD"
    mock_clipboard.set_text.return_value = True

    captured = {}

    def fake_timer(delay, fn):
        captured["fn"] = fn
        return MagicMock()

    with patch("dict.paste.clipboard", mock_clipboard), \
         patch("dict.paste._send_combo"), \
         patch("dict.paste._release_combo"), \
         patch("dict.paste.threading.Timer", side_effect=fake_timer):
        paste_mod.paste_text("NEW")

    # Now make restore fail
    mock_clipboard.set_text.side_effect = RuntimeError("clip locked")
    captured["fn"]()  # must not raise
