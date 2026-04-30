"""Unit tests for :mod:`shop_gen.data_synth.images`.

Covers:

* :class:`PlaceholderBackend` emits well-formed deterministic SVG bytes.
* :class:`OpenAIImageBackend` happy path against a fake ``AsyncOpenAI``
  client, cache hit on re-run, content-policy error fast-fail, retry on
  transient failure, and bounded-concurrency ceiling.
* :class:`GenImagesStep`'s declared step contract.
* The step writes per-product files + sentinel manifest under
  ``.shop_gen/stage_cache/images_manifest.json``.
* Pipeline registration surfaces ``gen_images`` in the data-synth phase.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import pytest
from openai import APIConnectionError, BadRequestError, RateLimitError

from shop_gen.config import CatalogConfig, ShopGenConfig
from shop_gen.data_synth import (
    AsyncImageBackend,
    CollectionDraft,
    GenImagesStep,
    ImageBackend,
    OpenAIImageBackend,
    PlaceholderBackend,
    ProductDetail,
    ProductSkeleton,
    get_backend,
)
from shop_gen.data_synth.images._cache import compute_cache_key
from shop_gen.data_synth.images._prompts import PROMPT_VERSION
from shop_gen.pipeline import list_steps
from shop_gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

# 1×1 transparent PNG — minimum valid PNG payload, used as canned bytes.
_PNG_BYTES: bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII=",
)
_PNG_B64: str = base64.b64encode(_PNG_BYTES).decode("ascii")


def _collection(handle: str, *, count: int) -> CollectionDraft:
    return CollectionDraft(
        title=handle.replace("-", " ").title(),
        handle=handle,
        description=f"Plain description of {handle}.",
        sort_order="manual",
        target_product_count=count,
    )


_OUTERWEAR = _collection("outerwear", count=2)
_KITCHEN = _collection("kitchen-tools", count=2)
_COLLECTIONS: tuple[CollectionDraft, ...] = (_OUTERWEAR, _KITCHEN)


def _skeleton(handle: str, *, collection: str, title: str | None = None) -> ProductSkeleton:
    return ProductSkeleton(
        title=title or handle.replace("-", " "),
        handle=handle,
        price="29.99",
        collection_handle=collection,
    )


_OUTERWEAR_SKELETONS: list[ProductSkeleton] = [
    _skeleton("warm-winter-coat", collection="outerwear"),
    _skeleton("waterproof-rain-jacket", collection="outerwear"),
]
_KITCHEN_SKELETONS: list[ProductSkeleton] = [
    _skeleton("ceramic-coffee-mug", collection="kitchen-tools"),
    _skeleton("stainless-mixing-bowl", collection="kitchen-tools"),
]
_ALL_SKELETONS: list[ProductSkeleton] = _OUTERWEAR_SKELETONS + _KITCHEN_SKELETONS

_DEFAULT_IMAGES: int = 2
_LARGER_IMAGES: int = 3
_EXPECTED_TOTAL_IMAGES: int = len(_ALL_SKELETONS) * _DEFAULT_IMAGES


def _detail(
    handle: str,
    *,
    vendor: str = "AisleArena",
    product_type: str = "outerwear",
) -> ProductDetail:
    return ProductDetail.model_validate(
        {
            "handle": handle,
            "description_html": "<p>warm and quiet.</p>",
            "vendor": vendor,
            "product_type": product_type,
            "tags": ["warm", "winter"],
            "options": [
                {"name": "Size", "position": 1, "values": ["S", "M", "L"]},
            ],
            "variants": [
                {
                    "title": "Small",
                    "sku": f"{handle}-s",
                    "price": "29.99",
                    "compare_at_price": None,
                    "available": True,
                    "option1": "S",
                    "option2": None,
                    "option3": None,
                    "position": 1,
                    "requires_shipping": True,
                },
            ],
        },
    )


_OUTERWEAR_DETAILS: list[ProductDetail] = [
    _detail("warm-winter-coat"),
    _detail("waterproof-rain-jacket"),
]
_KITCHEN_DETAILS: list[ProductDetail] = [
    _detail("ceramic-coffee-mug", product_type="mug"),
    _detail("stainless-mixing-bowl", product_type="bowl"),
]


def _materialise_workspace(
    out_dir: Path,
    *,
    collections: list[CollectionDraft] | None = None,
    skeletons: list[ProductSkeleton] | None = None,
    details_by_collection: dict[str, list[ProductDetail]] | None = None,
) -> None:
    actual_collections = collections if collections is not None else list(_COLLECTIONS)
    actual_skeletons = skeletons if skeletons is not None else _ALL_SKELETONS
    actual_details = (
        details_by_collection
        if details_by_collection is not None
        else {
            "outerwear": _OUTERWEAR_DETAILS,
            "kitchen-tools": _KITCHEN_DETAILS,
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "collections.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in actual_collections],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (cache_dir / "skeletons.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in actual_skeletons], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    details_dir = cache_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, Any]] = []
    for collection in actual_collections:
        details = actual_details.get(collection.handle, [])
        file_name = f"{collection.handle}.json"
        (details_dir / file_name).write_text(
            json.dumps([d.model_dump(mode="json") for d in details], indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        manifest_entries.append(
            {
                "handle": collection.handle,
                "file": file_name,
                "details_count": len(details),
                "dropped_count": 0,
            },
        )
    manifest = {
        "collections": manifest_entries,
        "total_products": sum(len(d) for d in actual_details.values()),
        "total_dropped": 0,
    }
    (details_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# Fake AsyncOpenAI for OpenAIImageBackend tests
# --------------------------------------------------------------------------- #


class _FakeImageData:
    """Mimics ``response.data[0]`` shape with a ``b64_json`` attribute."""

    def __init__(self, b64: str) -> None:
        self.b64_json = b64


class _FakeImagesResponse:
    """Mimics the ``client.images.generate`` response shape."""

    def __init__(self, b64: str) -> None:
        self.data = [_FakeImageData(b64)]


class _FakeImages:
    """Records each ``generate`` call; returns canned PNG bytes by default.

    Test helpers can override behavior by:

    * setting ``self.errors`` to a list of exceptions popped per call,
    * setting ``self.delay`` to introduce per-call await time (for the
      concurrency-ceiling test).
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.errors: list[Exception] = []
        self.delay: float = 0.0
        self.in_flight: int = 0
        self.max_in_flight: int = 0

    async def generate(self, **kwargs: Any) -> _FakeImagesResponse:
        self.calls.append(kwargs)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.errors:
                raise self.errors.pop(0)
            if self.delay > 0:
                await asyncio.sleep(self.delay)
            return _FakeImagesResponse(_PNG_B64)
        finally:
            self.in_flight -= 1


