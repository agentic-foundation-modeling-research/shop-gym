"""Tests for `shop_probe.scale.computer.compute_scale_metrics`.

Covers:

* Rolling per-page :class:`PageStats` into median fields on
  :class:`ScaleMetrics`.
* Skipping non-applicable rows (no ``page_stats``).
* Catalog counts populated when ``data_dir`` is set, ``None``
  otherwise.
* All-``None`` per-page fields when no bundle page has stats.
"""

from __future__ import annotations

import json
from pathlib import Path

from shop_probe.capture.bundle import PageBundle, PageCapture
from shop_probe.rubric.schema import PageRef
from shop_probe.scale.computer import compute_scale_metrics
from shop_probe.scale.metrics import PageStats


def _stats(
    *,
    dom_kb_gz: float,
    interactables: int,
    form_fields: int,
    a11y: int,
) -> PageStats:
    return PageStats(
        dom_kb_gz=dom_kb_gz,
        interactables_count=interactables,
        form_fields_count=form_fields,
        accessibility_nodes_count=a11y,
    )


def _capture(
    page_ref: PageRef,
    *,
    page_stats: PageStats | None = None,
    applicable: bool = True,
) -> PageCapture:
    return PageCapture(
        page_ref=page_ref,
        url=f"http://localhost/{page_ref}",
        screenshot_rel=f"_bundle/{page_ref}/shot.png" if applicable else None,
        accessibility_rel=f"_bundle/{page_ref}/a11y.json" if applicable else None,
        applicable=applicable,
        page_stats=page_stats,
    )


def _bundle_with_stats(values: list[tuple[float, int, int, int]]) -> PageBundle:
    refs: tuple[PageRef, ...] = ("home", "collection", "product", "cart", "search")
    captures = tuple(
        _capture(
            ref,
            page_stats=_stats(
                dom_kb_gz=dom,
                interactables=inter,
                form_fields=form,
                a11y=a11y,
            ),
        )
        for ref, (dom, inter, form, a11y) in zip(refs, values, strict=True)
    )
    return PageBundle(captures=captures)


def test_compute_scale_metrics_medians_across_five_pages(tmp_path: Path) -> None:
    bundle = _bundle_with_stats(
        [
            (10.0, 20, 1, 100),
            (20.0, 40, 3, 200),
            (30.0, 60, 5, 300),
            (40.0, 80, 7, 400),
            (50.0, 100, 9, 500),
        ]
    )
    metrics = compute_scale_metrics(bundle, data_dir=None)
    assert metrics.median_dom_kb_gz == 30.0  # noqa: PLR2004
    assert metrics.interactables_per_page_median == 60.0  # noqa: PLR2004
    assert metrics.form_fields_per_page_median == 5.0  # noqa: PLR2004
    assert metrics.accessibility_nodes_per_page_median == 300.0  # noqa: PLR2004
    assert metrics.catalog_products is None
    assert metrics.catalog_collections is None


def test_compute_scale_metrics_skips_non_applicable_pages() -> None:
    bundle = PageBundle(
        captures=(
            _capture(
                "home",
                page_stats=_stats(dom_kb_gz=10.0, interactables=10, form_fields=1, a11y=100),
            ),
            _capture("cart", applicable=False),  # no stats
            _capture(
                "product",
                page_stats=_stats(dom_kb_gz=30.0, interactables=30, form_fields=3, a11y=300),
            ),
        )
    )
    metrics = compute_scale_metrics(bundle, data_dir=None)
    # Median over the two applicable rows: (10.0 + 30.0) / 2 = 20.0
    assert metrics.median_dom_kb_gz == 20.0  # noqa: PLR2004
    assert metrics.interactables_per_page_median == 20.0  # noqa: PLR2004


def test_compute_scale_metrics_no_stats_returns_none_per_page_fields() -> None:
    bundle = PageBundle(
        captures=(
            _capture("home", applicable=False),
            _capture("cart", applicable=False),
        )
    )
    metrics = compute_scale_metrics(bundle, data_dir=None)
    assert metrics.median_dom_kb_gz is None
    assert metrics.interactables_per_page_median is None
    assert metrics.form_fields_per_page_median is None
    assert metrics.accessibility_nodes_per_page_median is None


def test_compute_scale_metrics_with_data_dir_populates_catalog(tmp_path: Path) -> None:
    (tmp_path / "products.json").write_text(
        json.dumps([{"id": i} for i in range(7)]), encoding="utf-8"
    )
    (tmp_path / "collections.json").write_text(
        json.dumps({"collections": [{"id": "c1"}, {"id": "c2"}]}),
        encoding="utf-8",
    )
    bundle = _bundle_with_stats(
        [
            (10.0, 10, 1, 100),
            (20.0, 20, 2, 200),
            (30.0, 30, 3, 300),
            (40.0, 40, 4, 400),
            (50.0, 50, 5, 500),
        ]
    )
    metrics = compute_scale_metrics(bundle, data_dir=tmp_path)
    assert metrics.catalog_products == 7  # noqa: PLR2004
    assert metrics.catalog_collections == 2  # noqa: PLR2004


def test_compute_scale_metrics_data_dir_without_files_yields_none_catalog(
    tmp_path: Path,
) -> None:
    bundle = _bundle_with_stats(
        [
            (10.0, 10, 1, 100),
            (20.0, 20, 2, 200),
            (30.0, 30, 3, 300),
            (40.0, 40, 4, 400),
            (50.0, 50, 5, 500),
        ]
    )
    metrics = compute_scale_metrics(bundle, data_dir=tmp_path)
    assert metrics.catalog_products is None
    assert metrics.catalog_collections is None
    # Per-page fields still populated.
    assert metrics.median_dom_kb_gz == 30.0  # noqa: PLR2004
