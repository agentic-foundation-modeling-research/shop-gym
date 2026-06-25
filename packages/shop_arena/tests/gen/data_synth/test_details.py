"""Unit tests for :mod:`shop_arena.gen.data_synth.details`.

Covers the T3.7 requirements from
``docs/impl/shop_gen_implementation.md``:

* Happy path: one LLM call per collection (parallel; ≤ 5 concurrent),
  pydantic-validated output cached under
  ``.shop_gen/stage_cache/details/<collection>.json``.
* Retry path: a row that fails validation on the first attempt is
  re-prompted exactly once and accepted on the second attempt.
* Drop-tolerance: per-collection drops below the global 5% budget are
  tolerated; details for accepted skeletons end up in the cache.
* Oversize-rejection failure: a global drop rate above 5% raises
  ``StageSynthError``.
* Vendor allowlist enforcement (spec §5.6: ``Product.vendor`` must be
  drawn from the fake-brand allowlist).
* Plain-descriptive scrubbing on ``description_html`` / ``product_type``
  / ``tags`` (allowlist tokens are forbidden in those fields).
* Variant ↔ option-group consistency.
* Step contract: id, phase, outputs, depends_on, version; runtime
  required; cached upstream files required; manifest written.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from harness.runtimes import LLMCompleter
from shop_arena.gen.config import ShopGenConfig
from shop_arena.gen.data_synth import (
    CollectionDraft,
    ProductDetail,
    ProductSkeleton,
    StageSynthError,
    SynthProductDetailsStep,
)
from shop_arena.gen.data_synth.details import (
    _MAX_REJECTION_RATE,
    _MAX_RETRIES,
    _MAX_SKELETONS_PER_CALL,
    synth_product_details_for_collection,
)
from shop_arena.gen.data_synth.prompts import load_synth_product_details_template
from shop_arena.gen.pipeline import list_steps
from shop_arena.gen.steps.base import StepContext

# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #


_IDENTITY: dict[str, Any] = {
    "name": "AisleArena",
    "descriptor": "minimalist outdoor essentials",
    "tone": ["calm", "earthy"],
    "currency": "USD",
    "country": "US",
}


def _collection(handle: str, *, count: int) -> CollectionDraft:
    return CollectionDraft(
        title=handle.replace("-", " "),
        handle=handle,
        description=f"Plain description of {handle}.",
        sort_order="manual",
        target_product_count=count,
    )


_OUTERWEAR = _collection("outerwear", count=2)
_KITCHEN = _collection("kitchen-tools", count=2)
_COLLECTIONS: tuple[CollectionDraft, ...] = (_OUTERWEAR, _KITCHEN)
_PER_COLLECTION_COUNT: int = 2
_TOTAL_PRODUCTS: int = sum(c.target_product_count for c in _COLLECTIONS)
_BIG_PER_COLLECTION_COUNT: int = 20
_BIG_TOTAL_PRODUCTS: int = 2 * _BIG_PER_COLLECTION_COUNT
_EXPECTED_RETRY_PROMPT_COUNT: int = 2


def _skeleton(handle: str, *, collection: str, price: str = "29.99") -> ProductSkeleton:
    return ProductSkeleton(
        title=handle.replace("-", " "),
        handle=handle,
        price=price,
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


def _detail_dict(
    *,
    handle: str,
    vendor: str = "AisleArena",
    description_html: str = "<p>warm and quiet.</p>",
    product_type: str = "outerwear",
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "handle": handle,
        "description_html": description_html,
        "vendor": vendor,
        "product_type": product_type,
        "tags": tags if tags is not None else ["warm", "winter"],
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
    }
    if extra:
        base.update(extra)
    return base


def _details_response(handles: list[str], **kwargs: Any) -> str:
    return json.dumps([_detail_dict(handle=h, **kwargs) for h in handles])


def _empty_responses() -> dict[str, list[str | RuntimeError]]:
    return {}


def _empty_prompts() -> list[str]:
    return []


@dataclass
class _StubCompleter:
    """Thread-safe :class:`LLMCompleter` returning a dict of canned responses.

    Looks up each prompt by the first collection handle that appears in it,
    so parallel per-collection calls remain deterministic regardless of the
    thread-pool's scheduling order. ``responses[handle]`` may be a list,
    in which case successive calls for that handle pop from the front
    (used to test the retry path).
    """

    responses: dict[str, list[str | RuntimeError]] = field(default_factory=_empty_responses)
    prompts: list[str] = field(default_factory=_empty_prompts)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def complete(self, prompt: str, *, timeout: float) -> str:
        del timeout
        with self._lock:
            self.prompts.append(prompt)
            handle = _route_prompt(prompt, list(self.responses.keys()))
            queue = self.responses.get(handle)
            if not queue:
                raise AssertionError(
                    f"unexpected LLM call for collection={handle!r}; "
                    f"prompts so far={len(self.prompts)}",
                )
            response = queue.pop(0)
            if isinstance(response, RuntimeError):
                raise response
            return response


def _route_prompt(prompt: str, handles: list[str]) -> str:
    """Pick the collection handle present in ``prompt``.

    The prompt embeds the collection draft as a JSON blob; matching on
    ``"handle": "<collection>"`` keeps routing unambiguous even when one
    collection's handle is a substring of another's.
    """
    for handle in handles:
        marker = f'"handle": "{handle}"'
        if marker in prompt:
            return handle
    raise AssertionError(f"prompt does not reference any of {handles!r}")


def _materialise_workspace(
    out_dir: Path,
    *,
    collections: list[CollectionDraft] | None = None,
    skeletons: list[ProductSkeleton] | None = None,
    identity: dict[str, Any] | None = None,
) -> None:
    actual_collections = collections if collections is not None else list(_COLLECTIONS)
    actual_skeletons = skeletons if skeletons is not None else _ALL_SKELETONS
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
        json.dumps(
            [s.model_dump(mode="json") for s in actual_skeletons],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "identity.json").write_text(
        json.dumps(identity if identity is not None else _IDENTITY, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed_a"
    seed.mkdir()
    return seed


# --------------------------------------------------------------------------- #
# Prompt-asserting tests
# --------------------------------------------------------------------------- #


def test_prompt_template_states_vendor_allowlist_rule() -> None:
    body = load_synth_product_details_template()
    assert "fake-brand token drawn from this exact allowlist" in body


def test_prompt_template_forbids_brand_tokens_in_descriptive_fields() -> None:
    body = load_synth_product_details_template()
    assert "plain descriptive" in body.lower()
    assert "{allowlist}" in body


# --------------------------------------------------------------------------- #
# synth_product_details_for_collection
# --------------------------------------------------------------------------- #


def test_synth_details_calls_llm_once_per_collection_happy_path() -> None:
    completer = _StubCompleter(
        responses={
            "outerwear": [
                _details_response(["warm-winter-coat", "waterproof-rain-jacket"]),
            ],
        },
    )
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == 1
    assert dropped == 0
    assert [d.handle for d in details] == ["warm-winter-coat", "waterproof-rain-jacket"]
    assert all(isinstance(d, ProductDetail) for d in details)


def test_synth_details_strips_code_fence() -> None:
    fenced = (
        "```json\n" + _details_response(["warm-winter-coat", "waterproof-rain-jacket"]) + "\n```"
    )
    completer = _StubCompleter(responses={"outerwear": [fenced]})
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert dropped == 0
    assert len(details) == _PER_COLLECTION_COUNT


def test_synth_details_rejects_empty_skeleton_list() -> None:
    completer = _StubCompleter(responses={})
    with pytest.raises(StageSynthError, match="empty skeleton list"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=[],
            completer=cast(LLMCompleter, completer),
        )
    assert completer.prompts == []


def test_synth_details_rejects_empty_response() -> None:
    """Two empty responses (initial + retry) escalate to ``StageSynthError``."""
    completer = _StubCompleter(responses={"outerwear": ["", ""]})
    with pytest.raises(StageSynthError, match="empty response"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            completer=cast(LLMCompleter, completer),
        )
    assert len(completer.prompts) == _MAX_RETRIES + 1


def test_synth_details_rejects_object_response() -> None:
    """Two object responses (initial + retry) escalate to ``StageSynthError``."""
    completer = _StubCompleter(responses={"outerwear": ["{}", "{}"]})
    with pytest.raises(StageSynthError, match="JSON array"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            completer=cast(LLMCompleter, completer),
        )
    assert len(completer.prompts) == _MAX_RETRIES + 1


def test_synth_details_rejects_empty_array() -> None:
    """Two empty arrays (initial + retry) escalate to ``StageSynthError``."""
    completer = _StubCompleter(responses={"outerwear": ["[]", "[]"]})
    with pytest.raises(StageSynthError, match="empty details array"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            completer=cast(LLMCompleter, completer),
        )
    assert len(completer.prompts) == _MAX_RETRIES + 1


def test_synth_details_retry_recovers_validation_failure() -> None:
    """T3.7 retry path: a row failing on attempt 1 is re-prompted once."""
    bad_first = json.dumps(
        [
            # Wrong type for ``tags`` -> ProductDetail validation fails.
            {**_detail_dict(handle="warm-winter-coat"), "tags": "not-a-list"},
            _detail_dict(handle="waterproof-rain-jacket"),
        ],
    )
    good_retry = _details_response(["warm-winter-coat"])
    completer = _StubCompleter(
        responses={"outerwear": [bad_first, good_retry]},
    )
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert _MAX_RETRIES == 1  # contract documented in module
    assert len(completer.prompts) == _EXPECTED_RETRY_PROMPT_COUNT
    assert dropped == 0
    assert [d.handle for d in details] == ["warm-winter-coat", "waterproof-rain-jacket"]


def test_synth_details_drops_after_failed_retry() -> None:
    """A row that fails BOTH attempts is dropped and counted."""
    bad = json.dumps(
        [
            {**_detail_dict(handle="warm-winter-coat"), "tags": "not-a-list"},
            _detail_dict(handle="waterproof-rain-jacket"),
        ],
    )
    bad_retry = json.dumps(
        [{**_detail_dict(handle="warm-winter-coat"), "tags": "still-not-a-list"}],
    )
    completer = _StubCompleter(
        responses={"outerwear": [bad, bad_retry]},
    )
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == _EXPECTED_RETRY_PROMPT_COUNT
    assert dropped == 1
    assert [d.handle for d in details] == ["waterproof-rain-jacket"]


def test_synth_details_rejects_non_allowlist_vendor() -> None:
    """Vendor must be in the fake-brand allowlist (spec §5.6)."""
    bad = json.dumps(
        [
            _detail_dict(handle="warm-winter-coat", vendor="MadeUpBrand"),
            _detail_dict(handle="waterproof-rain-jacket"),
        ],
    )
    bad_retry = json.dumps([_detail_dict(handle="warm-winter-coat", vendor="MadeUpBrand")])
    completer = _StubCompleter(responses={"outerwear": [bad, bad_retry]})
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert dropped == 1
    assert [d.handle for d in details] == ["waterproof-rain-jacket"]


def test_synth_details_rejects_allowlist_token_in_description() -> None:
    """Plain-descriptive fields must be brand-free (spec §5.6)."""
    bad = json.dumps(
        [
            _detail_dict(
                handle="warm-winter-coat",
                description_html="<p>the AisleArena classic.</p>",
            ),
            _detail_dict(handle="waterproof-rain-jacket"),
        ],
    )
    bad_retry = json.dumps(
        [
            _detail_dict(
                handle="warm-winter-coat",
                description_html="<p>the AisleArena classic.</p>",
            ),
        ],
    )
    completer = _StubCompleter(responses={"outerwear": [bad, bad_retry]})
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert dropped == 1
    assert [d.handle for d in details] == ["waterproof-rain-jacket"]


def test_synth_details_rejects_variant_option_mismatch() -> None:
    """Each ``variant.optionN`` must be in ``options[N-1].values``."""
    bad_detail = _detail_dict(handle="warm-winter-coat")
    bad_detail["variants"][0]["option1"] = "Phantom"
    bad = json.dumps([bad_detail, _detail_dict(handle="waterproof-rain-jacket")])
    bad_retry = json.dumps([bad_detail])
    completer = _StubCompleter(responses={"outerwear": [bad, bad_retry]})
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert dropped == 1
    assert [d.handle for d in details] == ["waterproof-rain-jacket"]


def test_synth_details_silently_drops_extra_handles() -> None:
    """Handles outside the requested set are ignored at parse time."""
    payload = json.dumps(
        [
            _detail_dict(handle="warm-winter-coat"),
            _detail_dict(handle="waterproof-rain-jacket"),
            _detail_dict(handle="phantom-product"),
        ],
    )
    completer = _StubCompleter(responses={"outerwear": [payload]})
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert dropped == 0
    assert [d.handle for d in details] == ["warm-winter-coat", "waterproof-rain-jacket"]


def test_synth_details_chunks_when_skeletons_exceed_call_size() -> None:
    """A skeleton list larger than ``_MAX_SKELETONS_PER_CALL`` drives multiple LLM calls.

    Caps total per-call output size so an over-budget collection cannot
    truncate the model's response and fail the whole step.
    """
    chunk_size = _MAX_SKELETONS_PER_CALL
    total = chunk_size + 5  # exactly two chunks: full + partial.
    big_collection = _collection("outerwear", count=total)
    big_skeletons = [_skeleton(f"outerwear-item-{i}", collection="outerwear") for i in range(total)]
    chunk0 = big_skeletons[:chunk_size]
    chunk1 = big_skeletons[chunk_size:]
    completer = _StubCompleter(
        responses={
            "outerwear": [
                json.dumps([_detail_dict(handle=s.handle) for s in chunk0]),
                json.dumps([_detail_dict(handle=s.handle) for s in chunk1]),
            ],
        },
    )
    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=big_collection,
        skeletons=big_skeletons,
        completer=cast(LLMCompleter, completer),
    )
    expected_calls = (total + chunk_size - 1) // chunk_size
    assert len(completer.prompts) == expected_calls
    assert dropped == 0
    assert [d.handle for d in details] == [s.handle for s in big_skeletons]


def test_synth_details_dumps_raw_response_on_parse_failure(tmp_path: Path) -> None:
    """Every-attempt parse failure: each attempt's raw is dumped, then the error propagates."""
    truncated = '[{"handle": "warm-winter-coat", "description_html": "<p>unfinis'
    # Both attempts truncate the same way ⇒ unrecoverable. Each attempt's
    # raw response is persisted with its own ``attempt_<n>`` suffix.
    completer = _StubCompleter(responses={"outerwear": [truncated, truncated]})
    debug_dir = tmp_path / "details"

    with pytest.raises(StageSynthError, match="not valid JSON"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            completer=cast(LLMCompleter, completer),
            debug_dir=debug_dir,
        )

    dumps = sorted(debug_dir.glob("_failed_outerwear_*.txt"))
    assert [d.name for d in dumps] == [
        "_failed_outerwear_chunk_0_attempt_0.txt",
        "_failed_outerwear_chunk_0_attempt_1.txt",
    ]
    for dump in dumps:
        assert dump.read_text(encoding="utf-8") == truncated


