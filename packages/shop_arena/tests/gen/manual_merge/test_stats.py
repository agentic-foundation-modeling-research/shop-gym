"""Unit tests for :mod:`shop_arena.gen.manual_merge.stats`.

Covers the T2.3 requirements from
``docs/impl/shop_gen_implementation.md``:

* Deterministic recomputation from merged capabilities + per-seed
  ``stats.json`` summaries — no LLM, no network.
* Aggregation rules: median for the typical-scale priors, min/max/median
  for prices (skipping all-zero seeds), mean for ``products_with_variants_pct``,
  union for ``variant_axes_observed``.
* Capability-derived leaves (``navigation_depth_max``,
  ``homepage_section_count``, ``info_pages_count``, ``feature_count``)
  re-derive from the merged capabilities, not from the seeds.
* End-to-end :class:`ComputeMergeStatsStep` writes ``manual/stats.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shop_arena.explore.capabilities import Capabilities
from shop_arena.explore.stats import Stats
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.manual_merge.stats import (
    ComputeMergeStatsStep,
    StatsValidationError,
    merge_stats_seeds,
)
from shop_arena.gen.steps.base import FileInput, Step, StepContext, StepInput

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _write_seed_stats(seed_dir: Path, payload: dict[str, object]) -> Path:
    """Write a ``stats.json`` under the canonical seed layout."""
    artifact = seed_dir / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    path = artifact / "stats.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stats_payload(**overrides: object) -> dict[str, object]:
    """Return a minimal valid stats payload merged with ``overrides``."""
    base: dict[str, object] = {
        "products_total": 100,
        "collections_total": 5,
        "products_per_collection": {"avg": 20.0, "median": 18.0, "max": 30},
        "price": {"min": 10.0, "max": 100.0, "median": 40.0, "currency": "USD"},
        "products_with_variants_pct": 0.5,
        "variant_axes_observed": ["size", "color"],
        "navigation_depth_max": 2,
        "homepage_section_count": 6,
        "info_pages_count": 3,
        "feature_count": 12,
    }
    for key, value in overrides.items():
        base[key] = value
    return base


def _capabilities(**overrides: object) -> Capabilities:
    """Return a Capabilities document populated for stats-merge tests."""
    payload: dict[str, object] = {
        "version": "0.1",
        "shop": {"descriptor": "minimalist storefront", "currency": "USD"},
        "site_shell": {"nav_depth": 3, "has_announcement_bar": True},
        "homepage": {"section_count": 7, "section_types": ["hero", "grid"]},
        "collection": {"filters": ["price"], "sort": ["best-selling"]},
        "product": {"variant_selectors": ["size"], "has_reviews": True},
        "info_pages_present": ["about", "contact"],
    }
    for key, value in overrides.items():
        payload[key] = value
    return Capabilities.model_validate(payload)


# --------------------------------------------------------------------------- #
# Aggregation rules
# --------------------------------------------------------------------------- #


def test_products_total_is_median_across_seeds(tmp_path: Path) -> None:
    """``products_total`` aggregates as median (rounded), not sum."""
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(products_total=80)),
        _write_seed_stats(tmp_path / "b", _stats_payload(products_total=200)),
        _write_seed_stats(tmp_path / "c", _stats_payload(products_total=150)),
    ]
    merged = merge_stats_seeds(seeds, capabilities=_capabilities())
    assert merged.products_total == 150


def test_collections_total_is_median_across_seeds(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(collections_total=4)),
        _write_seed_stats(tmp_path / "b", _stats_payload(collections_total=10)),
    ]
    # median([4, 10]) = 7.0 → round → 7
    merged = merge_stats_seeds(seeds, capabilities=_capabilities())
    assert merged.collections_total == 7


def test_products_per_collection_aggregates_avg_median_max(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(
            tmp_path / "a",
            _stats_payload(
                products_per_collection={"avg": 10.0, "median": 8.0, "max": 20},
            ),
        ),
        _write_seed_stats(
            tmp_path / "b",
            _stats_payload(
                products_per_collection={"avg": 30.0, "median": 28.0, "max": 50},
            ),
        ),
    ]
    merged = merge_stats_seeds(seeds, capabilities=_capabilities())
    assert merged.products_per_collection.avg == 20.0
    assert merged.products_per_collection.median == 18.0
    assert merged.products_per_collection.max == 50


def test_price_aggregates_min_max_median(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(
            tmp_path / "a",
            _stats_payload(
                price={"min": 5.0, "max": 100.0, "median": 40.0, "currency": "USD"},
            ),
        ),
        _write_seed_stats(
            tmp_path / "b",
            _stats_payload(
                price={"min": 20.0, "max": 250.0, "median": 60.0, "currency": "USD"},
            ),
        ),
    ]
    merged = merge_stats_seeds(seeds, capabilities=_capabilities())
    assert merged.price.min == 5.0
    assert merged.price.max == 250.0
    assert merged.price.median == 50.0
    assert merged.price.currency == "USD"


def test_price_skips_seeds_with_no_price_signal(tmp_path: Path) -> None:
    """Default-empty PriceStats (max=0) must not collapse merged ``min`` to 0."""
    seeds = [
        _write_seed_stats(
            tmp_path / "a",
            _stats_payload(
                price={"min": 0.0, "max": 0.0, "median": 0.0, "currency": ""},
            ),
        ),
        _write_seed_stats(
            tmp_path / "b",
            _stats_payload(
                price={"min": 9.99, "max": 49.99, "median": 19.99, "currency": "EUR"},
            ),
        ),
    ]
    merged = merge_stats_seeds(seeds, capabilities=_capabilities(shop={"currency": ""}))
    assert merged.price.min == 9.99
    assert merged.price.max == 49.99
    assert merged.price.median == 19.99


def test_price_currency_prefers_capabilities(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(
            tmp_path / "a",
            _stats_payload(
                price={"min": 5.0, "max": 50.0, "median": 20.0, "currency": "USD"},
            ),
        ),
        _write_seed_stats(
            tmp_path / "b",
            _stats_payload(
                price={"min": 5.0, "max": 50.0, "median": 20.0, "currency": "USD"},
            ),
        ),
    ]
    caps = _capabilities(shop={"descriptor": "x", "currency": "EUR"})
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.price.currency == "EUR"


def test_price_currency_falls_back_to_first_seed_when_caps_empty(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(
            tmp_path / "a",
            _stats_payload(
                price={"min": 0.0, "max": 0.0, "median": 0.0, "currency": ""},
            ),
        ),
        _write_seed_stats(
            tmp_path / "b",
            _stats_payload(
                price={"min": 5.0, "max": 50.0, "median": 20.0, "currency": "GBP"},
            ),
        ),
    ]
    caps = _capabilities(shop={"descriptor": "x", "currency": ""})
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.price.currency == "GBP"


def test_products_with_variants_pct_is_mean_across_seeds(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(products_with_variants_pct=0.0)),
        _write_seed_stats(tmp_path / "b", _stats_payload(products_with_variants_pct=0.5)),
        _write_seed_stats(tmp_path / "c", _stats_payload(products_with_variants_pct=1.0)),
    ]
    merged = merge_stats_seeds(seeds, capabilities=_capabilities())
    assert merged.products_with_variants_pct == pytest.approx(0.5)


def test_variant_axes_observed_is_union_preserving_first_seen_order(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(
            tmp_path / "a",
            _stats_payload(variant_axes_observed=["size", "color"]),
        ),
        _write_seed_stats(
            tmp_path / "b",
            _stats_payload(variant_axes_observed=["color", "material", "size"]),
        ),
    ]
    merged = merge_stats_seeds(seeds, capabilities=_capabilities())
    assert merged.variant_axes_observed == ["size", "color", "material"]


# --------------------------------------------------------------------------- #
# Capability-derived leaves (merged caps as ground truth, spec §5.2)
# --------------------------------------------------------------------------- #


def test_navigation_depth_max_comes_from_capabilities(tmp_path: Path) -> None:
    """The seeds' ``navigation_depth_max`` is ignored — merged caps wins."""
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(navigation_depth_max=99)),
    ]
    caps = _capabilities(site_shell={"nav_depth": 4})
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.navigation_depth_max == 4


