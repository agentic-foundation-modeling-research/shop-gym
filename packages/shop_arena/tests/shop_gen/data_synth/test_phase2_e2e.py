"""End-to-end Phase 2 tests for the data-synthesis sub-DAG.

Covers the T3.13 requirements from
``docs/impl/shop_gen_implementation.md``:

* Drive the full Phase 2 sub-DAG end-to-end against a single-seed
  fixture, exercising every step from ``synth_identity`` through the
  terminal ``assemble_data``.
* A stub :class:`~harness.runtimes.LLMCompleter` produces canned
  responses for every LLM call (one per single-call step plus one per
  collection for the per-collection details / alt-text fan-outs).
* :class:`shop_gen.data_synth.assemble.AssembleDataStep` emits a
  complete ``data/`` directory whose six published files round-trip
  through the closed pydantic mirrors from
  :mod:`shop_gen.data_synth.schema` (SC1).

Phase 1 is collapsed to the single-seed shortcut
(:class:`shop_gen.manual_merge.copy_seed.CopySeedManualStep`) so the
test does not exercise the multi-seed merge LLM path — that is the
T2.7 territory exercised by ``test_phase1_e2e``. The sub-DAG under
test here is the Phase 2 fan-out, not the Phase 1 merge.

The pipeline-level :func:`shop_gen.pipeline.run` does not currently
plumb a runtime through ``StepContext``; we therefore drive the same
registered DAG via :func:`shop_gen.steps.runner.run_pipeline` directly,
injecting the stub completer through ``StepContext.runtime`` (the
same pattern the multi-seed Phase 1 test uses).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from harness.runtimes import LLMCompleter
from shop_gen import pipeline
from shop_gen.config import CatalogConfig, ShopGenConfig
from shop_gen.data_synth import (
    Collection,
    Identity,
    Navigation,
    Page,
    Policy,
    Product,
    Store,
)
from shop_gen.steps.base import StepContext, StepStatus
from shop_gen.steps.runner import run_pipeline
from shop_gen.steps.state import read_state

# --------------------------------------------------------------------------- #
# Fixture: single seed manual that the ``copy_seed_manual`` step will pass
# through verbatim into ``<out_dir>/manual/`` for the Phase 2 sub-DAG to read.
# --------------------------------------------------------------------------- #

_SEED_DESCRIPTOR = "boutique outdoor storefront"

_SEED_CAPABILITIES: dict[str, Any] = {
    "version": "0.1",
    "shop": {
        "descriptor": _SEED_DESCRIPTOR,
        "category": "outdoor",
        "currency": "USD",
        "tone": ["rugged", "warm"],
    },
    "site_shell": {
        "nav_depth": 1,
        "header_style": "transparent",
        "has_announcement_bar": True,
    },
    "homepage": {
        "section_types": ["hero", "grid"],
        "section_count": 4,
    },
    "collection": {
        "layout": "grid",
        "filters": ["availability", "price"],
        "sort": ["best-selling"],
    },
    "product": {
        "variant_selectors": ["size"],
        "has_reviews": True,
    },
    "cart": {"has_promo_input": True},
    "info_pages_present": ["about", "contact"],
}

# ``stats.collections_total = 3`` drives ``resolve_target_count`` to
# the floor of the [3, 30] clamp (spec §5.3 default 10, but the test
# stays at the minimum to keep the canned LLM response set small).
_SEED_STATS: dict[str, Any] = {
    "products_total": 6,
    "collections_total": 3,
    "products_per_collection": {"avg": 2.0, "median": 2.0, "max": 2},
    "price": {
        "min": 9.99,
        "max": 39.99,
        "median": 19.99,
        "currency": "USD",
    },
    "products_with_variants_pct": 1.0,
    "variant_axes_observed": ["size"],
    "navigation_depth_max": 1,
    "homepage_section_count": 4,
    "info_pages_count": 2,
    "feature_count": 8,
}

_SEED_MANUAL_BODY = (
    "# Shop Manual — boutique outdoor storefront\n\n"
    "## Overview\n\n"
    "Focused outdoor storefront for hikers and campers.\n"
)

# --------------------------------------------------------------------------- #
# Canned LLM responses
# --------------------------------------------------------------------------- #

_VENDOR = "AisleArena"  # member of the in-repo fake-brand allowlist.

_IDENTITY_RESPONSE: str = json.dumps(
    {
        "descriptor": _SEED_DESCRIPTOR,
        "tone": ["rugged", "warm"],
        "currency": "USD",
        "country": "US",
    },
)

_STORE_RESPONSE: str = json.dumps(
    {
        "domain": "fakeshop.example",
        "description": "outdoor essentials for short trips.",
        "payment_settings": {"accepted_card_brands": ["VISA", "MASTER"]},
        "brand": {
            "logo_url": None,
            "colors": {"primary": "#1f6f43", "secondary": "#f3e9d2"},
        },
    },
)

_PAGES_RESPONSE: str = json.dumps(
    [
        {
            "handle": "about",
            "title": "About us",
            "body_html": "<p>plain about page.</p>",
        },
        {
            "handle": "contact",
            "title": "Contact",
            "body_html": "<p>plain contact page.</p>",
        },
    ],
)

_POLICIES_RESPONSE: str = json.dumps(
    [
        {
            "handle": "privacy-policy",
            "title": "Privacy",
            "body_html": "<p>plain privacy.</p>",
        },
        {
            "handle": "shipping-policy",
            "title": "Shipping",
            "body_html": "<p>plain shipping.</p>",
        },
        {
            "handle": "terms-of-service",
            "title": "Terms",
            "body_html": "<p>plain terms.</p>",
        },
        {
            "handle": "refund-policy",
            "title": "Refunds",
            "body_html": "<p>plain refunds.</p>",
        },
    ],
)

_COLLECTION_HANDLES: tuple[str, ...] = ("outerwear", "kitchen-tools", "bath-essentials")
_PRODUCTS_PER_COLLECTION: int = 2
_TOTAL_PRODUCTS: int = len(_COLLECTION_HANDLES) * _PRODUCTS_PER_COLLECTION

_COLLECTIONS_RESPONSE: str = json.dumps(
    [
        {
            "title": "outerwear",
            "handle": "outerwear",
            "description": "outdoor coats and shells.",
            "sort_order": "manual",
            "target_product_count": 2,
        },
        {
            "title": "kitchen tools",
            "handle": "kitchen-tools",
            "description": "kitchen items and helpers.",
            "sort_order": "manual",
            "target_product_count": 2,
        },
        {
            "title": "bath essentials",
            "handle": "bath-essentials",
            "description": "bath items and helpers.",
            "sort_order": "manual",
            "target_product_count": 2,
        },
    ],
)

_SKELETONS_BY_COLLECTION: dict[str, list[dict[str, str]]] = {
    "outerwear": [
        {
            "title": "warm winter coat",
            "handle": "warm-winter-coat",
            "price": "29.99",
            "collection_handle": "outerwear",
        },
        {
            "title": "waterproof rain jacket",
            "handle": "waterproof-rain-jacket",
            "price": "39.99",
            "collection_handle": "outerwear",
        },
    ],
    "kitchen-tools": [
        {
            "title": "ceramic coffee mug",
            "handle": "ceramic-coffee-mug",
            "price": "9.99",
            "collection_handle": "kitchen-tools",
        },
        {
            "title": "stainless mixing bowl",
            "handle": "stainless-mixing-bowl",
            "price": "14.99",
            "collection_handle": "kitchen-tools",
        },
    ],
    "bath-essentials": [
        {
            "title": "soft cotton towel",
            "handle": "soft-cotton-towel",
            "price": "19.99",
            "collection_handle": "bath-essentials",
        },
        {
            "title": "natural bristle brush",
            "handle": "natural-bristle-brush",
            "price": "12.99",
            "collection_handle": "bath-essentials",
        },
    ],
}

_SKELETONS_RESPONSE: str = json.dumps(
    [s for handle in _COLLECTION_HANDLES for s in _SKELETONS_BY_COLLECTION[handle]],
)


def _detail(handle: str, *, product_type: str) -> dict[str, Any]:
    """Build one ``ProductDetail``-shaped dict for the per-collection response.

    Vendor is drawn from the in-repo fake-brand allowlist; every other
    text field is plain-descriptive so the post-validation allowlist
    sweep accepts the row.
    """
    return {
        "handle": handle,
        "description_html": "<p>warm and quiet.</p>",
        "vendor": _VENDOR,
        "product_type": product_type,
        "tags": ["warm", "winter"],
        "options": [
            {"name": "Size", "position": 1, "values": ["S", "M"]},
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
            {
                "title": "Medium",
                "sku": f"{handle}-m",
                "price": "29.99",
                "compare_at_price": None,
                "available": True,
                "option1": "M",
                "option2": None,
                "option3": None,
                "position": 2,
                "requires_shipping": True,
            },
        ],
    }


_PRODUCT_TYPE_BY_COLLECTION: dict[str, str] = {
    "outerwear": "outerwear",
    "kitchen-tools": "mug",
    "bath-essentials": "bath",
}

_DETAILS_RESPONSE_BY_COLLECTION: dict[str, str] = {
    handle: json.dumps(
        [
            _detail(s["handle"], product_type=_PRODUCT_TYPE_BY_COLLECTION[handle])
            for s in _SKELETONS_BY_COLLECTION[handle]
        ],
    )
    for handle in _COLLECTION_HANDLES
}


def _alt_for(handle: str) -> list[str]:
    base = handle.replace("-", " ")
    return [
        f"front view of the {base} on a wooden bench",
        f"close up detail of the {base} stitching",
    ]


_ALT_TEXT_RESPONSE_BY_COLLECTION: dict[str, str] = {
    handle: json.dumps({s["handle"]: _alt_for(s["handle"]) for s in skeletons})
    for handle, skeletons in _SKELETONS_BY_COLLECTION.items()
}

_NAVIGATION_RESPONSE: str = json.dumps(
    {
        "main-menu": [
            {
                "title": "Outerwear",
                "url": "/collections/outerwear",
                "type": "COLLECTION",
                "children": [],
            },
            {
                "title": "Kitchen tools",
                "url": "/collections/kitchen-tools",
                "type": "COLLECTION",
                "children": [],
            },
            {
                "title": "Bath essentials",
                "url": "/collections/bath-essentials",
                "type": "COLLECTION",
                "children": [],
            },
        ],
        "footer": [
            {
                "title": "About",
                "url": "/pages/about",
                "type": "PAGE",
                "children": [],
            },
        ],
    },
)

# --------------------------------------------------------------------------- #
# Stub LLM completer
# --------------------------------------------------------------------------- #

# Each Phase 2 prompt opens with a unique, step-specific sentence (see the
# ``synth_*.md`` prompt files); the markers below are byte-for-byte slices
# of those sentences, so routing by substring is unambiguous regardless of
# the prompt body's downstream JSON-formatted context.
_PROMPT_MARKERS: dict[str, str] = {
    "synth_identity": "synthesizing the brand identity",
    "synth_store": "drafting the ``store.json``",
    "synth_pages": "drafting the storefront's content pages",
    "synth_policies": "drafting the storefront's policy pages",
    "synth_collections": "drafting the storefront's collections",
    "synth_product_skeletons": "drafting the storefront's product catalog skeleton",
    "synth_product_details": "filling in the rich product details for one collection",
    "synth_alt_text": "authoring image alt-text for one collection",
    "synth_navigation": "drafting the storefront's navigation menus",
}


@dataclass
class _StubCompleter:
    """Thread-safe :class:`LLMCompleter` returning canned responses per step.

    Routes by the unique opening-sentence marker each Phase 2 prompt
    template carries; per-collection steps (``synth_product_details`` and
    ``synth_alt_text``) further route by the embedded collection handle so
    the parallel ``ThreadPoolExecutor`` calls remain deterministic
    regardless of scheduling order.
    """

    single_responses: dict[str, str] = field(default_factory=dict)
    per_collection_responses: dict[str, dict[str, str]] = field(default_factory=dict)
    prompts: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        with self._lock:
            self.prompts.append(prompt)
            for step_id, marker in _PROMPT_MARKERS.items():
                if marker not in prompt:
                    continue
                if step_id in self.single_responses:
                    return self.single_responses[step_id]
                if step_id in self.per_collection_responses:
                    bucket = self.per_collection_responses[step_id]
                    handle = _route_collection_prompt(prompt, list(bucket.keys()))
                    return bucket[handle]
                raise AssertionError(
                    f"no canned response registered for step={step_id!r}",
                )
        raise AssertionError(
            "prompt does not match any known Phase 2 step marker; first 200 chars: " + prompt[:200],
        )


def _route_collection_prompt(prompt: str, handles: list[str]) -> str:
    """Pick the collection handle the prompt is about.

    Per-collection steps embed the collection's JSON in the prompt; the
    handle key appears exactly once as ``"handle": "<value>"``.
    """
    for handle in handles:
        if f'"handle": "{handle}"' in prompt:
            return handle
    raise AssertionError(
        f"prompt does not reference any of {handles!r}; first 200 chars: {prompt[:200]}",
    )


def _build_completer() -> _StubCompleter:
    return _StubCompleter(
        single_responses={
            "synth_identity": _IDENTITY_RESPONSE,
            "synth_store": _STORE_RESPONSE,
            "synth_pages": _PAGES_RESPONSE,
            "synth_policies": _POLICIES_RESPONSE,
            "synth_collections": _COLLECTIONS_RESPONSE,
            "synth_product_skeletons": _SKELETONS_RESPONSE,
            "synth_navigation": _NAVIGATION_RESPONSE,
        },
        per_collection_responses={
            "synth_product_details": dict(_DETAILS_RESPONSE_BY_COLLECTION),
            "synth_alt_text": dict(_ALT_TEXT_RESPONSE_BY_COLLECTION),
        },
    )


# --------------------------------------------------------------------------- #
# Workspace helpers
# --------------------------------------------------------------------------- #


def _write_seed(seed_dir: Path) -> Path:
    """Materialise the single seed under the canonical ``<seed>/artifact/`` layout."""
    artifact = seed_dir / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "capabilities.json").write_text(
        json.dumps(_SEED_CAPABILITIES),
        encoding="utf-8",
    )
    (artifact / "manual.md").write_text(_SEED_MANUAL_BODY, encoding="utf-8")
    (artifact / "stats.json").write_text(json.dumps(_SEED_STATS), encoding="utf-8")
    return seed_dir


def _make_config(seed_dir: Path, out_dir: Path) -> ShopGenConfig:
    """Build the test config: 3 collections x 2 products x 2 images each."""
    return ShopGenConfig(
        seeds=(seed_dir,),
        out_dir=out_dir,
        catalog=CatalogConfig(
            collections=3,
            products_per_collection=2,
            images_per_product=2,
        ),
    )


# --------------------------------------------------------------------------- #
# End-to-end test
# --------------------------------------------------------------------------- #

_EXPECTED_STEP_IDS: frozenset[str] = frozenset(
    {
        "copy_seed_manual",
        "synth_identity",
        "synth_store",
        "synth_pages",
        "synth_policies",
        "synth_collections",
        "synth_product_skeletons",
        "synth_product_details",
        "synth_alt_text",
        "gen_images",
        "synth_navigation",
        "assemble_data",
        # Phase 3 ``validate_schema`` (T4.1) sits at the same registry
        # level and is config-independent, so it runs as part of the
        # full pipeline once Phase 2 emits a valid ``data/`` tree.
        "validate_schema",
    },
)

# Single-call steps + per-collection fan-outs (details + alt-text).
_SINGLE_CALL_STEPS: int = 7
_PER_COLLECTION_STEPS: int = 2


def _assert_all_steps_fresh(out_dir: Path) -> None:
    """Assert every Phase 1 + Phase 2 step recorded :data:`StepStatus.FRESH`."""
    state = read_state(out_dir)
    for step_id in _EXPECTED_STEP_IDS:
        record = state.steps.get(step_id)
        assert record is not None, f"{step_id!r} not recorded in state.json"
        assert record.status is StepStatus.FRESH, f"{step_id!r} expected FRESH, got {record.status}"
        assert record.fingerprint is not None


def _assert_data_files_present(data_dir: Path) -> None:
    """Assert the six published ``data/*.json`` files exist."""
    expected = {
        "store.json",
        "products.json",
        "collections.json",
        "pages.json",
        "policies.json",
        "navigation.json",
    }
    for name in expected:
        assert (data_dir / name).exists(), f"missing data/{name}"


def _assert_data_round_trips_through_schema(
    data_dir: Path,
    *,
    identity: Identity,
    config: ShopGenConfig,
) -> None:
    """Assert ``data/*.json`` validates against the closed pydantic mirrors."""
    store = Store.model_validate_json(
        (data_dir / "store.json").read_text(encoding="utf-8"),
    )
    assert store.name == identity.name
    assert store.currency_code == "USD"
    assert store.country_code == "US"

    products_raw = json.loads((data_dir / "products.json").read_text(encoding="utf-8"))
    products = [Product.model_validate(p) for p in products_raw]
    assert len(products) == _TOTAL_PRODUCTS
    # Only allowlisted brand tokens survive the scrub: store.name + vendor.
    assert {p.vendor for p in products} == {_VENDOR}
    for product in products:
        assert len(product.images) == config.catalog.images_per_product
        assert all(img.alt for img in product.images)

    collections_raw = json.loads((data_dir / "collections.json").read_text(encoding="utf-8"))
    collections = [Collection.model_validate(c) for c in collections_raw]
    assert {c.handle for c in collections} == set(_COLLECTION_HANDLES)
    handles_by_collection = {c.handle: c.product_handles for c in collections}
    for handle in _COLLECTION_HANDLES:
        members = handles_by_collection[handle]
        assert len(members) == _PRODUCTS_PER_COLLECTION
        assert set(members) == {s["handle"] for s in _SKELETONS_BY_COLLECTION[handle]}

    pages_raw = json.loads((data_dir / "pages.json").read_text(encoding="utf-8"))
    pages = [Page.model_validate(p) for p in pages_raw]
    assert {p.handle for p in pages} == {"about", "contact"}

    policies_raw = json.loads((data_dir / "policies.json").read_text(encoding="utf-8"))
    policies = [Policy.model_validate(p) for p in policies_raw]
    assert {p.handle for p in policies} == {
        "privacy-policy",
        "shipping-policy",
        "terms-of-service",
        "refund-policy",
    }

    nav_raw = json.loads((data_dir / "navigation.json").read_text(encoding="utf-8"))
    navigation = Navigation.model_validate(nav_raw)
    main_menu = navigation.root["main-menu"]
    main_menu_collection_urls = {item.url for item in main_menu if item.type == "COLLECTION"}
    for handle in _COLLECTION_HANDLES:
        assert f"/collections/{handle}" in main_menu_collection_urls

    # One placeholder SVG per (product, image_index) pair (T3.10).
    images_dir = data_dir / "images"
    image_files = list(images_dir.glob("*.svg"))
    expected_image_count = len(products) * config.catalog.images_per_product
    assert len(image_files) == expected_image_count


def test_phase2_single_seed_end_to_end(tmp_path: Path) -> None:
    """Drive the full single-seed Phase 1 + Phase 2 sub-DAG with a stub LLM.

    The single-seed branch collapses Phase 1 to ``copy_seed_manual``
    (no LLM), then the Phase 2 fan-out runs every synthesis step in
    topological order. The terminal :class:`AssembleDataStep` reads
    every cached payload and emits the six final ``data/*.json`` files.

    Asserts:

    * Every Phase 1 + Phase 2 step recorded :data:`StepStatus.FRESH` in
      ``state.json`` (no failures, no skipped staleness).
    * The published ``data/*.json`` files exist and round-trip through
      the closed pydantic mirrors from
      :mod:`shop_gen.data_synth.schema` (SC1).
    * The catalog scale matches the canned fixture
      (3 collections, 6 products, 12 images).
    * Number of LLM calls matches the spec §5.3 fan-out:
      one per single-call step plus one per collection for the two
      per-collection steps (1 + 1 + 1 + 1 + 1 + 1 + 3 + 3 + 1 = 13).
    * The brand-leak scrub is silent: ``data/`` carries only allowlisted
      brand tokens (the deterministic ``store.name`` + ``Product.vendor``
      values).
    """
    seed = _write_seed(tmp_path / "seed_a")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config = _make_config(seed, out_dir)

    completer = _build_completer()
    ctx = StepContext(
        config=config,
        out_dir=out_dir,
        runtime=cast(LLMCompleter, completer),
    )

    # The pipeline's public ``run()`` entrypoint does not currently
    # plumb a runtime through ``StepContext``; drive the same registered
    # DAG via ``run_pipeline`` directly so the stub completer reaches
    # every Phase 2 step. ``validate_hosting`` (T4.2) boots
    # ``shop-backend`` against the synthesized data and is exercised in
    # its own integration test (tests/shop_gen/data_validation/
    # test_hosting_check.py); the build env-setup steps (T5.1) operate
    # against the vendored Hydrogen template and are exercised in
    # their own unit tests (tests/shop_gen/build/test_env.py). Skip
    # them all here so this Phase 2 e2e stays hermetic and free of
    # subprocess plumbing.
    registry = pipeline._build_registry(config)
    skip_ids = {"validate_hosting", "clone_template", "write_env_file"}
    phase2_steps = [step for step in registry.all() if step.id not in skip_ids]
    result = run_pipeline(phase2_steps, ctx)

    assert set(result.ran) == set(_EXPECTED_STEP_IDS)
    assert result.skipped == ()
    _assert_all_steps_fresh(out_dir)

    # LLM call count matches the spec §5.3 fan-out.
    expected_calls = _SINGLE_CALL_STEPS + _PER_COLLECTION_STEPS * len(_COLLECTION_HANDLES)
    assert len(completer.prompts) == expected_calls

    identity = Identity.model_validate_json(
        (out_dir / "identity.json").read_text(encoding="utf-8"),
    )
    assert identity.descriptor == _SEED_DESCRIPTOR
    assert identity.currency == "USD"
    assert identity.country == "US"

    data_dir = out_dir / "data"
    _assert_data_files_present(data_dir)
    _assert_data_round_trips_through_schema(
        data_dir,
        identity=identity,
        config=config,
    )
