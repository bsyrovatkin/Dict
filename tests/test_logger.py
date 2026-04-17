from __future__ import annotations

import re
from pathlib import Path

from dict.logger import append


LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| .+\n$")


def test_append_creates_file_and_writes_formatted_line(tmp_path: Path):
    log = tmp_path / "dict.log"
    append("hello world", path=log)
    content = log.read_text(encoding="utf-8")
    assert LINE_RE.match(content), f"bad line: {content!r}"
    assert "hello world" in content


def test_append_is_append_only(tmp_path: Path):
    log = tmp_path / "dict.log"
    append("one", path=log)
    append("two", path=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("| one")
    assert lines[1].endswith("| two")


def test_append_creates_parent_dir(tmp_path: Path):
    log = tmp_path / "nested" / "dict.log"
    append("x", path=log)
    assert log.exists()


def test_newlines_in_text_are_escaped(tmp_path: Path):
    log = tmp_path / "dict.log"
    append("line1\nline2", path=log)
    content = log.read_text(encoding="utf-8")
    assert content.count("\n") == 1
    assert "line1\\nline2" in content
