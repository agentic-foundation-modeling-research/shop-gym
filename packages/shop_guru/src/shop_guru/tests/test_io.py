"""Unit tests for :mod:`shop_guru.io`."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from shop_guru.config import Shop
from shop_guru.io import load_shop_data


def test_load_shop_data_falls_back_to_raw_data_for_stats(
    tmp_path: Path,
    tiny_shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    """When ``data/stats.json`` is absent but ``raw_data/stats.json`` exists
    (the layout produced by ``shop_arena.gen.multi_pipeline``), shop_guru must
    load the latter instead of silently defaulting to ``{}``.
    """
    root = tmp_path / "shop_arena_root"
    shop_dir = root / "outputs" / "shops" / "tiny.example"
    data_dir = shop_dir / "data"
    raw_data_dir = shop_dir / "raw_data"
    data_dir.mkdir(parents=True)
    raw_data_dir.mkdir(parents=True)

    # Minimal `data/` files. Note: no stats.json here.
    (data_dir / "store.json").write_text(json.dumps({"name": "Tiny"}))
    (data_dir / "products.json").write_text("[]")
    (data_dir / "collections.json").write_text("[]")
    (data_dir / "pages.json").write_text("[]")
    (data_dir / "policies.json").write_text("[]")
    (data_dir / "navigation.json").write_text("{}")

    # Stats live under raw_data/ (composite-shop layout).
    raw_stats = {
        "option_patterns": [
            {"name": "Color", "count": 1, "sample_values": ["Red"]},
        ]
    }
    (raw_data_dir / "stats.json").write_text(json.dumps(raw_stats))

    from shop_guru import _paths
    monkeypatch.setattr(_paths, "_REPO_ROOT", root)

    with caplog.at_level(logging.WARNING, logger="shop_guru.io"):
        out = load_shop_data(tiny_shop)

    assert out["stats"] == raw_stats
    assert any(
        "raw_data" in record.message and "tiny" in record.message
        for record in caplog.records
    ), "expected a warning naming the fallback path"


def test_load_shop_data_missing_stats_with_no_fallback(
    tmp_path: Path,
    tiny_shop: Shop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither location has stats.json, fall back to the empty default."""
    root = tmp_path / "shop_arena_root"
    data_dir = root / "outputs" / "shops" / "tiny.example" / "data"
    data_dir.mkdir(parents=True)
    for fname in ("store.json", "navigation.json"):
        (data_dir / fname).write_text("{}")
    for fname in ("products.json", "collections.json", "pages.json", "policies.json"):
        (data_dir / fname).write_text("[]")

    from shop_guru import _paths
    monkeypatch.setattr(_paths, "_REPO_ROOT", root)

    out = load_shop_data(tiny_shop)
    assert out["stats"] == {}
