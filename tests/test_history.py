from __future__ import annotations

from datetime import datetime

from dict.history import History, Entry


def test_push_stores_entry_with_timestamp():
    h = History(maxlen=5)
    before = datetime.now()
    h.push("hello")
    after = datetime.now()
    items = h.items()
    assert len(items) == 1
    assert items[0].text == "hello"
    assert before <= items[0].timestamp <= after


def test_items_returns_newest_first():
    h = History(maxlen=5)
    h.push("first")
    h.push("second")
    h.push("third")
    texts = [e.text for e in h.items()]
    assert texts == ["third", "second", "first"]


def test_maxlen_evicts_oldest():
    h = History(maxlen=3)
    for t in ["a", "b", "c", "d", "e"]:
        h.push(t)
    texts = [e.text for e in h.items()]
    assert texts == ["e", "d", "c"]


def test_entry_is_immutable_namedtuple():
    e = Entry(timestamp=datetime.now(), text="x")
    import pytest
    with pytest.raises((AttributeError, Exception)):
        e.text = "y"  # type: ignore[misc]