def test_homepage_section_count_comes_from_capabilities(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(homepage_section_count=99)),
    ]
    caps = _capabilities(homepage={"section_count": 5, "section_types": ["hero"]})
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.homepage_section_count == 5


def test_info_pages_count_comes_from_capabilities(tmp_path: Path) -> None:
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(info_pages_count=99)),
    ]
    caps = _capabilities(info_pages_present=["about", "contact", "shipping", "faq"])
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.info_pages_count == 4


def test_feature_count_recomputes_from_capabilities(tmp_path: Path) -> None:
    """``feature_count`` must use the merged-caps recipe, not seed values."""
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload(feature_count=999)),
    ]
    # Build a sparse capabilities so we can count features by hand:
    # one truthy bool + one list of length 2 = 3.
    caps = Capabilities.model_validate(
        {
            "version": "0.1",
            "site_shell": {"has_mega_menu": True},
            "info_pages_present": ["about", "contact"],
        },
    )
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.feature_count == 3


def test_capability_leaves_default_to_zero_when_unset(tmp_path: Path) -> None:
    """A capabilities doc without nav/homepage/info defaults the merged leaves to 0."""
    seeds = [
        _write_seed_stats(tmp_path / "a", _stats_payload()),
    ]
    caps = Capabilities.model_validate({"version": "0.1"})
    merged = merge_stats_seeds(seeds, capabilities=caps)
    assert merged.navigation_depth_max == 0
    assert merged.homepage_section_count == 0
    assert merged.info_pages_count == 0


