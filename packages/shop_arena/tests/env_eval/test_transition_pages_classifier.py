"""Unit tests for :mod:`shop_arena.env_eval.transition.pages_classifier`.

The classifier owns the lazy per-level batched LLM call that decides which
discovered ``/pages/<slug>`` URLs collapse to ``/pages/<*>``. Coverage here
pins the closed contract:

* an empty input set short-circuits without invoking the LLM,
* a non-empty input set issues exactly one batched ``call_text`` request
  whose prompt names every input path and the storefront base URL,
* malformed responses (missing ``entries``, unknown enum value, missing
  input path) raise :class:`PagesClassifierError` instead of silently
  degrading,
* :func:`collapse_set_from` picks only the configured collapse labels,
* :func:`stub_classification` produces a no-LLM document with every
  entry labelled ``"unknown"``,
* :func:`merge_classifications` is idempotent for already-seen paths and
  appends fresh entries in input order,
* the on-disk artifact is byte-stable JSON (two-space indent + trailing
  newline) and round-trips cleanly through the reader.

A hand-rolled fake :class:`LLMVisionClient` (model id property +
``call`` / ``call_text`` methods) keeps the tests hermetic; provider
routing is exercised in :mod:`test_llm`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shop_arena.env_eval.errors import PagesClassifierError
from shop_arena.env_eval.transition.pages_classifier import (
    COLLAPSE_LABELS,
    PAGES_CLASSIFICATION_FILENAME,
    PAGES_CLASSIFIER_VERSION,
    PageEntry,
    PagesClassification,
    classify_pages,
    collapse_set_from,
    merge_classifications,
    read_pages_classification,
    stub_classification,
    write_pages_classification,
)
from shop_arena.util._llm import VisionResponse

BASE_URL: str = "https://shop.example.com/"


# ---------------------------------------------------------------------------
# Test fake
# ---------------------------------------------------------------------------


@dataclass
class _FakeLLMClient:
    """Records ``call_text`` arguments and returns a canned response.

    Satisfies :class:`shop_arena.util._llm.LLMVisionClient` structurally:
    a ``model`` attribute plus the two call methods. The vision ``call``
    is included so ``isinstance`` Protocol checks succeed; the classifier
    only ever invokes ``call_text``.
    """

    model: str = "gpt-5"
    response: VisionResponse = field(
        default_factory=lambda: VisionResponse(parsed=None, raw_response=""),
    )
    text_calls: list[dict[str, Any]] = field(default_factory=list)
    image_calls: list[dict[str, Any]] = field(default_factory=list)

    def call(
        self,
        *,
        prompt: str,
        images: Sequence[bytes],
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        self.image_calls.append(
            {
                "prompt": prompt,
                "images": tuple(images),
                "schema": schema,
                "temperature": temperature,
            },
        )
        return self.response

    def call_text(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        temperature: float = 0.0,
    ) -> VisionResponse:
        self.text_calls.append(
            {
                "prompt": prompt,
                "schema": schema,
                "temperature": temperature,
            },
        )
        return self.response


def _ok_response(entries: list[dict[str, str]]) -> VisionResponse:
    """Build a successful :class:`VisionResponse` carrying the given entries."""
    payload = {"entries": entries}
    return VisionResponse(parsed=payload, raw_response=json.dumps(payload, sort_keys=True))


# ---------------------------------------------------------------------------
# classify_pages
# ---------------------------------------------------------------------------


def test_classify_pages_empty_input_skips_llm() -> None:
    """Empty input returns an empty doc without invoking the model."""
    client = _FakeLLMClient()
    doc = classify_pages([], base_url=BASE_URL, model="gpt-5", llm=client)

    assert doc == PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model="gpt-5",
        entries=[],
    )
    assert client.text_calls == []
    assert client.image_calls == []


def test_classify_pages_batches_into_one_call() -> None:
    """N paths produce exactly one ``call_text`` request mentioning every path."""
    paths = ["warranty", "about-us", "gift-bundle/coming-home-set"]
    response = _ok_response(
        [
            {"path": "warranty", "label": "support", "reason": "warranty info."},
            {"path": "about-us", "label": "about", "reason": "company narrative."},
            {
                "path": "gift-bundle/coming-home-set",
                "label": "marketing",
                "reason": "campaign bundle.",
            },
        ],
    )
    client = _FakeLLMClient(response=response)

    doc = classify_pages(paths, base_url=BASE_URL, model="gpt-5", llm=client)

    assert doc.classifier_version == PAGES_CLASSIFIER_VERSION
    assert doc.model == "gpt-5"
    assert [e.path for e in doc.entries] == paths
    assert [e.label for e in doc.entries] == ["support", "about", "marketing"]

    assert len(client.text_calls) == 1
    call = client.text_calls[0]
    prompt = call["prompt"]
    for path in paths:
        assert f'"{path}"' in prompt
    assert BASE_URL in prompt
    # The schema is the closed-enum response shape, not the rubric schema.
    assert call["schema"]["required"] == ["entries"]
    assert call["schema"]["additionalProperties"] is False


def test_classify_pages_validates_schema() -> None:
    """A response missing ``entries`` raises :class:`PagesClassifierError`."""
    client = _FakeLLMClient(
        response=VisionResponse(parsed={"items": []}, raw_response="{}"),
    )
    with pytest.raises(PagesClassifierError, match="schema validation"):
        classify_pages(["warranty"], base_url=BASE_URL, model="gpt-5", llm=client)


def test_classify_pages_rejects_unknown_label() -> None:
    """A label outside the closed enum surfaces as a classifier error."""
    response = _ok_response(
        [{"path": "warranty", "label": "bogus", "reason": "made up."}],
    )
    client = _FakeLLMClient(response=response)
    with pytest.raises(PagesClassifierError, match="schema validation"):
        classify_pages(["warranty"], base_url=BASE_URL, model="gpt-5", llm=client)


def test_classify_pages_rejects_missing_path_in_response() -> None:
    """The classifier requires one entry per input path; missing entries fail."""
    response = _ok_response(
        # Only one of the two requested paths is present.
        [{"path": "warranty", "label": "support", "reason": "ok."}],
    )
    client = _FakeLLMClient(response=response)
    with pytest.raises(PagesClassifierError):
        classify_pages(
            ["warranty", "about-us"],
            base_url=BASE_URL,
            model="gpt-5",
            llm=client,
        )


# ---------------------------------------------------------------------------
# collapse_set_from
# ---------------------------------------------------------------------------


def test_collapse_set_from_picks_marketing_only() -> None:
    """Only entries whose label is in :data:`COLLAPSE_LABELS` enter the set."""
    doc = PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model="gpt-5",
        entries=[
            PageEntry(path="warranty", label="support", reason="r"),
            PageEntry(path="about-us", label="about", reason="r"),
            PageEntry(
                path="gift-bundle/coming-home-set",
                label="marketing",
                reason="r",
            ),
            PageEntry(path="paris-rules", label="marketing", reason="r"),
            PageEntry(path="store-locator", label="locator", reason="r"),
        ],
    )
    assert collapse_set_from(doc) == frozenset(
        {"gift-bundle/coming-home-set", "paris-rules"},
    )
    # Sanity-check the configured collapse labels.
    assert frozenset({"marketing"}) == COLLAPSE_LABELS


# ---------------------------------------------------------------------------
# stub_classification
# ---------------------------------------------------------------------------


def test_stub_classification_labels_all_unknown() -> None:
    """Stub doc preserves order, labels every path ``unknown``, marks model ``stub``."""
    doc = stub_classification(["a", "b", "c/sub"])
    assert doc.model == "stub"
    assert doc.classifier_version == PAGES_CLASSIFIER_VERSION
    assert [e.path for e in doc.entries] == ["a", "b", "c/sub"]
    assert all(e.label == "unknown" for e in doc.entries)
    # No path is collapsed (because none are labelled marketing).
    assert collapse_set_from(doc) == frozenset()


# ---------------------------------------------------------------------------
# merge_classifications
# ---------------------------------------------------------------------------


def test_merge_classifications_skips_already_classified() -> None:
    """When ``existing`` covers every ``new_paths`` entry, no LLM call runs."""
    existing = PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model="gpt-5",
        entries=[
            PageEntry(path="warranty", label="support", reason="r"),
            PageEntry(path="about-us", label="about", reason="r"),
        ],
    )
    client = _FakeLLMClient()
    merged = merge_classifications(
        existing,
        new_paths=["warranty", "about-us"],
        base_url=BASE_URL,
        model="gpt-5",
        llm=client,
    )

    assert merged is existing
    assert client.text_calls == []


def test_merge_classifications_appends_new() -> None:
    """Only previously unseen paths are sent; output unions in input order."""
    # Use a sentinel slug ("seen-foo") that is unlikely to appear in the
    # prompt's static example text — the prompt body legitimately mentions
    # ``warranty`` and ``gift-bundle/coming-home-set`` as label examples,
    # so substring assertions on those slugs are noisy.
    existing = PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model="gpt-5",
        entries=[PageEntry(path="seen-foo", label="support", reason="r")],
    )
    response = _ok_response(
        [
            {"path": "fresh-bar", "label": "about", "reason": "ok."},
            {"path": "paris-rules", "label": "marketing", "reason": "ok."},
        ],
    )
    client = _FakeLLMClient(response=response)

    merged = merge_classifications(
        existing,
        # ``seen-foo`` is already classified and must be filtered out.
        new_paths=["seen-foo", "fresh-bar", "paris-rules"],
        base_url=BASE_URL,
        model="gpt-5",
        llm=client,
    )

    assert [e.path for e in merged.entries] == ["seen-foo", "fresh-bar", "paris-rules"]
    assert [e.label for e in merged.entries] == ["support", "about", "marketing"]
    assert len(client.text_calls) == 1
    prompt = client.text_calls[0]["prompt"]
    # The LLM should only see the unseen paths.
    assert '"fresh-bar"' in prompt
    assert '"paris-rules"' in prompt
    assert '"seen-foo"' not in prompt


# ---------------------------------------------------------------------------
# write_pages_classification / read_pages_classification
# ---------------------------------------------------------------------------


def test_write_read_round_trip(tmp_path: Path) -> None:
    """Write then read returns an equivalent doc; output is byte-stable JSON."""
    doc = PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model="gpt-5",
        entries=[
            PageEntry(path="warranty", label="support", reason="warranty info."),
            PageEntry(path="paris-rules", label="marketing", reason="campaign."),
        ],
    )

    target = write_pages_classification(doc, tmp_path)

    assert target == tmp_path / "transition" / PAGES_CLASSIFICATION_FILENAME
    text = target.read_text(encoding="utf-8")
    # Trailing newline is mandatory for byte-stable diffs.
    assert text.endswith("\n")
    # Two-space indent is the deterministic format mirrored from pages.json.
    payload = json.loads(text)
    assert text == json.dumps(payload, indent=2) + "\n"

    loaded = read_pages_classification(tmp_path)
    assert loaded == doc
