"""``gen_images`` — Phase 2 placeholder image generation (spec §5.3).

Pluggable image-generation step. v0.1 ships a deterministic
:class:`PlaceholderBackend` that emits one SVG per product image with a
category icon + the product title rendered as text. The :class:`AIBackend`
is stubbed and raises :class:`NotImplementedError`; the real AI image
generator lands in M8 (spec §8).

The step iterates every cached :class:`ProductSkeleton` and every
``images_per_product`` slot, asks the configured backend to render the
bytes, and writes them to ``<out_dir>/data/images/<handle>-<n>.<ext>``.
A small staleness sentinel manifest is written under
``<out_dir>/.shop_gen/stage_cache/images_manifest.json`` so the runner
can detect missing or fingerprint-mismatched outputs without
enumerating the catalog.

Step contract (spec §5.7.1):

* ``id``: ``gen_images``.
* ``phase``: ``data_synth``.
* ``inputs``: one :class:`~shop_gen.steps.base.StepInput` referencing
  ``synth_product_details``. Cascading through that step covers the
  upstream skeletons, collections, and identity payloads. Spec §5.3
  table.
* ``outputs``: ``.shop_gen/stage_cache/images_manifest.json``.
* ``depends_on``: ``[synth_product_details]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any, Final, Protocol, cast, runtime_checkable

from pydantic import ValidationError

from shop_gen.config import ImageBackend as ImageBackendName
from shop_gen.data_synth._synth_helpers import StageSynthError
from shop_gen.data_synth.collections import CollectionDraft
from shop_gen.data_synth.details import ProductDetail
from shop_gen.data_synth.skeletons import ProductSkeleton
from shop_gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "gen_images"
_UPSTREAM_ID: Final[str] = "synth_product_details"
_STEP_VERSION: Final[int] = 1

_OUT_MANIFEST: Final[Path] = Path(".shop_gen") / "stage_cache" / "images_manifest.json"
_OUT_IMAGES_DIR: Final[Path] = Path("data") / "images"
_IN_DETAILS_MANIFEST: Final[Path] = Path(".shop_gen") / "stage_cache" / "details" / "_manifest.json"
_IN_DETAILS_DIR: Final[Path] = Path(".shop_gen") / "stage_cache" / "details"
_IN_SKELETONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "skeletons.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"

_DEFAULT_WIDTH: Final[int] = 800
_DEFAULT_HEIGHT: Final[int] = 800
"""Square gallery dimensions (spec §5.3 "sized to honor capabilities.json's gallery hints").