# --------------------------------------------------------------------------- #
# Schema enforcement
# --------------------------------------------------------------------------- #


def test_seed_with_unknown_field_rejected(tmp_path: Path) -> None:
    payload = _stats_payload()
    payload["unknown_extra"] = "boom"
    seed = _write_seed_stats(tmp_path / "a", payload)
    with pytest.raises(StatsValidationError):
        merge_stats_seeds([seed], capabilities=_capabilities())


def test_seed_malformed_json_rejected(tmp_path: Path) -> None:
    seed_dir = tmp_path / "a" / "artifact"
    seed_dir.mkdir(parents=True)
    seed_path = seed_dir / "stats.json"
    seed_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(StatsValidationError, match="not valid JSON"):
        merge_stats_seeds([seed_path], capabilities=_capabilities())


def test_seed_non_object_rejected(tmp_path: Path) -> None:
    seed_dir = tmp_path / "a" / "artifact"
    seed_dir.mkdir(parents=True)
    seed_path = seed_dir / "stats.json"
    seed_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(StatsValidationError, match="JSON object"):
        merge_stats_seeds([seed_path], capabilities=_capabilities())


def test_missing_seed_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge_stats_seeds([tmp_path / "missing.json"], capabilities=_capabilities())


def test_empty_seed_paths_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        merge_stats_seeds([], capabilities=_capabilities())


def test_merged_document_validates_against_closed_schema(tmp_path: Path) -> None:
    seed = _write_seed_stats(tmp_path / "a", _stats_payload())
    merged = merge_stats_seeds([seed], capabilities=_capabilities())
    Stats.model_validate(merged.model_dump(mode="json"))


# --------------------------------------------------------------------------- #
# Single-seed shortcut
# --------------------------------------------------------------------------- #


def test_single_seed_passthrough(tmp_path: Path) -> None:
    """A 1-seed merge preserves seed-aggregated fields verbatim."""
    seed = _write_seed_stats(
        tmp_path / "a",
        _stats_payload(
            products_total=42,
            collections_total=3,
            products_per_collection={"avg": 14.0, "median": 12.0, "max": 25},
            price={"min": 1.99, "max": 99.99, "median": 19.99, "currency": "USD"},
            products_with_variants_pct=0.4,
            variant_axes_observed=["size", "color"],
        ),
    )
    merged = merge_stats_seeds([seed], capabilities=_capabilities())
    assert merged.products_total == 42
    assert merged.collections_total == 3
    assert merged.products_per_collection.avg == 14.0
    assert merged.price.min == 1.99
    assert merged.products_with_variants_pct == pytest.approx(0.4)
    assert merged.variant_axes_observed == ["size", "color"]


