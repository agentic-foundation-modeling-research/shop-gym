"""Closed schemas for the ``type: scale`` rubric entry.

* :class:`PageStats` — per-page richness measurements taken during the
  capture bundle pass (one record per applicable :class:`PageCapture`).
* :class:`ScaleMetrics` — the rolled-up record stored at
  :attr:`shop_probe.report.ProbeReport.scale`. Per-page fields are
  medians over the bundle's applicable pages; catalog fields come
  from the target's optional ``data_dir``.

Both models set ``extra="forbid"`` and ``frozen=True``: the report is
content-addressable and must round-trip exactly. The module is
import-safe — it performs no I/O at import time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PageStats(BaseModel):
    """Per-page richness measurements taken during the capture bundle pass.

    One :class:`PageStats` is computed per applicable
    :class:`shop_probe.capture.bundle.PageCapture` and stored on the
    capture row. The scale runner medians these across the bundle to
    produce :class:`ScaleMetrics`.

    Attributes:
        dom_kb_gz: Gzipped DOM size in kilobytes
            (``len(gzip.compress(html))/1024``).
        interactables_count: Number of interactable elements on the
            page (links, buttons, inputs, role-button / role-link /
            role-tab elements).
        form_fields_count: Number of form fields on the page (inputs,
            selects, textareas, contenteditable elements).
        accessibility_nodes_count: Number of nodes in the page's
            accessibility tree, derived from the same aria-snapshot
            JSON the capture-judge tier uses.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dom_kb_gz: float = Field(ge=0.0)
    interactables_count: int = Field(ge=0)
    form_fields_count: int = Field(ge=0)
    accessibility_nodes_count: int = Field(ge=0)


class ScaleMetrics(BaseModel):
    """Bundle-derived scale / richness summary for one target.

    Per-page fields are medians over the bundle's applicable pages;
    they are ``None`` when no bundle page returned :class:`PageStats`.
    Catalog fields come from the target's optional
    :attr:`shop_probe.targets.Target.data_dir` and are ``None`` when
    that directory is not set or the relevant JSON file is missing /
    in an unrecognised shape.

    Attributes:
        median_dom_kb_gz: Median gzipped DOM size in kilobytes across
            applicable bundle pages.
        interactables_per_page_median: Median count of interactable
            elements across applicable bundle pages.
        form_fields_per_page_median: Median count of form fields
            across applicable bundle pages.
        accessibility_nodes_per_page_median: Median count of
            accessibility-tree nodes across applicable bundle pages.
        catalog_products: Number of products in the target's catalog,
            read from ``<data_dir>/products.json``. ``None`` when
            ``data_dir`` is unset or the file is missing /
            unrecognised.
        catalog_collections: Number of collections in the target's
            catalog, read from ``<data_dir>/collections.json``.
            ``None`` when unavailable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    median_dom_kb_gz: float | None = Field(default=None, ge=0.0)
    interactables_per_page_median: float | None = Field(default=None, ge=0.0)
    form_fields_per_page_median: float | None = Field(default=None, ge=0.0)
    accessibility_nodes_per_page_median: float | None = Field(default=None, ge=0.0)
    catalog_products: int | None = Field(default=None, ge=0)
    catalog_collections: int | None = Field(default=None, ge=0)
