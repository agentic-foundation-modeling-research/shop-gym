"""End-to-end Phase 1 tests for the multi-seed manual-merge sub-DAG.

Covers the T2.7 requirements from
``docs/impl/shop_gen_implementation.md``:

* Drive Phase 1 end-to-end against 2-seed and 3-seed fixtures, exercising
  the full sub-DAG (``merge_capabilities`` → ``merge_manual_prose`` →
  ``compute_merge_stats`` → ``write_merge_manifest``).
* Assert ``<out_dir>/manual/`` is fully populated with the four published
  artifacts (``capabilities.json``, ``manual.md``, ``stats.json``,
  ``manifest.json``).
* Assert the merged ``capabilities.json`` validates against the closed
  :class:`shop_arena.explore.capabilities.Capabilities` schema.
* Smoke-check that no real-world brand leaks into the merged prose
  (the full allowlist scanner lands in T3.1; this is a defence in depth
  for spec §5.6).

The 2-seed fixture is deliberately constructed so that every per-area
merge rule resolves without an LLM tie-break (identical descriptors,
unanimous layout/style enums, disjoint manual sections), so the test
drives the public :func:`shop_arena.gen.pipeline.run` entrypoint without any
runtime patching.

The 3-seed fixture exercises the realistic case where the prose-merge
step calls the LLM for every overlapping section. We drive the full
DAG via :func:`shop_arena.gen.steps.runner.run_pipeline` directly so we can
inject a stub :class:`~harness.runtimes.LLMCompleter` through
:class:`StepContext`. The pipeline-level entrypoint does not currently
plumb a runtime through (M5 territory); the test still walks the same
registered DAG that :func:`shop_arena.gen.pipeline.run` produces, just with
the runtime injected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from unittest.mock import patch

from harness.runtimes import LLMCompleter
from shop_arena.explore.capabilities import Capabilities
from shop_arena.explore.stats import Stats
from shop_arena.gen import pipeline
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.manual_merge.manifest import Manifest
from shop_arena.gen.steps.base import StepContext, StepStatus
from shop_arena.gen.steps.runner import run_pipeline
from shop_arena.gen.steps.state import read_state

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


@dataclass
class _StubCompleter:
    """Recording :class:`LLMCompleter` that returns canned responses.

    Each call dequeues one response from ``responses``; an empty queue
    raises so the test fails loudly when the merge calls the LLM more
    times than expected.
    """

    responses: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM was called more times than expected")
        return self.responses.pop(0)


def _write_seed(
    seed_dir: Path,
    *,
    capabilities: dict[str, object],
    manual_body: str,
    stats: dict[str, object],
) -> Path:
    """Materialise one seed under the canonical ``<seed>/artifact/`` layout."""
    artifact = seed_dir / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "capabilities.json").write_text(json.dumps(capabilities), encoding="utf-8")
    (artifact / "manual.md").write_text(manual_body, encoding="utf-8")
    (artifact / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    return seed_dir


def _seed_manual(descriptor: str, *, sections: dict[str, str]) -> str:
    """Render a manual body with H1 + named H2 sections."""
    pieces = [f"# Shop Manual — {descriptor}", ""]
    for name, body in sections.items():
        pieces.append(f"## {name}")
        pieces.append("")
        pieces.append(body.rstrip())
        pieces.append("")
    return "\n".join(pieces).rstrip() + "\n"

def _assert_phase1_outputs_present(out_dir: Path) -> None:
    """Assert every Phase 1 artifact exists and validates against its schema."""
    manual_dir = out_dir / "manual"
    assert (manual_dir / "capabilities.json").is_file()
    assert (manual_dir / "manual.md").is_file()
    assert (manual_dir / "stats.json").is_file()
    assert (manual_dir / "manifest.json").is_file()

    # Closed-schema validation.
    Capabilities.model_validate_json(
        (manual_dir / "capabilities.json").read_text(encoding="utf-8"),
    )
    Stats.model_validate_json(
        (manual_dir / "stats.json").read_text(encoding="utf-8"),
    )
    Manifest.model_validate_json(
        (manual_dir / "manifest.json").read_text(encoding="utf-8"),
    )


def _assert_all_manual_merge_steps_fresh(out_dir: Path) -> None:
    """Assert every Phase 1 step persisted ``StepStatus.FRESH``."""
    state = read_state(out_dir)
    expected = (
        "merge_capabilities",
        "merge_manual_prose",
        "compute_merge_stats",
        "write_merge_manifest",
    )
    for step_id in expected:
        record = state.steps.get(step_id)
        assert record is not None, f"{step_id!r} not recorded in state.json"
        assert record.status is StepStatus.FRESH, f"{step_id!r} expected FRESH, got {record.status}"
        assert record.fingerprint is not None


# --------------------------------------------------------------------------- #
# 2-seed end-to-end (no LLM calls)
# --------------------------------------------------------------------------- #


def test_phase1_two_seed_end_to_end_no_llm(tmp_path: Path) -> None:
    """Two seeds with disjoint sections + identical descriptor merge without an LLM.

    Designed so every §9.2 merge rule resolves without a tie-break:

    * ``shop.descriptor`` is unanimous → no LLM merge.
    * ``collection.layout`` / ``site_shell.header_style`` are unanimous
      → no layout/style LLM tie-break.
    * Manual sections are disjoint across seeds → no prose LLM merge.
    * ``cart.has_promo_input`` differs (True / False) → bool union.
    * ``collection.filters`` / ``product.variant_selectors`` differ
      → list union.
    * ``site_shell.nav_depth`` differs (1 / 3) → max wins.

    This lets the test drive the public :func:`shop_arena.gen.pipeline.run`
    entrypoint with no runtime patching, asserting that the multi-seed
    sub-DAG comes up green out of the box.
    """
    descriptor = "boutique outdoor storefront"

    seed_a = _write_seed(
        tmp_path / "seed_a",
        capabilities={
            "version": "0.1",
            "shop": {
                "descriptor": descriptor,
                "category": "outdoor",
                "currency": "USD",
                "tone": ["rugged", "warm"],
            },
            "site_shell": {
                "nav_depth": 1,
                "header_style": "transparent",
                "has_announcement_bar": True,
            },
            "homepage": {
                "section_types": ["hero", "grid"],
                "section_count": 4,
            },
            "collection": {
                "layout": "grid",
                "filters": ["availability", "price"],
                "sort": ["best-selling"],
            },
            "product": {
                "variant_selectors": ["size"],
                "has_reviews": True,
            },
            "cart": {"has_promo_input": True},
            "info_pages_present": ["about", "contact"],
        },
        manual_body=_seed_manual(
            descriptor,
            sections={
                "Overview": "Seed A overview — a focused outdoor storefront.",
                "Cart": "Right-side drawer with promo input.",
            },
        ),
        stats={
            "products_total": 80,
            "collections_total": 4,
            "products_per_collection": {"avg": 20.0, "median": 18.0, "max": 30},
            "price": {
                "min": 9.99,
                "max": 199.99,
                "median": 49.99,
                "currency": "USD",
            },
            "products_with_variants_pct": 0.6,
            "variant_axes_observed": ["size", "color"],
            "navigation_depth_max": 1,
            "homepage_section_count": 4,
            "info_pages_count": 2,
            "feature_count": 14,
        },
    )
    seed_b = _write_seed(
        tmp_path / "seed_b",
        capabilities={
            "version": "0.1",
            "shop": {
                "descriptor": descriptor,
                "category": "outdoor",
                "currency": "USD",
                "tone": ["rugged", "playful"],
            },
            "site_shell": {
                "nav_depth": 3,
                "header_style": "transparent",
                "has_announcement_bar": False,
            },
            "homepage": {
                "section_types": ["hero", "press"],
                "section_count": 5,
            },
            "collection": {
                "layout": "grid",
                "filters": ["price", "color"],
                "sort": ["price-asc"],
            },
            "product": {
                "variant_selectors": ["color"],
                "has_reviews": True,
            },
            "cart": {"has_promo_input": False},
            "info_pages_present": ["about", "shipping"],
        },
        manual_body=_seed_manual(
            descriptor,
            sections={
                "Site shell": "Sticky transparent header with mega menu disabled.",
                "Search": "Modal search with predictive results.",
            },
        ),
        stats={
            "products_total": 220,
            "collections_total": 12,
            "products_per_collection": {"avg": 18.0, "median": 14.0, "max": 45},
            "price": {
                "min": 4.99,
                "max": 299.99,
                "median": 39.99,
                "currency": "USD",
            },
            "products_with_variants_pct": 0.4,
            "variant_axes_observed": ["color", "material"],
            "navigation_depth_max": 3,
            "homepage_section_count": 5,
            "info_pages_count": 2,
            "feature_count": 18,
        },
    )

    out_dir = tmp_path / "out"
    config = ShopGenConfig(seeds=[seed_a, seed_b], out_dir=out_dir)
    # Phase 2 ``synth_identity`` (T3.3) needs an LLM completer; this
    # test exercises Phase 1 only, so patch the data-synth registration.
    with (
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        result = pipeline.run(config)

    assert result.out_dir == out_dir
    _assert_phase1_outputs_present(out_dir)
    _assert_all_manual_merge_steps_fresh(out_dir)

    # Capabilities reflect the per-area merge rules.
    merged = Capabilities.model_validate_json(
        (out_dir / "manual" / "capabilities.json").read_text(encoding="utf-8"),
    )
    assert merged.shop.descriptor == descriptor
    # bool union: True wins.
    assert merged.cart.has_promo_input is True
    # max wins for nav_depth.
    assert merged.site_shell.nav_depth == 3  # noqa: PLR2004
    # list union, dedup, seed-order: seed_a first.
    assert merged.collection.filters == ["availability", "price", "color"]
    assert merged.product.variant_selectors == ["size", "color"]
    # Layout enum unanimous — no tie-break needed.
    assert merged.collection.layout == "grid"
    assert merged.site_shell.header_style == "transparent"

    # Manual prose: H1 + disjoint sections in canonical order.
    body = (out_dir / "manual" / "manual.md").read_text(encoding="utf-8")
    assert body.startswith(f"# Shop Manual — {descriptor}\n")
    assert "## Overview" in body
    assert "## Site shell" in body
    assert "## Cart" in body
    assert "## Search" in body
    _assert_no_real_brand_leaks(body)

    # Stats: median of (80, 220) → 150; max-of-maxes for price.
    stats = Stats.model_validate_json(
        (out_dir / "manual" / "stats.json").read_text(encoding="utf-8"),
    )
    assert stats.products_total == 150  # noqa: PLR2004
    assert stats.price.max == 299.99  # noqa: PLR2004
    assert stats.price.min == 4.99  # noqa: PLR2004
    # nav_depth comes from merged caps (max=3), not from either seed's stats.
    assert stats.navigation_depth_max == 3  # noqa: PLR2004

    # Manifest carries the seed list and a non-empty conflict log.
    manifest = Manifest.model_validate_json(
        (out_dir / "manual" / "manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest.seeds == [seed_a.as_posix(), seed_b.as_posix()]
    conflict_paths = {conflict.path for conflict in manifest.capability_conflicts}
    assert {"cart.has_promo_input", "site_shell.nav_depth"} <= conflict_paths


# --------------------------------------------------------------------------- #
# 3-seed end-to-end (LLM merges overlapping prose)
# --------------------------------------------------------------------------- #


def test_phase1_three_seed_end_to_end_with_llm(tmp_path: Path) -> None:
    """Three seeds with overlapping sections drive a stub LLM through the prose merge.

    The fixture exercises the realistic multi-seed case:

    * Three seeds share the same canonical sections, so the prose merge
      delegates one LLM call per overlapping section.
    * Boolean / scalar / list rules from spec §9.2 each surface a
      conflict in the manifest.
    * ``info_pages_present`` is unioned across seeds; the merged caps
      drive ``stats.info_pages_count`` deterministically.

    The pipeline-level :func:`shop_arena.gen.pipeline.run` does not currently
    plumb a runtime through ``StepContext``; we therefore drive the
    same registered DAG via :func:`run_pipeline` directly, injecting the
    stub completer through ``StepContext.runtime``.
    """
    descriptor = "premium home goods storefront"

    seed_caps = [
        {
            "shop": {
                "descriptor": descriptor,
                "category": "home",
                "currency": "USD",
                "tone": ["clean"],
            },
            "site_shell": {"nav_depth": 2, "header_style": "transparent"},
            "homepage": {"section_types": ["hero"], "section_count": 3},
            "collection": {
                "layout": "grid",
                "filters": ["availability"],
                "sort": ["best-selling"],
            },
            "product": {"variant_selectors": ["size"], "has_reviews": True},
            "cart": {"has_promo_input": True},
            "info_pages_present": ["about", "contact"],
        },
        {
            "shop": {
                "descriptor": descriptor,
                "category": "home",
                "currency": "USD",
                "tone": ["minimal"],
            },
            "site_shell": {"nav_depth": 3, "header_style": "transparent"},
            "homepage": {"section_types": ["hero", "grid"], "section_count": 4},
            "collection": {
                "layout": "grid",
                "filters": ["price"],
                "sort": ["price-asc"],
            },
            "product": {"variant_selectors": ["color"], "has_reviews": True},
            "cart": {"has_promo_input": True},
            "info_pages_present": ["about", "shipping"],
        },
        {
            "shop": {
                "descriptor": descriptor,
                "category": "home",
                "currency": "USD",
                "tone": ["warm"],
            },
            "site_shell": {"nav_depth": 1, "header_style": "transparent"},
            "homepage": {
                "section_types": ["hero", "newsletter"],
                "section_count": 5,
            },
            "collection": {
                "layout": "grid",
                "filters": ["availability", "price"],
                "sort": ["best-selling"],
            },
            "product": {"variant_selectors": ["size"], "has_reviews": False},
            "cart": {"has_promo_input": False},
            "info_pages_present": ["about", "faq"],
        },
    ]
    seed_stats = [
        {
            "products_total": 120,
            "collections_total": 6,
            "products_per_collection": {"avg": 20.0, "median": 18.0, "max": 35},
            "price": {
                "min": 9.99,
                "max": 199.0,
                "median": 49.0,
                "currency": "USD",
            },
            "products_with_variants_pct": 0.5,
            "variant_axes_observed": ["size"],
            "navigation_depth_max": 2,
            "homepage_section_count": 3,
            "info_pages_count": 2,
            "feature_count": 10,
        },
        {
            "products_total": 200,
            "collections_total": 10,
            "products_per_collection": {"avg": 22.0, "median": 20.0, "max": 50},
            "price": {
                "min": 12.0,
                "max": 350.0,
                "median": 60.0,
                "currency": "USD",
            },
            "products_with_variants_pct": 0.4,
            "variant_axes_observed": ["color"],
            "navigation_depth_max": 3,
            "homepage_section_count": 4,
            "info_pages_count": 2,
            "feature_count": 14,
        },
        {
            "products_total": 80,
            "collections_total": 4,
            "products_per_collection": {"avg": 18.0, "median": 16.0, "max": 28},
            "price": {
                "min": 5.0,
                "max": 99.0,
                "median": 25.0,
                "currency": "USD",
            },
            "products_with_variants_pct": 0.3,
            "variant_axes_observed": ["size", "material"],
            "navigation_depth_max": 1,
            "homepage_section_count": 5,
            "info_pages_count": 2,
            "feature_count": 8,
        },
    ]
    overlapping_sections = (
        "Overview",
        "Site shell",
        "Homepage",
        "Cart",
    )
    seed_paths: list[Path] = []
    for index, (caps, stats_payload) in enumerate(
        zip(seed_caps, seed_stats, strict=True),
    ):
        full_caps = {"version": "0.1", **caps}
        seed_dir = _write_seed(
            tmp_path / f"seed_{index}",
            capabilities=full_caps,
            manual_body=_seed_manual(
                descriptor,
                sections={
                    section: f"Seed {index} — {section} body." for section in overlapping_sections
                },
            ),
            stats=stats_payload,
        )
        seed_paths.append(seed_dir)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ShopGenConfig(seeds=seed_paths, out_dir=out_dir)

    completer = _StubCompleter(
        responses=[
            f"Merged {section.lower()} body, brand-anonymized." for section in overlapping_sections
        ],
    )
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )

    # Drive the same DAG ``pipeline.run`` would build, but with the runtime
    # injected so the prose merge can call the stub completer. Phase 2
    # ``synth_identity`` (T3.3) needs an LLM completer of its own; this
    # test exercises Phase 1 only, so patch the data-synth registration
    # before snapshotting the registry.
    with (
        patch.object(pipeline, "_register_data_synth", lambda reg, **_: None),
        patch.object(pipeline, "_register_data_validation", lambda reg: None),
        patch.object(pipeline, "_register_build", lambda reg: None),
        patch.object(pipeline, "_register_final_eval", lambda reg, **_: None),
    ):
        registry = pipeline._build_registry(config)
    result = run_pipeline(registry.all(), ctx)

    # Topological order with id-sorted tie-breaking (spec §5.7,
    # ``run_pipeline``): ``merge_manual_prose`` and ``compute_merge_stats``
    # both depend only on ``merge_capabilities``, so the runner schedules
    # them alphabetically (``c`` < ``m``). ``split_manual_parts`` runs
    # downstream of ``merge_manual_prose`` (per
    # ``docs/specs/shop_arena/manual_split.md``).
    assert result.ran == (
        "merge_capabilities",
        "compute_merge_stats",
        "merge_manual_prose",
        "split_manual_parts",
        "write_merge_manifest",
    )
    _assert_phase1_outputs_present(out_dir)
    _assert_all_manual_merge_steps_fresh(out_dir)

    # One LLM call per overlapping canonical section (no descriptor /
    # layout-enum tie-breaks: descriptor unanimous, layout unanimous).
    assert len(completer.prompts) == len(overlapping_sections)

    merged = Capabilities.model_validate_json(
        (out_dir / "manual" / "capabilities.json").read_text(encoding="utf-8"),
    )
    assert merged.shop.descriptor == descriptor
    # bool union: 2/3 True → True (and surfaces as a conflict).
    assert merged.cart.has_promo_input is True
    # nav_depth max across (2, 3, 1) → 3.
    assert merged.site_shell.nav_depth == 3  # noqa: PLR2004
    # info_pages_present is a list union over seed order.
    assert set(merged.info_pages_present) == {"about", "contact", "shipping", "faq"}
    # tone capped at 3, list union seed-order.
    assert merged.shop.tone == ["clean", "minimal", "warm"]

    body = (out_dir / "manual" / "manual.md").read_text(encoding="utf-8")
    assert body.startswith(f"# Shop Manual — {descriptor}\n")
    for section in overlapping_sections:
        assert f"## {section}" in body
        assert f"Merged {section.lower()} body, brand-anonymized." in body
    _assert_no_real_brand_leaks(body)

    stats = Stats.model_validate_json(
        (out_dir / "manual" / "stats.json").read_text(encoding="utf-8"),
    )
    # median of (120, 200, 80) → 120.
    assert stats.products_total == 120  # noqa: PLR2004
    # max-of-maxes / min-of-mins across seeds with non-zero price signal.
    assert stats.price.max == 350.0  # noqa: PLR2004
    assert stats.price.min == 5.0  # noqa: PLR2004
    # Capability-derived leaves come from the merged caps.
    assert stats.navigation_depth_max == 3  # noqa: PLR2004
    assert stats.info_pages_count == len(merged.info_pages_present)

    manifest = Manifest.model_validate_json(
        (out_dir / "manual" / "manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest.seeds == [seed.as_posix() for seed in seed_paths]
    conflict_paths = {conflict.path for conflict in manifest.capability_conflicts}
    # The 3-seed fixture must surface conflicts on the per-area rules
    # exercised above.
    assert "cart.has_promo_input" in conflict_paths
    assert "site_shell.nav_depth" in conflict_paths
    assert "homepage.section_count" in conflict_paths
