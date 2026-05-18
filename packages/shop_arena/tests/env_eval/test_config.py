"""Tests for ``shop_arena.env_eval.config`` (first M1 task).

Pins the spec §4.1 defaults, the closed/frozen contract, and the
field-level guards that catch obvious caller mistakes (empty URL,
negative ``max_hops``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shop_arena.env_eval.config import (
    DEFAULT_MAX_HOPS,
    DEFAULT_PAGES_CLASSIFIER_MODEL,
    DEFAULT_RUBRIC_MODEL,
    DEFAULT_VIEWPORT,
    EvalConfig,
    EvalResult,
)


def test_eval_config_defaults_match_spec() -> None:
    """Every default in ``EvalConfig`` matches spec §4.1 / impl-plan M0."""
    cfg = EvalConfig(url="https://example-shop.com")

    assert cfg.url == "https://example-shop.com"
    assert cfg.out_dir is None
    assert cfg.viewport == DEFAULT_VIEWPORT == (1440, 900)
    assert cfg.max_hops == DEFAULT_MAX_HOPS == 3
    assert cfg.rubric_model == DEFAULT_RUBRIC_MODEL == "claude-sonnet-4-6"
    assert cfg.pages_classifier_model == DEFAULT_PAGES_CLASSIFIER_MODEL
    assert cfg.rediscover is False
    assert cfg.shop_name is None
    assert cfg.no_rubric is False


def test_eval_config_is_frozen() -> None:
    """Mutating an ``EvalConfig`` field raises (model is frozen)."""
    cfg = EvalConfig(url="https://example-shop.com")
    with pytest.raises(ValidationError):
        cfg.max_hops = 5  # type: ignore[misc]


def test_eval_config_rejects_unknown_fields() -> None:
    """Unknown kwargs raise — closed schema (``extra='forbid'``)."""
    with pytest.raises(ValidationError):
        EvalConfig.model_validate(
            {"url": "https://example-shop.com", "unknown_flag": True},
        )


def test_eval_config_rejects_empty_url() -> None:
    """An empty ``url`` is a caller bug; surface it loudly."""
    with pytest.raises(ValidationError):
        EvalConfig(url="")


def test_eval_config_rejects_negative_max_hops() -> None:
    """``max_hops`` must be non-negative (BFS depth, spec §5.5)."""
    with pytest.raises(ValidationError):
        EvalConfig(url="https://example-shop.com", max_hops=-1)


def test_eval_config_accepts_overrides() -> None:
    """All documented overrides round-trip without surprises."""
    out = Path("/tmp/run-42")
    cfg = EvalConfig(
        url="https://example-shop.com",
        out_dir=out,
        viewport=(1280, 720),
        max_hops=1,
        rubric_model="gpt-4o",
        pages_classifier_model="gpt-5-nano",
        rediscover=True,
        shop_name="example",
        no_rubric=True,
    )

    assert cfg.out_dir == out
    assert cfg.viewport == (1280, 720)
    assert cfg.max_hops == 1
    assert cfg.rubric_model == "gpt-4o"
    assert cfg.pages_classifier_model == "gpt-5-nano"
    assert cfg.rediscover is True
    assert cfg.shop_name == "example"
    assert cfg.no_rubric is True


def test_eval_config_rejects_empty_pages_classifier_model() -> None:
    """``pages_classifier_model`` must be non-empty (provider routes by prefix)."""
    with pytest.raises(ValidationError):
        EvalConfig(url="https://example-shop.com", pages_classifier_model="")


def test_eval_result_holds_paths() -> None:
    """``EvalResult`` exposes ``run_dir`` and ``metrics_path``."""
    run_dir = Path("/tmp/runs/example/2026-05-03T00-00-00")
    metrics_path = run_dir / "metrics.json"

    result = EvalResult(run_dir=run_dir, metrics_path=metrics_path)

    assert result.run_dir == run_dir
    assert result.metrics_path == metrics_path


def test_eval_result_is_frozen_and_closed() -> None:
    """``EvalResult`` mirrors ``EvalConfig``: frozen + ``extra='forbid'``."""
    result = EvalResult(
        run_dir=Path("/tmp/r"),
        metrics_path=Path("/tmp/r/metrics.json"),
    )
    with pytest.raises(ValidationError):
        result.run_dir = Path("/tmp/other")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EvalResult.model_validate(
            {
                "run_dir": Path("/tmp/r"),
                "metrics_path": Path("/tmp/r/metrics.json"),
                "extra_field": "nope",
            },
        )
