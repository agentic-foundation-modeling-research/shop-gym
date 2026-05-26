"""Integration tests for shop_guru.pipeline.build_all."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shop_guru.pipeline import build_all, per_shop_out_dir


def _write_config(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "shops": [
                    {
                        "slug": "tiny",
                        "name": "Tiny Shop",
                        "shop_url": "https://tiny.example",
                        "data_dir": "outputs/shops/tiny.example",
                        "country": "US",
                        "currency": "USD",
                        "language": "en",
                        "image_tag": "tiny-main",
                    }
                ]
            }
        )
    )


def test_per_shop_default(tmp_path: Path, tiny_shop_arena_root: Path) -> None:
    """Default: tasks land in <repo>/outputs/shop_guru/<slug>/benchmarks/."""
    config = tmp_path / "shops.yml"
    _write_config(config)

    build_all(
        config=config,
        skip_manual=True,
        logger=lambda _msg: None,
    )

    # Shop was defined with data_dir=outputs/shops/tiny.example
    per_shop_dir = tiny_shop_arena_root / "outputs/shop_guru/tiny/benchmarks"
    assert per_shop_dir.exists()
    emitted = sorted(p.name for p in per_shop_dir.glob("*.json"))
    assert emitted, "expected at least one .json file"
    # No paired _real / _sandbox split — every file is a single .json.
    assert not any("_real.json" in name or "_sandbox.json" in name for name in emitted)

    for json_path in per_shop_dir.glob("*.json"):
        tasks = json.loads(json_path.read_text())
        assert tasks
        for t in tasks:
            assert t["id"].startswith("tiny-")
            assert t["url"] == "https://tiny.example"


def test_flat_mirror_additionally(tmp_path: Path, tiny_shop_arena_root: Path) -> None:
    """--flat-out writes in addition to per-shop."""
    config = tmp_path / "shops.yml"
    _write_config(config)
    flat = tmp_path / "mirror"

    build_all(
        config=config,
        flat_out=flat,
        skip_manual=True,
        logger=lambda _msg: None,
    )

    per_shop_dir = tiny_shop_arena_root / "outputs/shop_guru/tiny/benchmarks"
    assert any(per_shop_dir.glob("*.json"))
    assert any(flat.glob("*.json"))


def test_no_per_shop_requires_flat_out(tmp_path: Path, tiny_shop_arena_root: Path) -> None:
    config = tmp_path / "shops.yml"
    _write_config(config)

    with pytest.raises(ValueError, match="requires flat_out"):
        build_all(
            config=config,
            skip_per_shop=True,
            logger=lambda _msg: None,
        )


def test_flat_only(tmp_path: Path, tiny_shop_arena_root: Path) -> None:
    """--no-per-shop + --flat-out writes only the flat mirror."""
    config = tmp_path / "shops.yml"
    _write_config(config)
    flat = tmp_path / "mirror"

    build_all(
        config=config,
        flat_out=flat,
        skip_per_shop=True,
        skip_manual=True,
        logger=lambda _msg: None,
    )

    assert any(flat.glob("*.json"))
    per_shop_dir = tiny_shop_arena_root / "outputs/shop_guru/tiny/benchmarks"
    # Per-shop dir may not exist or may be empty from this run.
    if per_shop_dir.exists():
        assert not any(per_shop_dir.glob("*.json"))


def test_shop_filter_unmatched(tmp_path: Path, tiny_shop_arena_root: Path) -> None:
    config = tmp_path / "shops.yml"
    _write_config(config)

    with pytest.raises(SystemExit):
        build_all(
            config=config,
            shop_filter="nonexistent",
            logger=lambda _msg: None,
        )


def test_per_shop_out_dir_helper(tiny_shop, tiny_shop_arena_root: Path) -> None:
    assert (
        per_shop_out_dir(tiny_shop)
        == tiny_shop_arena_root / "outputs/shop_guru/tiny/benchmarks"
    )


def test_build_all_runs_validator_by_default(
    tmp_path: Path, tiny_shop_arena_root: Path
) -> None:
    """build_all() should validate emitted benchmarks and surface no errors
    on a clean fixture run."""
    config = tmp_path / "shops.yml"
    _write_config(config)

    issues = build_all(
        config=config,
        skip_manual=True,
        logger=lambda _msg: None,
    )

    # The fixture is internally consistent, so we expect no errors. Warnings
    # about /policies/* fallbacks (which look like /pages/* references) are
    # acceptable since policies.json is empty in the fixture.
    errors = [i for i in issues if i.severity == "error"]
    assert errors == [], f"unexpected validation errors: {errors}"


def test_build_all_validate_false_returns_empty(
    tmp_path: Path, tiny_shop_arena_root: Path
) -> None:
    config = tmp_path / "shops.yml"
    _write_config(config)
    issues = build_all(
        config=config,
        skip_manual=True,
        validate=False,
        logger=lambda _msg: None,
    )
    assert issues == []


def test_build_all_validator_flags_corrupted_benchmarks(
    tmp_path: Path, tiny_shop_arena_root: Path
) -> None:
    """If a stale/corrupt benchmark file references unknown handles, the
    validator must surface an error after the build completes.
    """
    config = tmp_path / "shops.yml"
    _write_config(config)

    bench_dir = tiny_shop_arena_root / "outputs/shop_guru/tiny/benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    # Pre-seed a manually-edited benchmark file that references a product
    # that doesn't exist. The build will overwrite the *generator* outputs
    # but a hand-authored file with a different stem survives untouched.
    bad_path = bench_dir / "ShopGuru_e2e_handauthored.json"
    bad_path.write_text(
        json.dumps(
            [
                {
                    "id": "tiny-e2e-99",
                    "type": "shopping",
                    "intent": "Find the unicorn product.",
                    "success_criteria": {
                        "url_contains": "/products/unicorn",
                        "type": "product_search",
                    },
                    "url": "https://tiny.example",
                }
            ]
        )
    )

    issues = build_all(
        config=config,
        skip_manual=True,
        logger=lambda _msg: None,
    )
    bad_issues = [i for i in issues if "tiny-e2e-99" in i.task_id]
    assert any(i.rule == "unknown-product" and i.severity == "error" for i in bad_issues)
