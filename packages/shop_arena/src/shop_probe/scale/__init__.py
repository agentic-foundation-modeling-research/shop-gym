"""Bundle-derived scale / richness metrics for ShopProbe.

The ``type: scale`` rubric entry produces one
:class:`shop_probe.scale.metrics.ScaleMetrics` record per target by
rolling up:

* per-page richness (DOM size, interactables, form fields, accessibility
  nodes) measured during the existing 5-page capture bundle, and
* catalog counts (products + collections) read from the target's
  optional :attr:`shop_probe.targets.Target.data_dir`.

Submodules:

* :mod:`shop_probe.scale.metrics` — :class:`PageStats` +
  :class:`ScaleMetrics` schemas (no other deps; safe to import from
  ``report.py`` to avoid a cycle through ``capture.bundle``).
* :mod:`shop_probe.scale.catalog` — read ``products.json`` /
  ``collections.json`` (auto-detects list vs. wrapper shape).
* :mod:`shop_probe.scale.computer` — :func:`compute_scale_metrics`
  rolls a :class:`shop_probe.capture.bundle.PageBundle` into a
  :class:`ScaleMetrics`. Imported lazily by callers; importing eagerly
  here would pull in ``capture.bundle -> report`` and create a cycle.

The package is import-safe: the lightweight ``metrics`` and
``catalog`` modules perform no I/O at import time, and we do not
re-export the heavyweight ``computer`` module from this ``__init__``.
"""

from __future__ import annotations
