"""Axis B surface-area metrics schema for ShopProbe.

Implements the typed contract documented in
``docs/specs/shop_arena/web_probe.md`` §5.4: a closed pydantic model
that records the crawl-derived surface-area metrics for one target.

Surface metrics are *descriptive, not normative* (spec §5.4): they sit
alongside the axis-A coverage rollup in :class:`shop_probe.report.ProbeReport`
without being folded into the headline fidelity score. The per-pair
fidelity aggregator (spec §5.7) consumes :class:`SurfaceMetrics` as
``surface_ratio = surface(sandbox) / surface(source)`` per metric.

The model is import-safe: it performs no I/O at import time. The crawler
that *populates* :class:`SurfaceMetrics` lives in :mod:`shop_probe.surface.crawler`
and is wired in T2.2 (spec §7 M2).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SurfaceMetrics(BaseModel):
    """Crawl-derived surface-area metrics for one target (spec §5.4).

    The crawler walks the storefront up to a fixed depth (default
    ``depth=2`` from the homepage, plus full enumeration of
    ``/collections/*`` and a sampled ``/products/*`` set up to
    ``N=20``) and reports each metric below. All fields are
    non-negative; counts are integers and aggregations are floats.

    Per spec §5.4 the model is ``extra="forbid"`` and ``frozen=True``:
    surface metrics flow into ``ProbeReport`` (spec §5.6) and into the
    paper's surface bar chart (spec §8.4 row 3), so unknown fields and
    silent mutation are rejected.

    Attributes:
        distinct_templates: Number of structurally distinct page
            templates observed on the crawl, keyed by structural
            fingerprint (spec §5.4).
        routes_crawled: Total number of unique routes the crawler
            visited (`/`, every `/collections/*`, the sampled
            `/products/*`, etc.).
        interactables_per_template_median: Median count of
            interactables (buttons, links, inputs, role-tabs, …)
            across distinct templates.
        interactables_per_template_p95: 95th-percentile count of
            interactables across distinct templates.
        forms_total: Total number of ``<form>`` elements observed
            across all crawled pages.
        form_fields_total: Total number of form fields (``<input>``,
            ``<select>``, ``<textarea>``, ``[contenteditable]``, …)
            across all crawled pages.
        catalog_products: Number of products discovered via the
            sampled ``/products/*`` enumeration.
        catalog_collections: Number of collections discovered via the
            ``/collections/*`` enumeration.
        catalog_variants: Number of distinct product variants
            observed across the sampled product set.
        filter_x_sort_state_space: Size of the cartesian
            ``filter x sort`` URL state space exposed by collection
            pages (spec §5.4).
        median_dom_kb_gz: Median gzipped DOM size in kilobytes,
            taken across distinct templates.
        accessibility_nodes_per_template_median: Median count of
            nodes in the accessibility tree, taken across distinct
            templates.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    distinct_templates: int = Field(ge=0)
    routes_crawled: int = Field(ge=0)
    interactables_per_template_median: float = Field(ge=0.0)
    interactables_per_template_p95: float = Field(ge=0.0)
    forms_total: int = Field(ge=0)
    form_fields_total: int = Field(ge=0)
    catalog_products: int = Field(ge=0)
    catalog_collections: int = Field(ge=0)
    catalog_variants: int = Field(ge=0)
    filter_x_sort_state_space: int = Field(ge=0)
    median_dom_kb_gz: float = Field(ge=0.0)
    accessibility_nodes_per_template_median: float = Field(ge=0.0)
