"""Tests for `shop_probe.scale.catalog`.

Covers the two on-disk JSON shapes the loader auto-detects:

* list at root (sandbox-shop dumps)
* ``{"<key>": [...]}`` wrapper (real-shop prefetch)

Plus the no-file and malformed-file fallbacks (silently ``None``).
"""

from __future__ import annotations

import json
from pathlib import Path

from shop_probe.scale.catalog import read_catalog_counts


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_read_catalog_counts_list_at_root(tmp_path: Path) -> None:
    _write(tmp_path / "products.json", [{"id": 1}, {"id": 2}, {"id": 3}])
    _write(tmp_path / "collections.json", [{"id": "c1"}])
    products, collections = read_catalog_counts(tmp_path)
    assert products == 3  # noqa: PLR2004
    assert collections == 1


def test_read_catalog_counts_wrapped_list(tmp_path: Path) -> None:
    _write(tmp_path / "products.json", {"products": [{"id": 1}, {"id": 2}]})
    _write(tmp_path / "collections.json", {"collections": [{"id": "c1"}, {"id": "c2"}]})
    products, collections = read_catalog_counts(tmp_path)
    assert products == 2  # noqa: PLR2004
    assert collections == 2  # noqa: PLR2004


def test_read_catalog_counts_missing_files_yield_none(tmp_path: Path) -> None:
    products, collections = read_catalog_counts(tmp_path)
    assert products is None
    assert collections is None


def test_read_catalog_counts_partial_files(tmp_path: Path) -> None:
    """Missing one file must not affect the other."""
    _write(tmp_path / "products.json", [{"id": 1}])
    products, collections = read_catalog_counts(tmp_path)
    assert products == 1
    assert collections is None


def test_read_catalog_counts_unknown_shape_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / "products.json", {"unexpected_key": [1, 2, 3]})
    products, _ = read_catalog_counts(tmp_path)
    assert products is None


def test_read_catalog_counts_malformed_json_returns_none(tmp_path: Path) -> None:
    (tmp_path / "products.json").write_text("not-json{", encoding="utf-8")
    products, _ = read_catalog_counts(tmp_path)
    assert products is None


def test_read_catalog_counts_empty_list(tmp_path: Path) -> None:
    """An empty list still counts — yields zero, not None."""
    _write(tmp_path / "products.json", [])
    _write(tmp_path / "collections.json", {"collections": []})
    products, collections = read_catalog_counts(tmp_path)
    assert products == 0
    assert collections == 0
