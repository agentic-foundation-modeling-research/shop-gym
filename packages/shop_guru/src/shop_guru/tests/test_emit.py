"""Unit tests for shop_guru.emit."""
from __future__ import annotations

import json
from pathlib import Path

from shop_guru.config import Shop
from shop_guru.emit import emit_pair, make_id


def test_make_id() -> None:
    assert make_id("mock_shop", "exact", 3) == "mock_shop-exact-3"


def test_emit_pair_writes_real_and_sandbox(tmp_path: Path, tiny_shop: Shop) -> None:
    tasks = [
        {"id": "tiny-exact-1", "type": "shopping", "intent": "find a thing"},
        {"id": "tiny-exact-2", "type": "shopping", "intent": "find another"},
    ]
    written = emit_pair(tasks, tiny_shop, tmp_path, "test_skill")

    assert {p.name for p in written} == {
        "test_skill_real.json",
        "test_skill_sandbox.json",
    }
    real = json.loads((tmp_path / "test_skill_real.json").read_text())
    sandbox = json.loads((tmp_path / "test_skill_sandbox.json").read_text())

    assert [t["id"] for t in real] == ["tiny-exact-1", "tiny-exact-2"]
    assert all(t["url"] == "https://tiny.example" for t in real)
    assert all(t["url"] == "https://sandbox.example/?token=abc" for t in sandbox)


def test_emit_pair_writes_tbd_sentinel_without_sandbox(
    tmp_path: Path, tiny_shop_no_sandbox: Shop
) -> None:
    tasks = [{"id": "tiny-exact-1", "type": "shopping", "intent": "x"}]
    written = emit_pair(tasks, tiny_shop_no_sandbox, tmp_path, "test_skill")

    names = {p.name for p in written}
    assert "test_skill_real.json" in names
    assert "test_skill_sandbox.TBD" in names
    assert not (tmp_path / "test_skill_sandbox.json").exists()


def test_emit_pair_handles_skip_real(tmp_path: Path, tiny_shop: Shop) -> None:
    tasks = [{"id": "task-1", "intent": "foo"}]
    written = emit_pair(tasks, tiny_shop, tmp_path, "ShopGuru_test", skip_real=True)

    assert len(written) == 1
    assert written[0].name == "ShopGuru_test_sandbox.json"

    # Sandbox has tasks with sandbox_url injected
    sandbox_data = json.loads(written[0].read_text())
    assert sandbox_data[0]["url"] == "https://sandbox.example/?token=abc"

    real_path = tmp_path / "ShopGuru_test_real.json"
    assert not real_path.exists()


def test_emit_pair_merges_by_id(tmp_path: Path, tiny_shop: Shop) -> None:
    """Calling emit_pair twice for different shops populates the same file."""
    shop_a = tiny_shop
    shop_b = Shop(
        **{
            **tiny_shop.__dict__,
            "slug": "other",
            "real_url": "https://other.example",
            "sandbox_url": "https://other-sandbox.example/?token=xyz",
        }
    )

    emit_pair(
        [{"id": "tiny-exact-1", "type": "shopping", "intent": "x"}],
        shop_a,
        tmp_path,
        "test_skill",
    )
    emit_pair(
        [{"id": "other-exact-1", "type": "shopping", "intent": "y"}],
        shop_b,
        tmp_path,
        "test_skill",
    )

    real = json.loads((tmp_path / "test_skill_real.json").read_text())
    ids = sorted(t["id"] for t in real)
    assert ids == ["other-exact-1", "tiny-exact-1"]


def test_emit_pair_is_deterministic_by_id(tmp_path: Path, tiny_shop: Shop) -> None:
    tasks = [
        {"id": "tiny-exact-2", "type": "shopping", "intent": "b"},
        {"id": "tiny-exact-1", "type": "shopping", "intent": "a"},
    ]
    emit_pair(tasks, tiny_shop, tmp_path, "test_skill")
    first = (tmp_path / "test_skill_real.json").read_text()

    # Emit again (tasks in reverse order) — content must be identical.
    emit_pair(list(reversed(tasks)), tiny_shop, tmp_path, "test_skill")
    second = (tmp_path / "test_skill_real.json").read_text()
    assert first == second