# --------------------------------------------------------------------------- #
# ComputeMergeStatsStep — Step contract
# --------------------------------------------------------------------------- #


def test_step_satisfies_step_protocol(tmp_path: Path) -> None:
    step = ComputeMergeStatsStep(seed_stats_paths=[tmp_path / "x.json"])
    assert isinstance(step, Step)
    assert step.id == "compute_merge_stats"
    assert step.phase == "manual_merge"
    assert step.depends_on == ["merge_capabilities"]
    assert step.outputs == [Path("manual") / "stats.json"]
    file_inputs = [ref for ref in step.inputs if isinstance(ref, FileInput)]
    step_inputs = [ref for ref in step.inputs if isinstance(ref, StepInput)]
    assert [ref.path for ref in file_inputs] == [tmp_path / "x.json"]
    assert [ref.step_id for ref in step_inputs] == ["merge_capabilities"]


def test_step_run_writes_stats_json(tmp_path: Path) -> None:
    """End-to-end: step reads merged caps from disk and writes ``manual/stats.json``."""
    seed_a_dir = tmp_path / "seed_a"
    seed_b_dir = tmp_path / "seed_b"
    seed_a = _write_seed_stats(
        seed_a_dir,
        _stats_payload(
            products_total=80,
            price={"min": 5.0, "max": 100.0, "median": 40.0, "currency": "USD"},
        ),
    )
    seed_b = _write_seed_stats(
        seed_b_dir,
        _stats_payload(
            products_total=180,
            price={"min": 12.0, "max": 200.0, "median": 60.0, "currency": "USD"},
        ),
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # The runtime contract: ``merge_capabilities`` writes the merged
    # capabilities before this step runs. Pre-populate it for isolation.
    caps = _capabilities()
    caps_path = out_dir / "manual" / "capabilities.json"
    caps_path.parent.mkdir(parents=True, exist_ok=True)
    caps_path.write_text(
        json.dumps(caps.model_dump(mode="json")),
        encoding="utf-8",
    )

    cfg = ShopGenConfig(seeds=[seed_a_dir, seed_b_dir], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    step = ComputeMergeStatsStep(seed_stats_paths=[seed_a, seed_b])
    step.run(ctx)

    stats_path = out_dir / "manual" / "stats.json"
    assert stats_path.is_file()

    merged = Stats.model_validate_json(stats_path.read_text(encoding="utf-8"))
    # median(80, 180) = 130 → round → 130
    assert merged.products_total == 130
    # min-of-mins / max-of-maxes / median-of-medians.
    assert merged.price.min == 5.0
    assert merged.price.max == 200.0
    assert merged.price.median == 50.0
    # Capability-derived leaves come from the pre-populated caps.
    assert merged.navigation_depth_max == 3
    assert merged.homepage_section_count == 7
    assert merged.info_pages_count == 2


def test_step_run_requires_upstream_capabilities(tmp_path: Path) -> None:
    """Step refuses to run when ``merge_capabilities`` hasn't written its output."""
    seed_a = _write_seed_stats(tmp_path / "a", _stats_payload())
    seed_b = _write_seed_stats(tmp_path / "b", _stats_payload())

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = ShopGenConfig(seeds=[tmp_path / "a", tmp_path / "b"], out_dir=out_dir)
    ctx = StepContext(config=cfg, out_dir=out_dir)

    step = ComputeMergeStatsStep(seed_stats_paths=[seed_a, seed_b])
    with pytest.raises(FileNotFoundError, match="merge_capabilities first"):
        step.run(ctx)


def test_step_run_is_deterministic_across_invocations(tmp_path: Path) -> None:
    """Two runs with the same seeds produce byte-identical outputs."""
    seed_a_dir = tmp_path / "seed_a"
    seed_b_dir = tmp_path / "seed_b"
    seed_a = _write_seed_stats(seed_a_dir, _stats_payload(products_total=120))
    seed_b = _write_seed_stats(seed_b_dir, _stats_payload(products_total=180))

    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    out_a.mkdir()
    out_b.mkdir()
    caps_payload = json.dumps(_capabilities().model_dump(mode="json"))
    for out in (out_a, out_b):
        caps_path = out / "manual" / "capabilities.json"
        caps_path.parent.mkdir(parents=True, exist_ok=True)
        caps_path.write_text(caps_payload, encoding="utf-8")

    cfg = ShopGenConfig(seeds=[seed_a_dir, seed_b_dir], out_dir=out_a)
    ctx_a = StepContext(config=cfg, out_dir=out_a)
    ctx_b = StepContext(config=cfg, out_dir=out_b)

    ComputeMergeStatsStep(seed_stats_paths=[seed_a, seed_b]).run(ctx_a)
    ComputeMergeStatsStep(seed_stats_paths=[seed_a, seed_b]).run(ctx_b)

    assert (out_a / "manual" / "stats.json").read_bytes() == (
        out_b / "manual" / "stats.json"
    ).read_bytes()


# --------------------------------------------------------------------------- #
# Fixture-backed end-to-end (T2.3 "unit test against fixture seeds")
# --------------------------------------------------------------------------- #


def test_fixture_seeds_produce_stable_priors(tmp_path: Path) -> None:
    """Two heterogeneous fixture seeds produce the documented priors.

    Anchors the aggregation rules end-to-end against a small but
    realistic fixture pair so a regression in any single rule is
    visible in one assertion block.
    """
    seed_a = _write_seed_stats(
        tmp_path / "a",
        {
            "products_total": 220,
            "collections_total": 12,
            "products_per_collection": {"avg": 18.5, "median": 16.0, "max": 45},
            "price": {
                "min": 4.99,
                "max": 129.99,
                "median": 24.99,
                "currency": "EUR",
            },
            "products_with_variants_pct": 0.32,
            "variant_axes_observed": ["flavor", "size"],
            "navigation_depth_max": 2,
            "homepage_section_count": 9,
            "info_pages_count": 5,
            "feature_count": 38,
        },
    )
    seed_b = _write_seed_stats(
        tmp_path / "b",
        {
            "products_total": 164,
            "collections_total": 50,
            "products_per_collection": {"avg": 15.42, "median": 8.0, "max": 179},
            "price": {
                "min": 0.98,
                "max": 5499.0,
                "median": 59.99,
                "currency": "USD",
            },
            "products_with_variants_pct": 0.07,
            "variant_axes_observed": ["title", "size"],
            "navigation_depth_max": 2,
            "homepage_section_count": 16,
            "info_pages_count": 7,
            "feature_count": 48,
        },
    )

    caps = _capabilities(
        shop={"descriptor": "premium goods", "currency": "USD"},
        site_shell={"nav_depth": 3, "has_mega_menu": True},
        homepage={"section_count": 12, "section_types": ["hero", "grid"]},
        info_pages_present=["about", "contact", "shipping", "faq", "policy"],
    )
    merged = merge_stats_seeds([seed_a, seed_b], capabilities=caps)

    # Median of (220, 164) = 192 → round → 192.
    assert merged.products_total == 192
    # Median of (12, 50) = 31.
    assert merged.collections_total == 31
    # Per-collection: avg = mean(18.5, 15.42); median = median of medians;
    # max = max of maxes.
    assert merged.products_per_collection.avg == pytest.approx(16.96)
    assert merged.products_per_collection.median == 12.0
    assert merged.products_per_collection.max == 179
    # Price: min-of-mins / max-of-maxes / median-of-medians.
    assert merged.price.min == 0.98
    assert merged.price.max == 5499.0
    assert merged.price.median == pytest.approx(42.49)
    # Currency wins from capabilities, not from either seed individually.
    assert merged.price.currency == "USD"
    # Mean of (0.32, 0.07).
    assert merged.products_with_variants_pct == pytest.approx(0.195)
    # Union: seed_a's order first, then new entries from seed_b.
    assert merged.variant_axes_observed == ["flavor", "size", "title"]
    # Capability-derived leaves come from the merged caps, not from either
    # seed's `navigation_depth_max=2` / `homepage_section_count=9|16` / etc.
    assert merged.navigation_depth_max == 3
    assert merged.homepage_section_count == 12
    assert merged.info_pages_count == 5
