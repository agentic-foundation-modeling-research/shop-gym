"""``gen_images`` — Phase 2 image generation step (spec §5.3).

Reads the cached collections, skeletons, and per-collection details,
asks the configured backend to render every ``(product, image_index)``
pair, and writes the bytes under ``data/images/`` plus a sentinel
manifest at ``.shop_gen/stage_cache/images_manifest.json``.

The step dispatches sync vs. async based on the backend's protocol:

* :class:`PlaceholderBackend` (sync) → serial in-process render.
* :class:`OpenAIImageBackend` (async) → bounded ``asyncio.Semaphore``
  fan-out so the catalog renders in ``ceil(n / concurrency)`` x per-call
  latency wall-time instead of ``n x per-call``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from shop_arena.gen.config import ImageBackend as ImageBackendName
from shop_arena.gen.data_synth._synth_helpers import StageSynthError
from shop_arena.gen.data_synth.collections import CollectionDraft
from shop_arena.gen.data_synth.details import ProductDetail
from shop_arena.gen.data_synth.images._openai_backend import OpenAIImageBackend
from shop_arena.gen.data_synth.images._placeholder import PlaceholderBackend
from shop_arena.gen.data_synth.images._protocol import AsyncImageBackend, ImageBackend
from shop_arena.gen.data_synth.skeletons import ProductSkeleton
from shop_arena.gen.steps.base import InputRef, StepContext, StepInput

_PHASE: Final[str] = "data_synth"
_STEP_ID: Final[str] = "gen_images"
_UPSTREAM_ID: Final[str] = "synth_product_details"
_STEP_VERSION: Final[int] = 2
"""Bumped to 2 in M1 when the backend literal flipped from {placeholder, ai}
to {placeholder, openai} and the manifest schema gained AI-cache fields."""

_OUT_MANIFEST: Final[Path] = Path(".shop_gen") / "stage_cache" / "images_manifest.json"
_OUT_IMAGES_DIR: Final[Path] = Path("data") / "images"
_IN_DETAILS_MANIFEST: Final[Path] = Path(".shop_gen") / "stage_cache" / "details" / "_manifest.json"
_IN_DETAILS_DIR: Final[Path] = Path(".shop_gen") / "stage_cache" / "details"
_IN_SKELETONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "skeletons.json"
_IN_COLLECTIONS: Final[Path] = Path(".shop_gen") / "stage_cache" / "collections.json"

_DEFAULT_WIDTH: Final[int] = 800
_DEFAULT_HEIGHT: Final[int] = 800
"""Square gallery dimensions for the placeholder backend (spec §5.3).

The OpenAI backend's canvas comes from
:attr:`shop_arena.gen.config.ShopGenConfig.image_size`; ``width``/``height``
are forwarded for protocol compatibility but the backend ignores them.
"""

_PLACEHOLDER_BACKEND_NAME: Final[str] = "placeholder"
_OPENAI_BACKEND_NAME: Final[str] = "openai"


def get_backend(name: ImageBackendName, *, ctx: StepContext) -> ImageBackend | AsyncImageBackend:
    """Return the backend instance matching ``name``.

    Args:
        name: One of :data:`shop_arena.gen.config.ImageBackend` literals.
        ctx: Step context — supplies ``out_dir`` (cache root) and
            ``config.image_*`` fields for the OpenAI backend.

    Returns:
        Either a synchronous :class:`ImageBackend` (placeholder) or an
        asynchronous :class:`AsyncImageBackend` (openai).

    Raises:
        ValueError: ``name`` is not a recognised backend.
    """
    if name == _PLACEHOLDER_BACKEND_NAME:
        return PlaceholderBackend()
    if name == _OPENAI_BACKEND_NAME:
        return OpenAIImageBackend(
            out_dir=ctx.out_dir,
            model=ctx.config.image_model or "gpt-image-1",
            size=ctx.config.image_size,
        )
    raise ValueError(f"unknown image backend {name!r}")


class GenImagesStep:
    """Phase 2 ``gen_images`` step (spec §5.3)."""

    def __init__(self) -> None:
        """Build the step bound to the ``synth_product_details`` upstream."""
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [StepInput(step_id=_UPSTREAM_ID)]
        self.outputs: list[Path] = [_OUT_MANIFEST]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION

    def run(self, ctx: StepContext) -> None:
        """Generate the image set for the catalog.

        Raises:
            FileNotFoundError: Any of the upstream cached files is missing.
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

        backend = get_backend(ctx.config.image_backend, ctx=ctx)
        images_per_product = ctx.config.catalog.images_per_product
        images_dir = ctx.out_dir / _OUT_IMAGES_DIR
        images_dir.mkdir(parents=True, exist_ok=True)

        jobs = _build_jobs(
            skeletons=skeletons,
            category_by_handle=category_by_handle,
            images_per_product=images_per_product,
            images_dir=images_dir,
            extension=backend.extension,
            width=_DEFAULT_WIDTH,
            height=_DEFAULT_HEIGHT,
        )

        if isinstance(backend, AsyncImageBackend):
            entries = asyncio.run(
                _run_async(
                    backend=backend,
                    jobs=jobs,
                    concurrency=ctx.config.image_concurrency,
                ),
            )
        else:
            entries = _run_sync(backend=backend, jobs=jobs)

        manifest = _build_manifest(
            backend_name=backend.name,
            extension=backend.extension,
            images_per_product=images_per_product,
            entries=entries,
        )
        out_path = ctx.out_dir / _OUT_MANIFEST
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Job model + dispatch
# --------------------------------------------------------------------------- #