Capabilities only carries qualitative gallery hints
(:attr:`shop_explore.capabilities.schema.Product.gallery_style`) at v0.1, so
the placeholder backend ships a fixed 800x800 canvas. Backends are free to
honor a richer hint when the spec adds dimension fields.
"""

_PLACEHOLDER_BACKEND_NAME: Final[str] = "placeholder"
_AI_BACKEND_NAME: Final[str] = "ai"
_PLACEHOLDER_EXTENSION: Final[str] = ".svg"
_AI_EXTENSION: Final[str] = ".png"

_TITLE_LINE_MAX_CHARS: Final[int] = 18
"""Approximate per-line character budget for the wrapped product title."""

_TITLE_MAX_LINES: Final[int] = 4
"""Stop wrapping after this many lines so the SVG never overflows the canvas."""

_HALF: Final[float] = 0.5
"""Half-lightness pivot used by the HSL-to-RGB conversion (CSS Color spec)."""


# --------------------------------------------------------------------------- #
# Backend protocol + implementations
# --------------------------------------------------------------------------- #


@runtime_checkable
class ImageBackend(Protocol):
    """One pluggable image-generation backend (spec §5.3).

    Backends produce raw bytes for a single product image. They are
    stateless and side-effect-free — :class:`GenImagesStep` owns the
    filesystem write so backends remain trivially unit-testable.

    Attributes:
        name: Backend identifier (matches
            :data:`shop_gen.config.ImageBackend` values).
        extension: File extension (with leading dot, e.g. ``".svg"``).
    """

    name: str
    extension: str

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
        """Render one product image as raw bytes.

        Args:
            handle: Product handle (URL-safe slug).
            index: 0-indexed image slot within the product.
            title: Product display title.
            category: Category label (typically the collection title or
                product type) — drives the placeholder icon hashing so
                products in the same category share visual identity.
            width: Canvas width in pixels.
            height: Canvas height in pixels.

        Returns:
            The image bytes ready for ``Path.write_bytes``.

        Raises:
            NotImplementedError: The backend is a stub (e.g. ``ai`` in
                v0.1).
        """
        ...


class PlaceholderBackend:
    """Deterministic SVG placeholder generator (spec §5.3).

    Emits an SVG with a category-colored background, a category-derived
    geometric icon (circle / square / triangle / diamond), and the
    word-wrapped product title beneath it. All randomness is replaced
    with sha256-derived choices so the same inputs always produce the
    same bytes — required for fingerprint-based staleness detection.
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

        See :meth:`ImageBackend.render` for argument semantics.

        Returns:
            UTF-8 encoded SVG bytes.

        Raises:
            ValueError: ``width`` or ``height`` is not strictly positive.
        """
        if width <= 0 or height <= 0:
            raise ValueError(
                f"placeholder backend requires positive dimensions, got {width}x{height}",
            )
        # ``index`` is part of the icon-hash payload so the per-product
        # image gallery has visible variety without breaking determinism.
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


class AIBackend:
    """Stub for the v0.2 AI image backend (spec §8, M8).

    Construction is allowed so the backend appears in registries and
    ``--list-steps`` output, but :meth:`render` always raises
    :class:`NotImplementedError`. The real implementation lands in M8.
    """

    name: str = _AI_BACKEND_NAME
    extension: str = _AI_EXTENSION

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
        """Always raise :class:`NotImplementedError`.

        Args:
            handle: Unused (recorded for interface compatibility).
            index: Unused.
            title: Unused.
            category: Unused.
            width: Unused.
            height: Unused.

        Raises:
            NotImplementedError: The AI backend lands in M8 (spec §8).
        """
        del handle, index, title, category, width, height
        raise NotImplementedError(
            f"{_AI_BACKEND_NAME!r} image backend is stubbed in v0.1; "
            "the real generator lands in M8 (spec §8)",
        )


def get_backend(name: ImageBackendName) -> ImageBackend:
    """Return the :class:`ImageBackend` matching ``name``.

    Args:
        name: One of :data:`shop_gen.config.ImageBackend` literals.

    Returns:
        A fresh backend instance. Backends are stateless so a singleton
        would be valid, but a fresh instance keeps test isolation
        trivial.

    Raises:
        ValueError: ``name`` is not a recognised backend.
    """
    if name == _PLACEHOLDER_BACKEND_NAME:
        return PlaceholderBackend()
    if name == _AI_BACKEND_NAME:
        return AIBackend()
    raise ValueError(f"unknown image backend {name!r}")


# --------------------------------------------------------------------------- #
# Step
# --------------------------------------------------------------------------- #


class GenImagesStep:
    """Phase 2 ``gen_images`` step (spec §5.3).

    Reads the cached collections, skeletons, and per-collection details,
    asks the configured :class:`ImageBackend` to render every
    ``(product, image_index)`` pair, and writes the bytes under
    ``data/images/`` plus a sentinel manifest under
    ``.shop_gen/stage_cache/images_manifest.json``.

    Attributes:
        id: Step id (``gen_images``).
        phase: ``data_synth``.
        inputs: One :class:`StepInput` referencing
            ``synth_product_details``.
        outputs: ``.shop_gen/stage_cache/images_manifest.json``. The
            individual image files under ``data/images/`` are siblings;
            declaring only the manifest as the staleness sentinel keeps
            the step's :attr:`outputs` list independent of the catalog
            size.
        depends_on: ``[synth_product_details]``.
        version: Bumped when the synthesis behaviour changes (spec §5.7.1).
    """

    def __init__(self) -> None:
        """Build the step bound to the ``synth_product_details`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_MANIFEST]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Generate the placeholder image set for the catalog.

        Args:
            ctx: Execution context. ``ctx.runtime`` is unused — image
                generation is fully deterministic at v0.1.

        Raises:
            FileNotFoundError: Any of the upstream cached files
                (``collections.json``, ``skeletons.json``,
                ``details/_manifest.json``) is missing.
            ValueError: The configured ``image_backend`` is unknown.
            StageSynthError: A cached file is malformed.
        """
        collections_path = ctx.out_dir / _IN_COLLECTIONS
        if not collections_path.exists():
            raise FileNotFoundError(
                f"cached collections not found at {collections_path}; run synth_collections first",
            )
        skeletons_path = ctx.out_dir / _IN_SKELETONS
        if not skeletons_path.exists():
            raise FileNotFoundError(
                f"cached skeletons not found at {skeletons_path}; "
                "run synth_product_skeletons first",
            )
        manifest_path = ctx.out_dir / _IN_DETAILS_MANIFEST
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"cached details manifest not found at {manifest_path}; "
                "run synth_product_details first",
            )

        collections = _load_collections(collections_path)
        skeletons = _load_skeletons(skeletons_path)
        details_by_handle = _load_details_by_handle(
            manifest_path=manifest_path,
            details_dir=ctx.out_dir / _IN_DETAILS_DIR,
        )
        category_by_handle = _category_by_handle(
            skeletons=skeletons,
            collections=collections,
            details_by_handle=details_by_handle,
        )

        backend = get_backend(ctx.config.image_backend)
        images_per_product = ctx.config.catalog.images_per_product
        images_dir = ctx.out_dir / _OUT_IMAGES_DIR
        images_dir.mkdir(parents=True, exist_ok=True)

        manifest_entries: list[dict[str, Any]] = []
        for skeleton in skeletons:
            category = category_by_handle[skeleton.handle]
            for index in range(images_per_product):
                file_name = f"{skeleton.handle}-{index}{backend.extension}"
                file_path = images_dir / file_name
                image_bytes = backend.render(
                    handle=skeleton.handle,
                    index=index,
                    title=skeleton.title,
                    category=category,
                    width=_DEFAULT_WIDTH,
                    height=_DEFAULT_HEIGHT,
                )
                file_path.write_bytes(image_bytes)
                manifest_entries.append(
                    {
                        "handle": skeleton.handle,
                        "index": index,
                        "file": f"{_OUT_IMAGES_DIR.as_posix()}/{file_name}",
                        "width": _DEFAULT_WIDTH,
                        "height": _DEFAULT_HEIGHT,
                    },
                )

        manifest = {
            "backend": backend.name,
            "extension": backend.extension,
            "images_per_product": images_per_product,
            "total_images": len(manifest_entries),
            "entries": manifest_entries,
        }
        out_path = ctx.out_dir / _OUT_MANIFEST
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# SVG rendering helpers
# --------------------------------------------------------------------------- #


_ICON_SHAPES: Final[tuple[str, ...]] = ("circle", "square", "triangle", "diamond")
"""Closed enum of placeholder icon shapes (selected by per-image hash)."""


def _hex_color_from_bytes(digest: bytes, *, lightness: float) -> str:
    """Return a deterministic ``#rrggbb`` color derived from ``digest``.

    The hue is taken from the first byte of ``digest`` and converted to
    an HSL color with fixed saturation. ``lightness`` controls
    background-vs-accent contrast: higher → lighter (used for
    backgrounds), lower → darker (used for accents).
    """
    hue = digest[0] / 256.0
    return _hsl_to_hex(h=hue, s=0.45, lightness=lightness)


def _hsl_to_hex(*, h: float, s: float, lightness: float) -> str:
    """Convert HSL coordinates in [0, 1] to a ``#rrggbb`` hex string.

    Pure float arithmetic on inputs that are themselves derived from
    hashed bytes — output is byte-deterministic across runs.
    """
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
    """Return the SVG snippet for one icon shape centered horizontally.

    The icon is anchored in the upper third of the canvas so the title
    text below has room to breathe regardless of how many wrap lines it
    needs.
    """
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
    """Render the wrapped product title as SVG ``<text>`` + ``<tspan>``.

    Word-wrapping is greedy and capped at :data:`_TITLE_MAX_LINES`
    lines; longer titles end with an ellipsis on the last line. The
    text is anchored at the horizontal center, two-thirds down the
    canvas, with a fixed font-size that fits comfortably for the
    default 800x800 placeholder.
    """
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
    """Greedy word-wrap with ellipsis truncation past the line cap.

    Empty / whitespace-only titles return ``[""]`` so the SVG still
    renders a (blank) text element rather than producing malformed
    markup.
    """
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
        # Truncate the last line with an ellipsis if more words remain.
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


# --------------------------------------------------------------------------- #
# Cache loaders
# --------------------------------------------------------------------------- #


def _load_collections(path: Path) -> list[CollectionDraft]:
    """Read the cached ``collections.json`` payload as ``list[CollectionDraft]``."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"cached collections at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, list):
        raise StageSynthError(
            f"cached collections at {path} must be a JSON array, got {type(raw).__name__}",
        )
    try:
        return [CollectionDraft.model_validate(entry) for entry in cast("list[Any]", raw)]
    except ValidationError as exc:
        raise StageSynthError(
            f"cached collections at {path} failed CollectionDraft schema validation: {exc}",
        ) from exc


def _load_skeletons(path: Path) -> list[ProductSkeleton]:
    """Read the cached ``skeletons.json`` payload as ``list[ProductSkeleton]``."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"cached skeletons at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, list):
        raise StageSynthError(
            f"cached skeletons at {path} must be a JSON array, got {type(raw).__name__}",
        )
    try:
        return [ProductSkeleton.model_validate(entry) for entry in cast("list[Any]", raw)]
    except ValidationError as exc:
        raise StageSynthError(
            f"cached skeletons at {path} failed ProductSkeleton schema validation: {exc}",
        ) from exc


def _load_details_by_handle(
    *,
    manifest_path: Path,
    details_dir: Path,
) -> dict[str, ProductDetail]:
    """Flatten the per-collection ``details/<handle>.json`` files into ``{handle: detail}``."""
    try:
        manifest_raw: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageSynthError(
            f"details manifest at {manifest_path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(manifest_raw, dict):
        raise StageSynthError(
            f"details manifest at {manifest_path} must be a JSON object, "
            f"got {type(manifest_raw).__name__}",
        )
    entries_raw = cast("dict[str, Any]", manifest_raw).get("collections")
    if not isinstance(entries_raw, list):
        raise StageSynthError(
            f"details manifest at {manifest_path} missing 'collections' array",
        )
    out: dict[str, ProductDetail] = {}
    for entry in cast("list[Any]", entries_raw):
        if not isinstance(entry, dict):
            raise StageSynthError(
                f"details manifest at {manifest_path} entry must be an object",
            )
        entry_dict = cast("dict[str, Any]", entry)
        file_raw = entry_dict.get("file")
        if not isinstance(file_raw, str):
            raise StageSynthError(
                f"details manifest at {manifest_path} entry missing 'file'",
            )
        details_path = details_dir / file_raw
        if not details_path.exists():
            raise FileNotFoundError(
                f"cached details file not found at {details_path}",
            )
        try:
            payload: Any = json.loads(details_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StageSynthError(
                f"cached details at {details_path} is not valid JSON: {exc}",
            ) from exc
        if not isinstance(payload, list):
            raise StageSynthError(
                f"cached details at {details_path} must be a JSON array, "
                f"got {type(payload).__name__}",
            )
        try:
            for item in cast("list[Any]", payload):
                detail = ProductDetail.model_validate(item)
                out[detail.handle] = detail
        except ValidationError as exc:
            raise StageSynthError(
                f"cached details at {details_path} failed ProductDetail schema validation: {exc}",
            ) from exc
    return out


def _category_by_handle(
    *,
    skeletons: list[ProductSkeleton],
    collections: list[CollectionDraft],
    details_by_handle: dict[str, ProductDetail],
) -> dict[str, str]:
    """Resolve each product handle's category label.

    Prefers the per-product ``product_type`` from
    :class:`ProductDetail` when available (more specific than the
    collection title), falling back to the parent collection's title.
    Products whose collection cannot be resolved fall back to the
    collection handle so the placeholder still hashes deterministically.
    """
    title_by_collection = {c.handle: c.title for c in collections}
    out: dict[str, str] = {}
    for skeleton in skeletons:
        detail = details_by_handle.get(skeleton.handle)
        if detail is not None and detail.product_type:
            out[skeleton.handle] = detail.product_type
            continue
        out[skeleton.handle] = title_by_collection.get(
            skeleton.collection_handle,
            skeleton.collection_handle,
        )
    return out


__all__ = [
    "AIBackend",
    "GenImagesStep",
    "ImageBackend",
    "PlaceholderBackend",
    "get_backend",
]
