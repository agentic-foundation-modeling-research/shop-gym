"""Deterministic SVG :class:`PlaceholderBackend` for ``gen_images`` (spec §5.3).

Lifted unchanged from the v0.1 single-file ``images.py``. Emits an SVG
with a category-colored background, a category-derived geometric icon,
and the wrapped product title. All randomness is replaced with
sha256-derived choices so the same inputs always produce the same bytes
— required for the staleness contract.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import hashlib
import html
from typing import Final

_PLACEHOLDER_BACKEND_NAME: Final[str] = "placeholder"
_PLACEHOLDER_EXTENSION: Final[str] = ".svg"

_TITLE_LINE_MAX_CHARS: Final[int] = 18
"""Approximate per-line character budget for the wrapped product title."""

_TITLE_MAX_LINES: Final[int] = 4
"""Stop wrapping after this many lines so the SVG never overflows the canvas."""

_HALF: Final[float] = 0.5
"""Half-lightness pivot used by the HSL-to-RGB conversion (CSS Color spec)."""

_ICON_SHAPES: Final[tuple[str, ...]] = ("circle", "square", "triangle", "diamond")
"""Closed enum of placeholder icon shapes (selected by per-image hash)."""


class PlaceholderBackend:
    """Deterministic SVG placeholder generator (spec §5.3).

    Emits an SVG with a category-colored background, a category-derived
    geometric icon (circle / square / triangle / diamond), and the
    word-wrapped product title beneath it.
    """

    name: str = _PLACEHOLDER_BACKEND_NAME
    extension: str = _PLACEHOLDER_EXTENSION

    def render(
        self,
        *,
        handle: str,
        index: int,
        title: str,
        category: str,
        width: int,
        height: int,
    ) -> bytes:
        """Render the placeholder SVG for one product image.

        Args:
            handle: Product handle (URL-safe slug).
            index: 0-indexed image slot within the product.
            title: Product display title.
            category: Category label.
            width: Canvas width in pixels.
            height: Canvas height in pixels.

        Returns:
            UTF-8 encoded SVG bytes.

        Raises:
            ValueError: ``width`` or ``height`` is not strictly positive.
        """
        if width <= 0 or height <= 0:
            raise ValueError(
                f"placeholder backend requires positive dimensions, got {width}x{height}",
            )
        category_hash = hashlib.sha256(category.encode("utf-8")).digest()
        index_hash = hashlib.sha256(f"{handle}|{index}".encode()).digest()
        background = _hex_color_from_bytes(category_hash, lightness=0.85)
        accent = _hex_color_from_bytes(category_hash, lightness=0.45)
        icon_shape = _ICON_SHAPES[index_hash[0] % len(_ICON_SHAPES)]
        icon_svg = _render_icon(icon_shape, width=width, height=height, color=accent)
        title_svg = _render_title_text(title=title, width=width, height=height, color=accent)
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="{html.escape(title)}">\n'
            f'  <rect width="{width}" height="{height}" fill="{background}"/>\n'
            f"{icon_svg}"
            f"{title_svg}"
            f"</svg>\n"
        )
        return body.encode("utf-8")


# --------------------------------------------------------------------------- #
# SVG rendering helpers
# --------------------------------------------------------------------------- #


def _hex_color_from_bytes(digest: bytes, *, lightness: float) -> str:
    """Return a deterministic ``#rrggbb`` color derived from ``digest``."""
    hue = digest[0] / 256.0
    return _hsl_to_hex(h=hue, s=0.45, lightness=lightness)