class _FakeAsyncOpenAI:
    def __init__(self) -> None:
        self.images = _FakeImages()


def _fake_response_error(status_code: int, message: str) -> Exception:
    """Build an error matching the openai SDK constructor shape used in v2.x."""
    response = _FakeHttpxResponse(status_code)
    if status_code == 400:  # noqa: PLR2004 — the SDK's content-policy code
        return BadRequestError(message=message, response=response, body=None)  # type: ignore[arg-type]
    if status_code == 429:  # noqa: PLR2004
        return RateLimitError(message=message, response=response, body=None)  # type: ignore[arg-type]
    raise ValueError(f"unsupported test status_code {status_code}")


class _FakeHttpxResponse:
    """Minimal shim — the openai SDK only reads ``status_code`` / ``headers``."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.request = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# PlaceholderBackend
# --------------------------------------------------------------------------- #


def test_placeholder_backend_emits_well_formed_svg() -> None:
    backend = PlaceholderBackend()
    body = backend.render(
        handle="warm-winter-coat",
        index=0,
        title="warm winter coat",
        category="outerwear",
        width=800,
        height=800,
    )
    text = body.decode("utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert "<svg " in text
    assert text.rstrip().endswith("</svg>")
    assert 'width="800"' in text
    assert 'height="800"' in text
    assert 'viewBox="0 0 800 800"' in text
    assert "warm winter coat" in text


def test_placeholder_backend_is_deterministic() -> None:
    backend = PlaceholderBackend()
    args: dict[str, Any] = {
        "handle": "ceramic-coffee-mug",
        "index": 1,
        "title": "ceramic coffee mug",
        "category": "kitchen-tools",
        "width": 800,
        "height": 800,
    }
    assert backend.render(**args) == backend.render(**args)


def test_placeholder_backend_distinct_categories_produce_different_bytes() -> None:
    backend = PlaceholderBackend()
    a = backend.render(
        handle="x",
        index=0,
        title="t",
        category="outerwear",
        width=800,
        height=800,
    )
    b = backend.render(
        handle="x",
        index=0,
        title="t",
        category="kitchen-tools",
        width=800,
        height=800,
    )
    assert a != b


def test_placeholder_backend_rejects_non_positive_dimensions() -> None:
    backend = PlaceholderBackend()
    with pytest.raises(ValueError, match="positive dimensions"):
        backend.render(
            handle="x",
            index=0,
            title="t",
            category="c",
            width=0,
            height=800,
        )


# --------------------------------------------------------------------------- #
# OpenAIImageBackend
# --------------------------------------------------------------------------- #


def test_openai_backend_metadata() -> None:
    backend = OpenAIImageBackend(out_dir=Path("."), client=_fake_client_for_metadata())
    assert backend.name == "openai"
    assert backend.extension == ".png"
    assert backend.model == "gpt-image-1"
    assert backend.size == "1024x1024"


def _fake_client_for_metadata() -> Any:
    """Build a fake client just to satisfy the constructor signature."""
    return _FakeAsyncOpenAI()


def test_openai_backend_render_async_happy_path(tmp_path: Path) -> None:
    fake = _FakeAsyncOpenAI()
    backend = OpenAIImageBackend(out_dir=tmp_path, client=fake)  # type: ignore[arg-type]
    payload = asyncio.run(
        backend.render_async(
            handle="warm-winter-coat",
            index=0,
            title="warm winter coat",
            category="outerwear",
            width=1024,
            height=1024,
        ),
    )
    assert payload == _PNG_BYTES
    assert len(fake.images.calls) == 1
    call = fake.images.calls[0]
    assert call["model"] == "gpt-image-1"
    assert call["size"] == "1024x1024"
    assert "warm winter coat" in call["prompt"]
    assert "outerwear" in call["prompt"]
    # Brand-safety suffix must be present on every render.
    assert "Brand-safety hard constraints" in call["prompt"]
    assert backend.last_render_was_cache_hit is False


def test_openai_backend_render_async_cache_hit_skips_api(tmp_path: Path) -> None:
    fake = _FakeAsyncOpenAI()
    backend = OpenAIImageBackend(out_dir=tmp_path, client=fake)  # type: ignore[arg-type]
    args: dict[str, Any] = {
        "handle": "x",
        "index": 0,
        "title": "t",
        "category": "c",
        "width": 1024,
        "height": 1024,
    }
    first = asyncio.run(backend.render_async(**args))
    second = asyncio.run(backend.render_async(**args))
    assert first == second == _PNG_BYTES
    # Second call must be a cache hit; only one upstream API call.
    assert len(fake.images.calls) == 1
    assert backend.last_render_was_cache_hit is True


def test_openai_backend_cache_key_changes_with_size(tmp_path: Path) -> None:
    """Cache key includes size so two sizes do not collide."""
    fake = _FakeAsyncOpenAI()
    a = OpenAIImageBackend(out_dir=tmp_path, size="1024x1024", client=fake)  # type: ignore[arg-type]
    b = OpenAIImageBackend(out_dir=tmp_path, size="1024x1536", client=fake)  # type: ignore[arg-type]
    args: dict[str, Any] = {
        "handle": "x",
        "index": 0,
        "title": "t",
        "category": "c",
        "width": 1024,
        "height": 1024,
    }
    asyncio.run(a.render_async(**args))
    asyncio.run(b.render_async(**args))
    # Different size → different cache key → two API calls, no hit.
    assert len(fake.images.calls) == 2  # noqa: PLR2004


def test_openai_backend_retries_on_transient_then_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeAsyncOpenAI()
    fake.images.errors = [APIConnectionError(request=None)]  # type: ignore[arg-type]

    async def _no_sleep(_seconds: float) -> None:
        del _seconds

    # Patch the backend module's `asyncio.sleep` so the test runs fast.
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    backend = OpenAIImageBackend(out_dir=tmp_path, client=fake)  # type: ignore[arg-type]
    payload = asyncio.run(
        backend.render_async(
            handle="x",
            index=0,
            title="t",
            category="c",
            width=1024,
            height=1024,
        ),
    )
    assert payload == _PNG_BYTES
    # Original call + 1 retry.
    expected_attempts = 2
    assert len(fake.images.calls) == expected_attempts


def test_openai_backend_does_not_retry_bad_request(tmp_path: Path) -> None:
    fake = _FakeAsyncOpenAI()
    fake.images.errors = [_fake_response_error(400, "content_policy_violation")]
    backend = OpenAIImageBackend(out_dir=tmp_path, client=fake)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="rejected prompt"):
        asyncio.run(
            backend.render_async(
                handle="x",
                index=0,
                title="t",
                category="c",
                width=1024,
                height=1024,
            ),
        )
    # No retry on a deterministic 400.
    assert len(fake.images.calls) == 1


def test_openai_backend_requires_api_key_in_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing without an injected client + no env key fails at first use."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = OpenAIImageBackend(out_dir=tmp_path)
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        asyncio.run(
            backend.render_async(
                handle="x",
                index=0,
                title="t",
                category="c",
                width=1024,
                height=1024,
            ),
        )


# --------------------------------------------------------------------------- #
# Cache key
# --------------------------------------------------------------------------- #


def test_compute_cache_key_is_stable() -> None:
    args: dict[str, Any] = {
        "prompt": "hello",
        "model": "gpt-image-1",
        "size": "1024x1024",
        "quality": "medium",
        "prompt_version": PROMPT_VERSION,
    }
    assert compute_cache_key(**args) == compute_cache_key(**args)


def test_compute_cache_key_changes_with_inputs() -> None:
    base: dict[str, Any] = {
        "prompt": "hello",
        "model": "gpt-image-1",
        "size": "1024x1024",
        "quality": "medium",
        "prompt_version": PROMPT_VERSION,
    }
    other = base | {"size": "1024x1536"}
    assert compute_cache_key(**base) != compute_cache_key(**other)


# --------------------------------------------------------------------------- #
# get_backend
# --------------------------------------------------------------------------- #


def test_get_backend_placeholder_returns_placeholder_backend(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    config = ShopGenConfig(seeds=[seed], out_dir=tmp_path / "out")
    ctx = StepContext(config=config, out_dir=tmp_path / "out", runtime=None)
    backend = get_backend("placeholder", ctx=ctx)
    assert isinstance(backend, PlaceholderBackend)


def test_get_backend_openai_returns_openai_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seed = _make_seed(tmp_path)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=tmp_path / "out",
        image_backend="openai",
    )
    ctx = StepContext(config=config, out_dir=tmp_path / "out", runtime=None)
    backend = get_backend("openai", ctx=ctx)
    assert isinstance(backend, OpenAIImageBackend)


def test_image_backend_protocol_runtime_check() -> None:
    """Both shipped backends satisfy their respective protocols."""
    assert isinstance(PlaceholderBackend(), ImageBackend)
    assert isinstance(OpenAIImageBackend(out_dir=Path(".")), AsyncImageBackend)


# --------------------------------------------------------------------------- #
# GenImagesStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = GenImagesStep()
    assert step.id == "gen_images"
    assert step.phase == "data_synth"
    assert step.outputs == [Path(".shop_gen") / "stage_cache" / "images_manifest.json"]
    assert step.depends_on == ["synth_product_details"]
    expected_step_version = 2
    assert step.version == expected_step_version


def test_step_run_writes_one_svg_per_product_image_slot(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    GenImagesStep().run(ctx)

    images_dir = out_dir / "data" / "images"
    assert images_dir.is_dir()
    files = sorted(p.name for p in images_dir.iterdir())
    expected = sorted(f"{s.handle}-{i}.svg" for s in _ALL_SKELETONS for i in range(_DEFAULT_IMAGES))
    assert files == expected
    for path in images_dir.iterdir():
        body = path.read_text(encoding="utf-8")
        assert body.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
        assert "</svg>" in body


def test_step_run_writes_manifest(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    GenImagesStep().run(ctx)

    manifest_path = out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "placeholder"
    assert manifest["extension"] == ".svg"
    assert manifest["images_per_product"] == _DEFAULT_IMAGES
    assert manifest["total_images"] == _EXPECTED_TOTAL_IMAGES
    assert len(manifest["entries"]) == _EXPECTED_TOTAL_IMAGES
    handles = {entry["handle"] for entry in manifest["entries"]}
    assert handles == {s.handle for s in _ALL_SKELETONS}
    for entry in manifest["entries"]:
        assert entry["file"].startswith("data/images/")
        assert entry["file"].endswith(".svg")
        assert entry["width"] > 0
        assert entry["height"] > 0
        assert entry["cache_hit"] is False
    # Top-level cache counters reflect placeholder = always miss in v0.2 manifest.
    assert manifest["cache_hits"] == 0
    assert manifest["cache_misses"] == _EXPECTED_TOTAL_IMAGES


def test_step_run_uses_configured_images_per_product(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        catalog=CatalogConfig(images_per_product=_LARGER_IMAGES),
    )
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)

    GenImagesStep().run(ctx)

    images_dir = out_dir / "data" / "images"
    assert sum(1 for _ in images_dir.iterdir()) == len(_ALL_SKELETONS) * _LARGER_IMAGES


def test_step_run_is_deterministic_for_placeholder(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)

    def _run() -> tuple[bytes, bytes]:
        ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
        GenImagesStep().run(ctx)
        manifest_bytes = (
            out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json"
        ).read_bytes()
        sample = (out_dir / "data" / "images" / "warm-winter-coat-0.svg").read_bytes()
        return manifest_bytes, sample

    assert _run() == _run()


def test_step_run_openai_backend_uses_async_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``image_backend=openai`` triggers async fan-out + cache + PNG outputs.

    The v0.2 prompt only varies by ``(title, category)``, so every image
    slot of a given product shares one cache key. Running serially gives
    deterministic dedup: ``N`` products → ``N`` upstream calls, with the
    remaining ``(images_per_product - 1) × N`` slots served from cache.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        image_backend="openai",
        image_concurrency=1,  # serial → deterministic cache-dedup ordering
    )

    fake = _FakeAsyncOpenAI()

    def _factory(name: Any, *, ctx: StepContext) -> Any:
        del name
        return OpenAIImageBackend(out_dir=ctx.out_dir, client=fake)  # type: ignore[arg-type]

    from shop_gen.data_synth.images import _step as step_mod

    monkeypatch.setattr(step_mod, "get_backend", _factory)

    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    GenImagesStep().run(ctx)

    images_dir = out_dir / "data" / "images"
    files = sorted(p.name for p in images_dir.iterdir())
    expected = sorted(f"{s.handle}-{i}.png" for s in _ALL_SKELETONS for i in range(_DEFAULT_IMAGES))
    assert files == expected
    for path in images_dir.iterdir():
        assert path.read_bytes() == _PNG_BYTES

    manifest = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest["backend"] == "openai"
    assert manifest["extension"] == ".png"
    n_products = len(_ALL_SKELETONS)
    expected_misses = n_products
    expected_hits = _EXPECTED_TOTAL_IMAGES - n_products
    assert manifest["cache_misses"] == expected_misses
    assert manifest["cache_hits"] == expected_hits
    assert len(fake.images.calls) == expected_misses


def test_step_run_openai_backend_concurrency_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    cap = 3
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        image_backend="openai",
        image_concurrency=cap,
    )
    fake = _FakeAsyncOpenAI()
    fake.images.delay = 0.05

    def _factory(name: Any, *, ctx: StepContext) -> Any:
        del name
        return OpenAIImageBackend(out_dir=ctx.out_dir, client=fake)  # type: ignore[arg-type]

    from shop_gen.data_synth.images import _step as step_mod

    monkeypatch.setattr(step_mod, "get_backend", _factory)

    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    GenImagesStep().run(ctx)

    assert fake.images.max_in_flight <= cap
    # Sanity: 8 jobs vs. cap=3 with a 50ms per-call delay should saturate
    # the semaphore (under cooperative scheduling, ≥2 in-flight at peak).
    assert fake.images.max_in_flight >= 2  # noqa: PLR2004


def test_step_run_openai_backend_second_run_is_all_cache_hits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(
        seeds=[seed],
        out_dir=out_dir,
        image_backend="openai",
        image_concurrency=1,  # serial → deterministic dedup
    )
    fake = _FakeAsyncOpenAI()

    def _factory(name: Any, *, ctx: StepContext) -> Any:
        del name
        return OpenAIImageBackend(out_dir=ctx.out_dir, client=fake)  # type: ignore[arg-type]

    from shop_gen.data_synth.images import _step as step_mod

    monkeypatch.setattr(step_mod, "get_backend", _factory)

    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    GenImagesStep().run(ctx)
    first_call_count = len(fake.images.calls)
    # First run: one upstream call per unique cache key (= one per product).
    assert first_call_count == len(_ALL_SKELETONS)

    GenImagesStep().run(ctx)
    # Second run: every entry hits the cache, so no new API calls.
    assert len(fake.images.calls) == first_call_count

    manifest = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "images_manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest["cache_hits"] == _EXPECTED_TOTAL_IMAGES
    assert manifest["cache_misses"] == 0
    for entry in manifest["entries"]:
        assert entry["cache_hit"] is True


def test_step_run_missing_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="cached collections"):
        GenImagesStep().run(ctx)


def test_step_run_missing_skeletons_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]) + "\n",
        encoding="utf-8",
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="cached skeletons"):
        GenImagesStep().run(ctx)


def test_step_run_missing_details_manifest(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]) + "\n",
        encoding="utf-8",
    )
    (cache_dir / "skeletons.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in _ALL_SKELETONS]) + "\n",
        encoding="utf-8",
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    with pytest.raises(FileNotFoundError, match="details manifest"):
        GenImagesStep().run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    grouped = list_steps()
    assert "gen_images" in grouped["data_synth"]
