"""Unit tests for shop_guru.config."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shop_guru.config import load_shops


def _write_yaml(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc))


def test_load_shops_basic(tmp_path: Path) -> None:
    path = tmp_path / "shops.yml"
    _write_yaml(
        path,
        {
            "shops": [
                {
                    "slug": "a",
                    "name": "Alpha",
                    "shop_url": "https://a.example/",
                    "data_dir": "outputs/shops/a",
                    "country": "US",
                    "currency": "USD",
                    "language": "en",
                    "image_tag": "a-main",
                }
            ]
        },
    )
    shops = load_shops(path)
    assert len(shops) == 1
    s = shops[0]
    assert s.slug == "a"
    assert s.shop_url == "https://a.example"  # trailing slash stripped


def test_load_shops_rejects_legacy_keys(tmp_path: Path) -> None:
    path = tmp_path / "shops.yml"
    _write_yaml(
        path,
        {
            "shops": [
                {
                    "slug": "a",
                    "name": "Alpha",
                    "real_url": "https://a.example",
                    "sandbox_url": "https://sandbox-a.example",
                    "data_dir": "outputs/shops/a",
                    "country": "US",
                    "currency": "USD",
                    "language": "en",
                    "image_tag": "a-main",
                }
            ]
        },
    )
    with pytest.raises(ValueError, match="legacy keys"):
        load_shops(path)


def test_load_shops_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_shops(tmp_path / "does-not-exist.yml")


def test_load_shops_missing_section(tmp_path: Path) -> None:
    path = tmp_path / "shops.yml"
    path.write_text("other_key: []\n")
    with pytest.raises(ValueError, match="missing top-level"):
        load_shops(path)