def test_synth_details_retry_recovers_from_parse_failure() -> None:
    """A truncated response on attempt 0 + valid JSON on attempt 1 ⇒ success.

    Targets the transient-truncation case that motivated Fix B in
    ``docs/specs/shop_arena/shop_arena.gen.md`` §5.3 ("Schema strictness vs. LLM drift"):
    a single truncated response should not poison the whole step when
    the re-prompt budget is still available.
    """
    truncated = '[{"handle": "warm-winter-coat", "description_html": "<p>unfinis'
    good = _details_response(["warm-winter-coat", "waterproof-rain-jacket"])
    completer = _StubCompleter(responses={"outerwear": [truncated, good]})

    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )
    assert len(completer.prompts) == _MAX_RETRIES + 1
    assert dropped == 0
    assert [d.handle for d in details] == ["warm-winter-coat", "waterproof-rain-jacket"]


def test_synth_details_retry_recovers_from_runtime_failure() -> None:
    """A transient runtime stream failure consumes the same retry budget."""
    good = _details_response(["warm-winter-coat", "waterproof-rain-jacket"])
    completer = _StubCompleter(
        responses={
            "outerwear": [
                RuntimeError(
                    "pi completion failed with exit code 1: stderr: "
                    "OpenAI Responses stream ended before a terminal response event"
                ),
                good,
            ],
        },
    )

    details, dropped = synth_product_details_for_collection(
        identity=_IDENTITY,
        collection=_OUTERWEAR,
        skeletons=_OUTERWEAR_SKELETONS,
        completer=cast(LLMCompleter, completer),
    )

    assert len(completer.prompts) == _MAX_RETRIES + 1
    assert dropped == 0
    assert [d.handle for d in details] == ["warm-winter-coat", "waterproof-rain-jacket"]


