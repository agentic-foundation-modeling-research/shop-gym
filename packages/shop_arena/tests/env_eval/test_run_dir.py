"""Tests for ``shop_arena.env_eval.pipeline.resolve_run_dir`` (M1 task).

Covers the impl-plan M1 path-builder bullet:

* default ``outputs/shop_env_evals/<shop_name>/<run_id>/`` layout,
* hostname-derived ``<shop_name>`` (lowercased, no port),
* timestamped UTC ``<run_id>``,
* ``--shop-name`` / ``EvalConfig.shop_name`` override,
* resumable existing ``--out`` (returned verbatim).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shop_arena.env_eval.config import EvalConfig
from shop_arena.env_eval.pipeline import (
    DEFAULT_OUTPUT_ROOT,
    RUN_ID_TIMESTAMP_FORMAT,
    resolve_run_dir,
)

# Frozen clock used across tests so the run_id segment is byte-stable.
_FIXED_NOW = datetime(2026, 5, 3, 12, 34, 56, tzinfo=UTC)
_FIXED_RUN_ID = "20260503T123456Z"


def test_run_id_format_is_filesystem_safe() -> None:
    """``<run_id>`` is UTC, second-precision, no colons (Windows-safe)."""
    rendered = _FIXED_NOW.strftime(RUN_ID_TIMESTAMP_FORMAT)
    assert rendered == _FIXED_RUN_ID
    assert ":" not in rendered


def test_default_path_uses_hostname_and_timestamp(tmp_path: Path) -> None:
    """No overrides → ``<base>/<hostname>/<timestamp>/``."""
    cfg = EvalConfig(url="https://example-shop.com/")

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path)

    assert run_dir == tmp_path / "example-shop.com" / _FIXED_RUN_ID


def test_default_base_dir_is_outputs_shop_env_evals() -> None:
    """When ``base_dir`` is not provided, ``DEFAULT_OUTPUT_ROOT`` is used."""
    cfg = EvalConfig(url="https://example-shop.com/")

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW)

    assert run_dir == DEFAULT_OUTPUT_ROOT / "example-shop.com" / _FIXED_RUN_ID
    assert Path("outputs/shop_env_evals") == DEFAULT_OUTPUT_ROOT


def test_hostname_is_lowercased_and_strips_port(tmp_path: Path) -> None:
    """Hosts are lowercased and the URL port is dropped from ``<shop_name>``."""
    cfg = EvalConfig(url="https://Example-Shop.COM:8443/path?q=x#frag")

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path)

    assert run_dir == tmp_path / "example-shop.com" / _FIXED_RUN_ID


def test_shop_name_override_wins(tmp_path: Path) -> None:
    """``EvalConfig.shop_name`` overrides the hostname-derived segment."""
    cfg = EvalConfig(
        url="https://example-shop.com/",
        shop_name="canonical-shop",
    )

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path)

    assert run_dir == tmp_path / "canonical-shop" / _FIXED_RUN_ID


def test_existing_out_dir_returned_verbatim(tmp_path: Path) -> None:
    """``EvalConfig.out_dir`` is the resume signal — return it as-is."""
    pre_existing = tmp_path / "existing-run"
    pre_existing.mkdir()
    cfg = EvalConfig(url="https://example-shop.com/", out_dir=pre_existing)

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path / "ignored")

    assert run_dir == pre_existing


def test_out_dir_returned_even_when_missing(tmp_path: Path) -> None:
    """A non-existent ``out_dir`` is still returned verbatim.

    The pipeline (not the resolver) is responsible for creating the
    directory on first artifact write; the resolver is pure.
    """
    fresh = tmp_path / "fresh-run"
    cfg = EvalConfig(url="https://example-shop.com/", out_dir=fresh)

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path / "ignored")

    assert run_dir == fresh
    assert not fresh.exists()


def test_now_defaults_to_current_utc(tmp_path: Path) -> None:
    """Omitting ``now`` falls back to ``datetime.now(UTC)`` (smoke check)."""
    cfg = EvalConfig(url="https://example-shop.com/")

    before = datetime.now(UTC)
    run_dir = resolve_run_dir(cfg, base_dir=tmp_path)
    after = datetime.now(UTC)

    rendered = run_dir.name
    parsed = datetime.strptime(rendered, RUN_ID_TIMESTAMP_FORMAT).replace(
        tzinfo=UTC,
    )
    # ``before``/``after`` keep sub-second precision; truncate to match.
    before_trunc = before.replace(microsecond=0)
    after_trunc = after.replace(microsecond=0)
    assert before_trunc <= parsed <= after_trunc


def test_url_without_hostname_raises(tmp_path: Path) -> None:
    """A URL with no hostname surfaces a clear ``ValueError`` (no fallback)."""
    cfg = EvalConfig(url="example-shop.com")  # no scheme → no hostname

    with pytest.raises(ValueError, match="cannot derive <shop_name>"):
        resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path)


def test_url_without_hostname_but_shop_name_override_ok(tmp_path: Path) -> None:
    """The override saves the day when hostname derivation fails."""
    cfg = EvalConfig(url="example-shop.com", shop_name="manual-name")

    run_dir = resolve_run_dir(cfg, now=_FIXED_NOW, base_dir=tmp_path)

    assert run_dir == tmp_path / "manual-name" / _FIXED_RUN_ID
