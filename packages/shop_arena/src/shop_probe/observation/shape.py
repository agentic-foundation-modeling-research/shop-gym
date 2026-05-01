"""``observation.shape`` — mechanical, deterministic shape metrics.

Reads the on-disk artifacts produced by :func:`shop_probe.capture.capture_bundle`
and computes per-page-type, per-modality continuous metrics:

* a11y: ``nodes``, ``tokens``, ``actionable_count``
* screenshot: ``megapixels``, ``byte_size_kb``

No LLM, no Playwright, no I/O beyond reading the bundle files. Compared
cohort-vs-cohort with Mann-Whitney + Cliff's δ in
:mod:`shop_probe.fidelity`.

The aria-snapshot we persist (``page.locator("body").aria_snapshot()``)
is YAML-style indented text, not a tree of dicts. Counts here are line-
based and word-based heuristics — good enough to discriminate cohorts
even though they don't model the full a11y tree shape.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any, Final, cast

from shop_probe.capture.bundle import PageBundle, PageCapture
from shop_probe.report import ShapeMetrics
from shop_probe.rubric.schema import Modality, PageType

_PNG_SIGNATURE: Final[bytes] = b"\x89PNG\r\n\x1a\n"
"""8-byte PNG file signature (IHDR follows)."""

_ACTIONABLE_ROLES: Final[tuple[str, ...]] = (
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "menuitem",
    "tab",
    "switch",
    "searchbox",
    "spinbutton",
    "slider",
)
"""ARIA roles that an agent can act on.

The aria_snapshot serializes each accessibility node on its own line,
prefixed with ``- <role>``; we match those line starts.
"""

_ACTIONABLE_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+(" + "|".join(_ACTIONABLE_ROLES) + r")\b",
    re.MULTILINE,
)


def _read_a11y_text(bundle_root: Path, capture: PageCapture) -> str:
    """Return the raw aria_snapshot text for ``capture``, or ``""`` on miss."""
    if capture.accessibility_rel is None:
        return ""
    try:
        payload = json.loads(
            (bundle_root / capture.accessibility_rel).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    snap = cast(dict[str, Any], payload).get("aria_snapshot", "")
    return snap if isinstance(snap, str) else ""


def _shape_a11y(text: str) -> ShapeMetrics:
    """Compute a11y-modality shape metrics from raw aria_snapshot text."""
    if not text:
        return ShapeMetrics()
    nodes = sum(1 for line in text.splitlines() if line.strip())
    tokens = len(text.split())
    actionable = len(_ACTIONABLE_LINE_RE.findall(text))
    return ShapeMetrics(
        nodes=nodes,
        tokens=tokens,
        actionable_count=actionable,
    )


def _read_png_dimensions(path: Path) -> tuple[int, int] | None:
    """Read PNG width/height from the IHDR chunk without loading the image."""
    try:
        with path.open("rb") as fh:
            header = fh.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE:
        return None
    # IHDR is the first chunk after the signature: 4 bytes length + "IHDR" +
    # 4 bytes width (big-endian) + 4 bytes height.
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def _shape_screenshot(bundle_root: Path, capture: PageCapture) -> ShapeMetrics:
    """Compute screenshot-modality shape metrics from the PNG file."""
    if capture.screenshot_rel is None:
        return ShapeMetrics()
    path = bundle_root / capture.screenshot_rel
    if not path.is_file():
        return ShapeMetrics()
    byte_size_kb = path.stat().st_size / 1024.0
    dims = _read_png_dimensions(path)
    megapixels: float | None = None
    if dims is not None:
        width, height = dims
        megapixels = (width * height) / 1_000_000.0
    return ShapeMetrics(
        megapixels=megapixels,
        byte_size_kb=byte_size_kb,
    )


def compute_shape(
    bundle: PageBundle,
    *,
    bundle_root: Path,
    modalities: tuple[Modality, ...] = ("a11y", "screenshot"),
) -> dict[PageType, dict[Modality, ShapeMetrics]]:
    """Compute observation.shape metrics across the bundle.

    Args:
        bundle: 5-page capture bundle.
        bundle_root: Directory the bundle's relative paths resolve under.
        modalities: Subset of modalities to compute. Defaults to both.

    Returns:
        ``{page_type: {modality: ShapeMetrics}}``. Pages with
        ``applicable=False`` produce empty :class:`ShapeMetrics` rows
        (every field ``None``).
    """
    out: dict[PageType, dict[Modality, ShapeMetrics]] = {}
    for capture in bundle.captures:
        per_modality: dict[Modality, ShapeMetrics] = {}
        if "a11y" in modalities:
            text = _read_a11y_text(bundle_root, capture) if capture.applicable else ""
            per_modality["a11y"] = _shape_a11y(text)
        if "screenshot" in modalities:
            metrics = (
                _shape_screenshot(bundle_root, capture)
                if capture.applicable
                else ShapeMetrics()
            )
            per_modality["screenshot"] = metrics
        out[capture.page_type] = per_modality
    return out
