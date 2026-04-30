"""Compute :class:`ScaleMetrics` for one target.

Inputs:

* the per-shop :class:`PageBundle` produced by
  :func:`shop_probe.capture.bundle.capture_bundle`. Each applicable
  :class:`PageCapture` carries a :class:`PageStats` row recorded
  during the navigation pass.
* the target's optional ``data_dir`` (``None`` when the operator did
  not provide one in ``benchmark.yaml``). Catalog counts are read
  from ``products.json`` / ``collections.json`` inside that
  directory; absent or malformed files yield ``None``.

The module is import-safe — all I/O happens inside
:func:`compute_scale_metrics`.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from shop_probe.capture.bundle import PageBundle
from shop_probe.scale.catalog import read_catalog_counts
from shop_probe.scale.metrics import PageStats, ScaleMetrics


def _median_or_none(values: list[float]) -> float | None:
    """Return the median of ``values`` or ``None`` when empty."""
    if not values:
        return None
    return float(statistics.median(values))


def compute_scale_metrics(
    bundle: PageBundle,
    data_dir: Path | None,
) -> ScaleMetrics:
    """Roll a bundle's per-page stats (+ optional catalog) into :class:`ScaleMetrics`.

    Pages without :class:`PageStats` (``applicable=False`` or stats
    missing from a reused bundle) are skipped. When no page has
    stats, all per-page fields are ``None``.

    Args:
        bundle: The 5-page :class:`PageBundle` for the target.
        data_dir: Optional directory holding ``products.json`` /
            ``collections.json``. ``None`` ⇒ both catalog counts are
            ``None``.

    Returns:
        A populated :class:`ScaleMetrics`.
    """
    stats: list[PageStats] = [c.page_stats for c in bundle.captures if c.page_stats is not None]
    median_dom = _median_or_none([s.dom_kb_gz for s in stats])
    median_inter = _median_or_none([float(s.interactables_count) for s in stats])
    median_form = _median_or_none([float(s.form_fields_count) for s in stats])
    median_a11y = _median_or_none([float(s.accessibility_nodes_count) for s in stats])

    if data_dir is None:
        catalog_products: int | None = None
        catalog_collections: int | None = None
    else:
        catalog_products, catalog_collections = read_catalog_counts(data_dir)

    return ScaleMetrics(
        median_dom_kb_gz=median_dom,
        interactables_per_page_median=median_inter,
        form_fields_per_page_median=median_form,
        accessibility_nodes_per_page_median=median_a11y,
        catalog_products=catalog_products,
        catalog_collections=catalog_collections,
    )