def test_synth_details_reraises_runtime_failure_after_retry() -> None:
    """Repeated runtime failures keep the provider diagnostic visible."""
    err = RuntimeError("pi completion failed with exit code 1: stderr: stream ended")
    completer = _StubCompleter(responses={"outerwear": [err, err]})

    with pytest.raises(RuntimeError, match="stream ended"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            completer=cast(LLMCompleter, completer),
        )

    assert len(completer.prompts) == _MAX_RETRIES + 1


def test_synth_details_no_dump_when_debug_dir_unset(tmp_path: Path) -> None:
    """Without ``debug_dir`` the parse error still propagates but no file is written."""
    completer = _StubCompleter(
        responses={"outerwear": ["not even close to json", "still not json"]},
    )
    debug_dir = tmp_path / "details"  # exists but never passed in.
    debug_dir.mkdir()

    with pytest.raises(StageSynthError, match="not valid JSON"):
        synth_product_details_for_collection(
            identity=_IDENTITY,
            collection=_OUTERWEAR,
            skeletons=_OUTERWEAR_SKELETONS,
            completer=cast(LLMCompleter, completer),
        )

    assert list(debug_dir.iterdir()) == []


def test_step_run_dumps_raw_on_chunk_parse_failure(tmp_path: Path) -> None:
    """End-to-end: a truncated chunk response leaves a dump under the details dir.

    Mirrors the production failure mode (model truncation produces
    invalid JSON across the re-prompt budget) and asserts the user gets
    a usable on-disk artefact even when the step fails fast.
    """
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    truncated = '[{"handle": "warm-winter-coat", "description_html": "<p>unfinis'
    completer = _StubCompleter(
        responses={
            # Two truncated responses ⇒ retry exhausted ⇒ step-fatal.
            "outerwear": [truncated, truncated],
            # kitchen-tools may or may not run depending on thread scheduling;
            # keep its queue valid so we don't conflate parse failure with
            # "stub ran dry".
            "kitchen-tools": [_details_response(["ceramic-coffee-mug", "stainless-mixing-bowl"])],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    with pytest.raises(StageSynthError, match="not valid JSON"):
        SynthProductDetailsStep().run(ctx)

    details_dir = out_dir / ".shop_gen" / "stage_cache" / "details"
    dumps = sorted(details_dir.glob("_failed_outerwear_*.txt"))
    assert [d.name for d in dumps] == [
        "_failed_outerwear_chunk_0_attempt_0.txt",
        "_failed_outerwear_chunk_0_attempt_1.txt",
    ]
    for dump in dumps:
        assert dump.read_text(encoding="utf-8") == truncated

# --------------------------------------------------------------------------- #
# SynthProductDetailsStep
# --------------------------------------------------------------------------- #


def test_step_metadata() -> None:
    step = SynthProductDetailsStep()
    assert step.id == "synth_product_details"
    assert step.phase == "data_synth"
    assert step.outputs == [
        Path(".shop_gen") / "stage_cache" / "details" / "_manifest.json",
    ]
    assert step.depends_on == ["synth_product_skeletons"]
    assert step.version == 1


def test_step_run_writes_per_collection_files_and_manifest(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(
        responses={
            "outerwear": [
                _details_response(["warm-winter-coat", "waterproof-rain-jacket"]),
            ],
            "kitchen-tools": [
                _details_response(["ceramic-coffee-mug", "stainless-mixing-bowl"]),
            ],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductDetailsStep()
    step.run(ctx)

    details_dir = out_dir / ".shop_gen" / "stage_cache" / "details"
    outerwear_path = details_dir / "outerwear.json"
    kitchen_path = details_dir / "kitchen-tools.json"
    manifest_path = details_dir / "_manifest.json"

    assert outerwear_path.exists()
    assert kitchen_path.exists()
    assert manifest_path.exists()

    outerwear = json.loads(outerwear_path.read_text(encoding="utf-8"))
    kitchen = json.loads(kitchen_path.read_text(encoding="utf-8"))
    assert [d["handle"] for d in outerwear] == [
        "warm-winter-coat",
        "waterproof-rain-jacket",
    ]
    assert [d["handle"] for d in kitchen] == [
        "ceramic-coffee-mug",
        "stainless-mixing-bowl",
    ]
    for entry in outerwear + kitchen:
        ProductDetail.model_validate(entry)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["total_products"] == _TOTAL_PRODUCTS
    assert manifest["total_dropped"] == 0
    by_handle = {row["handle"]: row for row in manifest["collections"]}
    assert by_handle["outerwear"]["details_count"] == _PER_COLLECTION_COUNT
    assert by_handle["kitchen-tools"]["details_count"] == _PER_COLLECTION_COUNT


def test_step_run_persists_completed_collection_before_failure(tmp_path: Path) -> None:
    """A late collection failure leaves earlier successful collection files on disk."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    completer = _StubCompleter(
        responses={
            "outerwear": [
                _details_response(["warm-winter-coat", "waterproof-rain-jacket"]),
            ],
            "kitchen-tools": [
                RuntimeError("pi completion failed: stream ended"),
                RuntimeError("pi completion failed: stream ended"),
            ],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductDetailsStep()
    with pytest.raises(RuntimeError, match="stream ended"):
        step.run(ctx)

    details_dir = out_dir / ".shop_gen" / "stage_cache" / "details"
    assert (details_dir / "outerwear.json").exists()
    assert not (details_dir / "kitchen-tools.json").exists()
    assert not (details_dir / "_manifest.json").exists()


def test_step_run_reuses_partial_collection_files(tmp_path: Path) -> None:
    """A retry resumes from valid collection files when the manifest is absent."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    details_dir = out_dir / ".shop_gen" / "stage_cache" / "details"
    details_dir.mkdir(parents=True)
    (details_dir / "outerwear.json").write_text(
        _details_response(["warm-winter-coat", "waterproof-rain-jacket"]) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(
        responses={
            "kitchen-tools": [
                _details_response(["ceramic-coffee-mug", "stainless-mixing-bowl"]),
            ],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductDetailsStep()
    step.run(ctx)

    assert len(completer.prompts) == 1
    assert '"handle": "kitchen-tools"' in completer.prompts[0]
    manifest = json.loads((details_dir / "_manifest.json").read_text(encoding="utf-8"))
    by_handle = {row["handle"]: row for row in manifest["collections"]}
    assert by_handle["outerwear"]["details_count"] == _PER_COLLECTION_COUNT
    assert by_handle["kitchen-tools"]["details_count"] == _PER_COLLECTION_COUNT


def test_step_run_regenerates_partial_collection_with_drops(tmp_path: Path) -> None:
    """Partial collection files with missing handles are regenerated."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    details_dir = out_dir / ".shop_gen" / "stage_cache" / "details"
    details_dir.mkdir(parents=True)
    (details_dir / "outerwear.json").write_text(
        _details_response(["warm-winter-coat"]) + "\n",
        encoding="utf-8",
    )
    completer = _StubCompleter(
        responses={
            "outerwear": [
                _details_response(["warm-winter-coat", "waterproof-rain-jacket"]),
            ],
            "kitchen-tools": [
                _details_response(["ceramic-coffee-mug", "stainless-mixing-bowl"]),
            ],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductDetailsStep()
    step.run(ctx)

    assert len(completer.prompts) == 2
    outerwear = json.loads((details_dir / "outerwear.json").read_text(encoding="utf-8"))
    assert [d["handle"] for d in outerwear] == [
        "warm-winter-coat",
        "waterproof-rain-jacket",
    ]


def test_step_run_tolerates_drops_under_budget(tmp_path: Path) -> None:
    """Dropping 1/40 = 2.5% is below the 5% budget."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"

    big_outerwear = _collection("outerwear", count=_BIG_PER_COLLECTION_COUNT)
    big_kitchen = _collection("kitchen-tools", count=_BIG_PER_COLLECTION_COUNT)
    big_collections = [big_outerwear, big_kitchen]

    outerwear_skeletons = [
        _skeleton(f"outerwear-item-{i}", collection="outerwear")
        for i in range(_BIG_PER_COLLECTION_COUNT)
    ]
    kitchen_skeletons = [
        _skeleton(f"kitchen-item-{i}", collection="kitchen-tools")
        for i in range(_BIG_PER_COLLECTION_COUNT)
    ]
    all_skeletons = outerwear_skeletons + kitchen_skeletons
    _materialise_workspace(out_dir, collections=big_collections, skeletons=all_skeletons)
    # With ``_BIG_PER_COLLECTION_COUNT == 20`` and the implementation's
    # ``_MAX_SKELETONS_PER_CALL == 10`` chunk size, each collection is
    # synthesised over two LLM calls. Outerwear's chunk-0 contains the
    # bad row at index 0, which fails on both attempts ⇒ 1 drop. The
    # other three chunks all return clean payloads.
    outerwear_chunk0 = outerwear_skeletons[:_MAX_SKELETONS_PER_CALL]
    outerwear_chunk1 = outerwear_skeletons[_MAX_SKELETONS_PER_CALL:]
    kitchen_chunk0 = kitchen_skeletons[:_MAX_SKELETONS_PER_CALL]
    kitchen_chunk1 = kitchen_skeletons[_MAX_SKELETONS_PER_CALL:]

    outerwear_chunk0_first = [_detail_dict(handle=s.handle) for s in outerwear_chunk0]
    outerwear_chunk0_first[0]["tags"] = "not-a-list"
    outerwear_chunk0_retry = [
        {**_detail_dict(handle=outerwear_chunk0[0].handle), "tags": "still-bad"},
    ]
    outerwear_chunk1_first = [_detail_dict(handle=s.handle) for s in outerwear_chunk1]
    kitchen_chunk0_first = [_detail_dict(handle=s.handle) for s in kitchen_chunk0]
    kitchen_chunk1_first = [_detail_dict(handle=s.handle) for s in kitchen_chunk1]

    completer = _StubCompleter(
        responses={
            "outerwear": [
                json.dumps(outerwear_chunk0_first),
                json.dumps(outerwear_chunk0_retry),
                json.dumps(outerwear_chunk1_first),
            ],
            "kitchen-tools": [
                json.dumps(kitchen_chunk0_first),
                json.dumps(kitchen_chunk1_first),
            ],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductDetailsStep()
    step.run(ctx)

    manifest = json.loads(
        (out_dir / ".shop_gen" / "stage_cache" / "details" / "_manifest.json").read_text(
            encoding="utf-8",
        ),
    )
    assert manifest["total_products"] == _BIG_TOTAL_PRODUCTS
    assert manifest["total_dropped"] == 1
    assert manifest["total_dropped"] / manifest["total_products"] <= _MAX_REJECTION_RATE


def test_step_run_fails_when_rejection_rate_exceeds_5_percent(tmp_path: Path) -> None:
    """T3.7 oversize-rejection failure path."""
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)

    bad_payload = json.dumps(
        [
            {**_detail_dict(handle="warm-winter-coat"), "tags": "broken"},
            {**_detail_dict(handle="waterproof-rain-jacket"), "tags": "broken"},
        ],
    )
    bad_retry = json.dumps(
        [
            {**_detail_dict(handle="warm-winter-coat"), "tags": "broken"},
            {**_detail_dict(handle="waterproof-rain-jacket"), "tags": "broken"},
        ],
    )
    completer = _StubCompleter(
        responses={
            "outerwear": [bad_payload, bad_retry],
            "kitchen-tools": [
                _details_response(["ceramic-coffee-mug", "stainless-mixing-bowl"]),
            ],
        },
    )
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))

    step = SynthProductDetailsStep()
    with pytest.raises(StageSynthError, match=r"rejection rate 2/4 exceeds 5%"):
        step.run(ctx)
    assert not (out_dir / ".shop_gen" / "stage_cache" / "details" / "_manifest.json").exists()


def test_step_run_requires_runtime(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    _materialise_workspace(out_dir)
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=None)
    step = SynthProductDetailsStep()
    with pytest.raises(ValueError, match="LLMCompleter"):
        step.run(ctx)


def test_step_run_missing_identity(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]),
        encoding="utf-8",
    )
    (cache_dir / "skeletons.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in _ALL_SKELETONS]),
        encoding="utf-8",
    )
    completer = _StubCompleter(responses={})
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthProductDetailsStep()
    with pytest.raises(FileNotFoundError, match=r"identity\.json"):
        step.run(ctx)


def test_step_run_missing_collections_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "identity.json").write_text(
        json.dumps(_IDENTITY),
        encoding="utf-8",
    )
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "skeletons.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in _ALL_SKELETONS]),
        encoding="utf-8",
    )
    completer = _StubCompleter(responses={})
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthProductDetailsStep()
    with pytest.raises(FileNotFoundError, match="cached collections"):
        step.run(ctx)


def test_step_run_missing_skeletons_cache(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "identity.json").write_text(json.dumps(_IDENTITY), encoding="utf-8")
    cache_dir = out_dir / ".shop_gen" / "stage_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "collections.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in _COLLECTIONS]),
        encoding="utf-8",
    )
    completer = _StubCompleter(responses={})
    config = ShopGenConfig(seeds=[seed], out_dir=out_dir)
    ctx = StepContext(config=config, out_dir=out_dir, runtime=cast(LLMCompleter, completer))
    step = SynthProductDetailsStep()
    with pytest.raises(FileNotFoundError, match="cached skeletons"):
        step.run(ctx)


def test_step_registered_with_pipeline_appears_in_data_synth_phase() -> None:
    """T3.7 wires ``synth_product_details`` into the Phase 2 phase listing."""
    grouped = list_steps()
    assert "synth_product_details" in grouped["data_synth"]