def _hsl_to_hex(*, h: float, s: float, lightness: float) -> str:
    """Convert HSL coordinates in [0, 1] to a ``#rrggbb`` hex string."""
    if s == 0:
        gray = round(lightness * 255)
        return f"#{gray:02x}{gray:02x}{gray:02x}"
    chroma_q = lightness * (1 + s) if lightness < _HALF else lightness + s - lightness * s
    chroma_p = 2 * lightness - chroma_q
    red = _hue_to_rgb(chroma_p, chroma_q, h + 1.0 / 3.0)
    green = _hue_to_rgb(chroma_p, chroma_q, h)
    blue = _hue_to_rgb(chroma_p, chroma_q, h - 1.0 / 3.0)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _hue_to_rgb(p: float, q: float, t: float) -> float:
    """Standard HSL to RGB component conversion (CSS Color spec, deterministic)."""
    if t < 0:
        t += 1
    if t > 1:
        t -= 1
    if t < 1.0 / 6.0:
        return p + (q - p) * 6 * t
    if t < _HALF:
        return q
    if t < 2.0 / 3.0:
        return p + (q - p) * (2.0 / 3.0 - t) * 6
    return p


def _render_icon(shape: str, *, width: int, height: int, color: str) -> str:
    """Return the SVG snippet for one icon shape centered horizontally."""
    cx = width // 2
    cy = height // 3
    radius = min(width, height) // 6
    if shape == "circle":
        return f'  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="{color}"/>\n'
    if shape == "square":
        side = radius * 2
        x = cx - radius
        y = cy - radius
        return f'  <rect x="{x}" y="{y}" width="{side}" height="{side}" fill="{color}"/>\n'
    if shape == "triangle":
        x1 = cx
        y1 = cy - radius
        x2 = cx - radius
        y2 = cy + radius
        x3 = cx + radius
        y3 = cy + radius
        return f'  <polygon points="{x1},{y1} {x2},{y2} {x3},{y3}" fill="{color}"/>\n'
    if shape == "diamond":
        x1 = cx
        y1 = cy - radius
        x2 = cx + radius
        y2 = cy
        x3 = cx
        y3 = cy + radius
        x4 = cx - radius
        y4 = cy
        return f'  <polygon points="{x1},{y1} {x2},{y2} {x3},{y3} {x4},{y4}" fill="{color}"/>\n'
    raise ValueError(f"unknown icon shape {shape!r}")


def _render_title_text(*, title: str, width: int, height: int, color: str) -> str:
    """Render the wrapped product title as SVG ``<text>`` + ``<tspan>``."""
    lines = _wrap_title(title)
    cx = width // 2
    base_y = (height * 2) // 3
    font_size = max(20, min(width, height) // 24)
    line_height = int(font_size * 1.25)
    tspans: list[str] = []
    for offset, line in enumerate(lines):
        dy = 0 if offset == 0 else line_height
        tspans.append(f'    <tspan x="{cx}" dy="{dy}">{html.escape(line)}</tspan>')
    tspan_block = "\n".join(tspans)
    return (
        f'  <text x="{cx}" y="{base_y}" '
        f'fill="{color}" '
        f'font-family="sans-serif" '
        f'font-size="{font_size}" '
        f'font-weight="600" '
        f'text-anchor="middle">\n'
        f"{tspan_block}\n"
        f"  </text>\n"
    )


def _wrap_title(title: str) -> list[str]:
    """Greedy word-wrap with ellipsis truncation past the line cap."""
    words = title.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= _TITLE_LINE_MAX_CHARS:
            current = candidate
            continue
        if current:
            lines.append(current)
            if len(lines) >= _TITLE_MAX_LINES:
                break
        current = word
    if current and len(lines) < _TITLE_MAX_LINES:
        lines.append(current)
    if len(lines) >= _TITLE_MAX_LINES:
        consumed = sum(len(line.split()) for line in lines)
        if consumed < len(words):
            lines[-1] = _ellipsize(lines[-1])
    return lines


def _ellipsize(line: str) -> str:
    """Append ``"…"`` to ``line`` while staying under the per-line cap."""
    suffix = "…"
    if len(line) + len(suffix) <= _TITLE_LINE_MAX_CHARS:
        return line + suffix
    return line[: _TITLE_LINE_MAX_CHARS - len(suffix)] + suffix


__all__ = ["PlaceholderBackend"]
