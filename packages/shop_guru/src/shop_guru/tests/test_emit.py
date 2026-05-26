"""Unit tests for shop_guru.emit."""
from __future__ import annotations

import json
from pathlib import Path

from shop_guru.config import Shop
from shop_guru.emit import emit_tasks, make_id


def test_make_id() -> None:
    assert make_id("mock_shop", "exact", 3) == "mock_shop-exact-3"


def test_emit_tasks_writes_single_file(tmp_path: Path, tiny_shop: Shop) -> None:
    tasks = [
        {"id": "tiny-exact-1", "type": "shopping", "intent": "find a thing"},
        {"id": "tiny-exact-2", "type": "shopping", "intent": "find another"},
    ]
    written = emit_tasks(tasks, tiny_shop, tmp_path, "test_skill")

    assert {p.name for p in written} == {"test_skill.json"}
    payload = json.loads((tmp_path / "test_skill.json").read_text())
    assert [t["id"] for t in payload] == ["tiny-exact-1", "tiny-exact-2"]
    assert all(t["url"] == "https://tiny.example" for t in payload)


def test_emit_tasks_merges_by_id(tmp_path: Path, tiny_shop: Shop) -> None:
    """Calling emit_tasks twice for different shops populates the same file."""
    shop_a = tiny_shop
    shop_b = Shop(
        **{
            **tiny_shop.__dict__,
            "slug": "other",
            "shop_url": "https://other.example",
        }
    )

    emit_tasks(
        [{"id": "tiny-exact-1", "type": "shopping", "intent": "x"}],
        shop_a,
        tmp_path,
        "test_skill",
    )
    emit_tasks(
        [{"id": "other-exact-1", "type": "shopping", "intent": "y"}],
        shop_b,
        tmp_path,
        "test_skill",
    )

    payload = json.loads((tmp_path / "test_skill.json").read_text())
    ids = sorted(t["id"] for t in payload)
    assert ids == ["other-exact-1", "tiny-exact-1"]


def test_emit_tasks_is_deterministic_by_id(tmp_path: Path, tiny_shop: Shop) -> None:
    tasks = [
        {"id": "tiny-exact-2", "type": "shopping", "intent": "b"},
        {"id": "tiny-exact-1", "type": "shopping", "intent": "a"},
    ]
    emit_tasks(tasks, tiny_shop, tmp_path, "test_skill")
    first = (tmp_path / "test_skill.json").read_text()

    # Emit again (tasks in reverse order) — content must be identical.
    emit_tasks(list(reversed(tasks)), tiny_shop, tmp_path, "test_skill")
    second = (tmp_path / "test_skill.json").read_text()
    assert first == second
