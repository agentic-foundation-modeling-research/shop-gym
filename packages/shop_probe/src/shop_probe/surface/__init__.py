"""Axis B: crawler + surface-area metrics."""

from shop_probe.surface.crawler import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_PRODUCTS,
    DEFAULT_MAX_ROUTES,
    SurfaceCrawler,
)
from shop_probe.surface.metrics import SurfaceMetrics

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_PRODUCTS",
    "DEFAULT_MAX_ROUTES",
    "SurfaceCrawler",
    "SurfaceMetrics",
]
