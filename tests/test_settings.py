from __future__ import annotations

from pathlib import Path

from dict import settings as settings_mod


def test_load_returns_defaults_when_no_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "s.json")
    s = settings_mod.load()
    assert s.hotkey  # non-empty default from config
    assert s.model_size == "small"


def test_save_and_load_roundtrip(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "s.json")
    s = settings_mod.Settings(hotkey="ctrl+alt+d", model_size="medium",
                              language="ru", volume=0.5)
    settings_mod.save(s)
    loaded = settings_mod.load()
    assert loaded.hotkey == "ctrl+alt+d"
    assert loaded.model_size == "medium"
    assert loaded.language == "ru"
    assert loaded.volume == 0.5


def test_load_ignores_unknown_keys(monkeypatch, tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text('{"hotkey": "f9", "unknown_field": 42}', encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", p)
    s = settings_mod.load()
    assert s.hotkey == "f9"
    assert not hasattr(s, "unknown_field")


def test_load_falls_back_on_corrupt_file(monkeypatch, tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text("not json{", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", p)
    s = settings_mod.load()
    # Does not raise; returns defaults
    assert s.model_size == "small"