class _Job:
    """One ``(handle, index)`` render request."""

    __slots__ = (
        "category",
        "file_name",
        "file_path",
        "handle",
        "height",
        "index",
        "title",
        "width",
    )

    def __init__(
        self,
        *,
        handle: str,
        index: int,
        title: str,
        category: str,
        file_path: Path,
        file_name: str,
        width: int,
        height: int,
    ) -> None:
        self.handle = handle
        self.index = index
        self.title = title
        self.category = category
        self.file_path = file_path
        self.file_name = file_name
        self.width = width
        self.height = height


def _build_jobs(
    *,
    skeletons: list[ProductSkeleton],
    category_by_handle: dict[str, str],
    images_per_product: int,
    images_dir: Path,
    extension: str,
    width: int,
    height: int,
) -> list[_Job]:
    """Materialize the per-(handle, index) render request list."""
    jobs: list[_Job] = []
    for skeleton in skeletons:
        category = category_by_handle[skeleton.handle]
        for index in range(images_per_product):
            file_name = f"{skeleton.handle}-{index}{extension}"
            jobs.append(
                _Job(
                    handle=skeleton.handle,
                    index=index,
                    title=skeleton.title,
                    category=category,
                    file_path=images_dir / file_name,
                    file_name=file_name,
                    width=width,
                    height=height,
                ),
            )
    return jobs


def _run_sync(*, backend: ImageBackend, jobs: list[_Job]) -> list[dict[str, Any]]:
    """Render every job serially; return per-entry manifest dicts."""
    entries: list[dict[str, Any]] = []
    for job in jobs:
        payload = backend.render(
            handle=job.handle,
            index=job.index,
            title=job.title,
            category=job.category,
            width=job.width,
            height=job.height,
        )
        job.file_path.write_bytes(payload)
        entries.append(_manifest_entry(job=job, cache_hit=False))
    return entries


async def _run_async(
    *,
    backend: AsyncImageBackend,
    jobs: list[_Job],
    concurrency: int,
) -> list[dict[str, Any]]:
    """Render every job through a bounded ``asyncio.Semaphore``."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(job: _Job) -> dict[str, Any]:
        async with sem:
            payload = await backend.render_async(
                handle=job.handle,
                index=job.index,
                title=job.title,
                category=job.category,
                width=job.width,
                height=job.height,
            )
            cache_hit = bool(getattr(backend, "last_render_was_cache_hit", False))
            job.file_path.write_bytes(payload)
            return _manifest_entry(job=job, cache_hit=cache_hit)

    return await asyncio.gather(*(_one(job) for job in jobs))


def _manifest_entry(*, job: _Job, cache_hit: bool) -> dict[str, Any]:
    """Return the per-image manifest entry."""
    return {
        "handle": job.handle,
        "index": job.index,
        "file": f"{_OUT_IMAGES_DIR.as_posix()}/{job.file_name}",
        "width": job.width,
        "height": job.height,
        "cache_hit": cache_hit,
    }


def _build_manifest(
    *,
    backend_name: str,
    extension: str,
    images_per_product: int,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the top-level manifest dict written to disk."""
    sorted_entries = sorted(
        entries,
        key=lambda e: (cast("str", e["handle"]), cast("int", e["index"])),
    )
    cache_hits = sum(1 for e in sorted_entries if e.get("cache_hit"))
    return {
        "backend": backend_name,
        "extension": extension,
        "images_per_product": images_per_product,
        "total_images": len(sorted_entries),
        "cache_hits": cache_hits,
        "cache_misses": len(sorted_entries) - cache_hits,
        "entries": sorted_entries,
    }


# --------------------------------------------------------------------------- #
# Cache loaders (lifted from the legacy single-file images.py)
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
    """Resolve each product handle's category label (lifted from legacy images.py)."""
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


__all__ = ["GenImagesStep", "get_backend"]
