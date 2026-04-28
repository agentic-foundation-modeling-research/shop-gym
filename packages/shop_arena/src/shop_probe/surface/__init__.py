"""Axis B: crawler + surface-area metrics."""

# Only the lightweight ``SurfaceMetrics`` schema is re-exported at package
# load. The crawler imports Playwright + ``shop_probe.probes._runner``,
# which would create a circular import with ``shop_probe.report`` (which
# now references :class:`SurfaceMetrics` for spec §5.6). Consumers of the
# crawler import :class:`SurfaceCrawler` from
# :mod:`shop_probe.surface.crawler` directly.
from shop_probe.surface.metrics import SurfaceMetrics

__all__ = [
    "SurfaceMetrics",
]
