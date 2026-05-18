"""LLM classifier for ``/pages/<slug>`` URLs discovered during the BFS.

Shopify's ``/pages/`` namespace mixes terse info pages (``/pages/warranty``,
``/pages/faq``) with sentence-shaped marketing/campaign slugs
(``/pages/gordons-golden-ticket-paris-rules``,
``/pages/gift-bundle/coming-home-set``). The transition graph collapses
the marketing pages to ``/pages/<*>`` so they do not flood the node
count, but keeps the info pages distinct because they describe real
shopping affordances. Earlier versions used a hyphen-count heuristic;
this module replaces it with a small batched LLM call.

Responsibilities:

* :func:`classify_pages` — issue exactly one
  :meth:`shop_arena.util._llm.LLMVisionClient.call_text` request that
  classifies every input path under a closed seven-label enum and
  returns a frozen :class:`PagesClassification` document.
* :func:`merge_classifications` — lazy per-level helper used by the
  BFS: classify only paths the existing on-disk doc has not seen yet,
  then return a union doc with insertion order preserved.
* :func:`collapse_set_from` — derive the frozen set of paths that
  should collapse to ``/pages/<*>`` (currently the ``"marketing"``
  label) so the canonicalizer can consume it without knowing about
  labels.
* :func:`stub_classification` — caller-side fallback when the
  pipeline is run with ``--no-rubric`` and the LLM must not be
  invoked; every path is labelled ``"unknown"`` (no collapses).
* :func:`write_pages_classification` / :func:`read_pages_classification`
  — deterministic JSON writer/reader for the
  ``transition/pages_classification.json`` artifact.

Module is import-safe: no I/O, no env reads, no network. The classifier
prompt is embedded as a module-level constant — short enough that a
separate ``prompt.md`` would add more friction than it removes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shop_arena.env_eval.errors import PagesClassifierError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from shop_arena.util._llm import LLMVisionClient

__all__ = [
    "COLLAPSE_LABELS",
    "DEFAULT_PAGES_CLASSIFIER_MODEL",
    "PAGES_CLASSIFICATION_FILENAME",
    "PAGES_CLASSIFIER_VERSION",
    "PageEntry",
    "PagesClassification",
    "PagesLabel",
    "build_pages_classifier_prompt",
    "classify_pages",
    "collapse_set_from",
    "merge_classifications",
    "read_pages_classification",
    "stub_classification",
    "write_pages_classification",
]

#: Filename written under ``<run_dir>/transition/`` by
#: :func:`write_pages_classification`.
PAGES_CLASSIFICATION_FILENAME: Final[str] = "pages_classification.json"

#: Version of the classifier prompt + response schema. Bumped on any
#: contract-affecting change (label enum, prompt body, output shape) and
#: persisted in every artifact so cohorts can be filtered by version.
PAGES_CLASSIFIER_VERSION: Final[str] = "0.1"

#: Default model the pipeline uses for the classifier when no override
#: is supplied. Kept as a module-level constant so callers wiring the
#: pipeline can pin a single source of truth.
DEFAULT_PAGES_CLASSIFIER_MODEL: Final[str] = "gpt-5"

#: Closed seven-label enum describing why a ``/pages/<slug>`` page
#: exists. ``unknown`` is the conservative fallback the prompt directs
#: the model toward when it cannot confidently choose another label;
#: ``unknown`` is *not* in :data:`COLLAPSE_LABELS` so uncertain pages
#: stay as distinct graph nodes.
PagesLabel = Literal[
    "support",
    "about",
    "policy",
    "program",
    "locator",
    "marketing",
    "unknown",
]

#: Tuple form of the label enum, used for JSON-schema generation and
#: validation. Kept as a tuple so the schema and the pydantic model both
#: read from the same constant.
_PAGES_LABEL_VALUES: Final[tuple[str, ...]] = (
    "support",
    "about",
    "policy",
    "program",
    "locator",
    "marketing",
    "unknown",
)

#: Labels whose paths are eligible to collapse to ``/pages/<*>`` in the
#: transition graph. ``marketing`` is the only one today: campaign /
#: bundle / promo pages tend to flood the slug space without adding
#: shopping affordances. Every other label keeps its distinct graph
#: node identity.
COLLAPSE_LABELS: Final[frozenset[str]] = frozenset({"marketing"})


# ---------------------------------------------------------------------------
# Closed pydantic schema for the on-disk artifact and the LLM response.
# ---------------------------------------------------------------------------


class PageEntry(BaseModel):
    """A single ``/pages/<path>`` classification result.

    Attributes:
        path: Post-``/pages/`` string for the discovered URL. Includes
            any further ``/<sub>`` segments — e.g. ``"warranty"``,
            ``"about-us"``, or ``"gift-bundle/coming-home-set"``.
        label: One of the seven values in :data:`PagesLabel`. The model
            is instructed to return ``"unknown"`` whenever it is not
            confident, so callers should not treat ``"unknown"`` as an
            error.
        reason: One short sentence the model emits explaining its
            choice. Persisted verbatim for audit; the pipeline does not
            interpret it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    label: PagesLabel
    reason: str


class PagesClassification(BaseModel):
    """Closed schema for the ``transition/pages_classification.json`` artifact.

    Attributes:
        classifier_version: Always :data:`PAGES_CLASSIFIER_VERSION` at
            write time. Pinned in the artifact so cohorts of artifacts
            can be filtered by version.
        model: Model id used to produce :attr:`entries`. Set to
            ``"stub"`` for documents produced by
            :func:`stub_classification` (i.e. ``--no-rubric`` runs).
        entries: Insertion-ordered list of per-path classifications.
            Order is the order paths were first observed by the BFS;
            :func:`merge_classifications` preserves it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    classifier_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    entries: list[PageEntry]


# ---------------------------------------------------------------------------
# Closed JSON schema sent to the model.
# ---------------------------------------------------------------------------


#: JSON schema the LLM client forwards to the model. Mirrors
#: :class:`PagesClassification`'s wire shape (without the
#: ``classifier_version`` / ``model`` fields, which the caller fills
#: in).  Closed: ``additionalProperties=false`` and an exhaustive
#: ``required`` list, matching how the rubric module shapes its closed
#: schema (see :mod:`shop_arena.env_eval.observation.rubric`).
_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "enum": list(_PAGES_LABEL_VALUES)},
                    "reason": {"type": "string"},
                },
                "required": ["path", "label", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entries"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Prompt construction.
# ---------------------------------------------------------------------------


#: Body of the classifier prompt. Short by design — the entire model
#: contract fits in ~30 lines, so a separate ``prompt.md`` would add
#: friction without reducing duplication. The label table is the source
#: of truth for "what each label means" and is mirrored by the
#: :data:`PagesLabel` literal for validation.
_PROMPT_BODY: Final[str] = """\
You classify Shopify ``/pages/<slug>`` URLs into one of seven labels so
the storefront crawler can decide which pages are distinct shopping
affordances and which are interchangeable marketing/campaign pages.

Use exactly one of the labels below for every input path:

- support: customer-support / help / contact / FAQ / shipping / returns
  / warranty / size-guide pages.
- about: company narrative — about us, our story, mission, team,
  press, sustainability statements.
- policy: legal / policy pages (terms of service, privacy policy,
  accessibility, do-not-sell, cookie policy, GDPR notice).
- program: structured customer programs — loyalty, rewards, referral,
  affiliate, wholesale / trade, gift cards, newsletter signup.
- locator: store / dealer / stockist / retailer / showroom locators
  and "find us" pages.
- marketing: campaign / promo / lookbook / collaboration / bundle /
  landing pages. These tend to be sentence-shaped slugs created in
  bulk; collapsing them keeps the graph readable.
- unknown: anything you are not confident about. Prefer this over a
  bad guess — uncertain pages are kept as distinct graph nodes,
  whereas a wrong ``marketing`` label silently merges nodes.

Be conservative: when uncertain, return ``"unknown"``.

Storefront base URL: {base_url}

Classify these paths (all are post-``/pages/`` strings — e.g.
``"warranty"`` for ``/pages/warranty`` or
``"gift-bundle/coming-home-set"`` for
``/pages/gift-bundle/coming-home-set``):

{path_list}

Return a JSON object of shape:

  {{"entries": [{{"path": "...", "label": "...", "reason": "..."}}, ...]}}

with exactly one entry per input path, in the same order. ``reason``
is one short sentence justifying the label.
"""


def build_pages_classifier_prompt(paths: Sequence[str], *, base_url: str) -> str:
    """Return the prompt body with ``base_url`` and ``paths`` interpolated.

    Args:
        paths: Post-``/pages/`` strings to classify, in input order.
        base_url: Absolute storefront URL the model uses for context.

    Returns:
        The interpolated prompt body. Path lines are ``- "<path>"`` so
        the model sees a clean enumeration without having to decide
        whether bullet markers are part of the path.
    """
    path_lines = "\n".join(f'- "{p}"' for p in paths)
    return _PROMPT_BODY.format(base_url=base_url, path_list=path_lines)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def classify_pages(
    paths: Sequence[str],
    *,
    base_url: str,
    model: str,
    llm: LLMVisionClient,
) -> PagesClassification:
    """Classify ``paths`` with one batched ``call_text`` request.

    Args:
        paths: Post-``/pages/`` strings to classify, in input order.
            Empty input returns an empty document without invoking the
            LLM.
        base_url: Absolute storefront URL passed to the model for
            context.
        model: Model id recorded on the returned
            :class:`PagesClassification`. Passed in by the caller so
            this module does not need to re-derive it from ``llm`` —
            keeping the artifact's ``model`` field truthful when the
            caller plumbs a wrapper client.
        llm: Any concrete :class:`LLMVisionClient`. Tests inject a
            fake.

    Returns:
        A frozen :class:`PagesClassification` recording one
        :class:`PageEntry` per input path, in the same order.

    Raises:
        PagesClassifierError: The model response did not parse as the
            closed schema (missing ``entries``, unknown ``label``,
            type errors, etc.), the entries list had the wrong length,
            or its paths did not match the input set exactly. The
            pipeline can catch this at the call site and fall back to
            :func:`stub_classification`.
    """
    if not paths:
        return PagesClassification(
            classifier_version=PAGES_CLASSIFIER_VERSION,
            model=model,
            entries=[],
        )

    prompt = build_pages_classifier_prompt(paths, base_url=base_url)
    response = llm.call_text(prompt=prompt, schema=_RESPONSE_SCHEMA)
    doc = _build_classification(response_parsed=response.parsed, model=model)
    _check_path_coverage(expected=paths, doc=doc)
    return doc


def collapse_set_from(doc: PagesClassification) -> frozenset[str]:
    """Return the set of paths that should collapse to ``/pages/<*>``.

    Currently picks every entry whose label is in
    :data:`COLLAPSE_LABELS` (i.e. ``"marketing"``). Returned as a
    frozen set so it can be threaded straight into
    :func:`shop_arena.env_eval.transition.canonicalize.canonical_id_for_path`.

    Args:
        doc: A previously produced :class:`PagesClassification`.

    Returns:
        ``frozenset(entry.path for entry in doc.entries if entry.label
        in COLLAPSE_LABELS)``.
    """
    return frozenset(entry.path for entry in doc.entries if entry.label in COLLAPSE_LABELS)


def stub_classification(paths: Sequence[str]) -> PagesClassification:
    """Return a no-LLM document labelling every path ``"unknown"``.

    Used by the pipeline when ``--no-rubric`` is set so the BFS still
    receives a schema-valid document on disk but no path is collapsed.
    The ``model`` field is set to ``"stub"`` so consumers can tell the
    artifact apart from a real classifier run.

    Args:
        paths: Post-``/pages/`` strings to record. Order is preserved.

    Returns:
        A :class:`PagesClassification` whose every entry has label
        ``"unknown"`` and a fixed reason string.
    """
    entries = [
        PageEntry(path=path, label="unknown", reason="stub: classifier disabled")
        for path in paths
    ]
    return PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model="stub",
        entries=entries,
    )


def merge_classifications(
    existing: PagesClassification | None,
    *,
    new_paths: Sequence[str],
    base_url: str,
    model: str,
    llm: LLMVisionClient,
) -> PagesClassification:
    """Classify only the unseen paths and union with ``existing``.

    The lazy per-level BFS calls this once per level: ``existing`` is
    the doc loaded from disk (or ``None`` on the first level), and
    ``new_paths`` is every ``/pages/<rest>`` path discovered at the
    current level. Paths already classified in ``existing`` are never
    re-sent to the model; the returned doc preserves ``existing``'s
    insertion order and appends the freshly classified entries in
    input order.

    Args:
        existing: Previously loaded classification document, or
            ``None`` if no doc exists yet.
        new_paths: Post-``/pages/`` paths discovered at the current
            BFS level. Duplicates are filtered (first occurrence
            wins). Already-classified paths are dropped before the
            LLM call.
        base_url: Absolute storefront URL passed to the model.
        model: Model id recorded on the returned doc when an LLM call
            actually runs. When every input path is already covered,
            ``existing`` is returned unchanged so its ``model`` field
            is preserved.
        llm: Any concrete :class:`LLMVisionClient`.

    Returns:
        A :class:`PagesClassification` covering ``existing.entries``
        followed by the newly classified entries. When ``existing``
        already covers every ``new_paths`` entry the function returns
        ``existing`` verbatim **without invoking the LLM**.

    Raises:
        PagesClassifierError: The classifier call returned an invalid
            response.
    """
    classified_paths: set[str] = (
        set() if existing is None else {entry.path for entry in existing.entries}
    )
    seen_in_call: set[str] = set()
    to_classify: list[str] = []
    for path in new_paths:
        if path in classified_paths or path in seen_in_call:
            continue
        seen_in_call.add(path)
        to_classify.append(path)

    if not to_classify:
        if existing is not None:
            return existing
        return PagesClassification(
            classifier_version=PAGES_CLASSIFIER_VERSION,
            model=model,
            entries=[],
        )

    fresh = classify_pages(to_classify, base_url=base_url, model=model, llm=llm)

    merged_entries: list[PageEntry] = (
        list(existing.entries) if existing is not None else []
    )
    merged_entries.extend(fresh.entries)
    return PagesClassification(
        classifier_version=PAGES_CLASSIFIER_VERSION,
        model=model,
        entries=merged_entries,
    )


def write_pages_classification(
    doc: PagesClassification,
    run_dir: Path | str,
) -> Path:
    """Serialise ``doc`` to ``<run_dir>/transition/pages_classification.json``.

    The ``transition/`` subdirectory is created if missing. Output is
    deterministic JSON: two-space indent and a trailing newline,
    matching :func:`shop_arena.env_eval.pages.write_pages_json` so
    byte-stable reuse checks behave the same way across artifacts.

    Args:
        doc: Validated :class:`PagesClassification`.
        run_dir: Run directory; the artifact lands under
            ``<run_dir>/transition/``.

    Returns:
        The absolute :class:`pathlib.Path` of the written file, for
        chaining.
    """
    target = Path(run_dir) / "transition" / PAGES_CLASSIFICATION_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = doc.model_dump(mode="json")
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def read_pages_classification(run_dir: Path | str) -> PagesClassification:
    """Load and validate ``<run_dir>/transition/pages_classification.json``.

    Args:
        run_dir: Run directory containing the classifier artifact.

    Returns:
        The parsed :class:`PagesClassification`.

    Raises:
        PagesClassifierError: The file is missing, malformed JSON, or
            violates the closed pydantic schema. The exception wraps
            the underlying error so callers depend only on the EnvEval
            failure vocabulary.
    """
    target = Path(run_dir) / "transition" / PAGES_CLASSIFICATION_FILENAME
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PagesClassifierError(f"cannot read {target}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PagesClassifierError(f"{target} is not valid JSON: {exc}") from exc
    try:
        return PagesClassification.model_validate(payload)
    except ValidationError as exc:
        raise PagesClassifierError(f"{target} failed schema validation: {exc}") from exc


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_classification(
    *,
    response_parsed: Any,
    model: str,
) -> PagesClassification:
    """Validate the raw LLM response into a :class:`PagesClassification`.

    Raises:
        PagesClassifierError: The response is missing, not a JSON
            object, or fails closed-schema validation.
    """
    if response_parsed is None:
        raise PagesClassifierError(
            "pages classifier returned no parsed response (model may have rejected the schema)",
        )
    if not isinstance(response_parsed, dict):
        raise PagesClassifierError(
            "pages classifier response root is "
            f"{type(response_parsed).__name__}, expected object",
        )
    response_dict = cast("dict[str, Any]", response_parsed)
    payload: dict[str, Any] = {
        "classifier_version": PAGES_CLASSIFIER_VERSION,
        "model": model,
        "entries": response_dict.get("entries"),
    }
    try:
        return PagesClassification.model_validate(payload)
    except ValidationError as exc:
        raise PagesClassifierError(
            f"pages classifier response failed schema validation: {exc}",
        ) from exc


def _check_path_coverage(
    *,
    expected: Sequence[str],
    doc: PagesClassification,
) -> None:
    """Verify ``doc.entries`` covers ``expected`` exactly once each.

    The model contract requires one entry per input path, in input order;
    enforce it here so a silent path drop in the response surfaces as a
    classifier error rather than a missing graph node downstream.

    Raises:
        PagesClassifierError: The entry count or path set does not match
            ``expected``.
    """
    actual = [entry.path for entry in doc.entries]
    if len(actual) != len(expected):
        raise PagesClassifierError(
            "pages classifier returned "
            f"{len(actual)} entries for {len(expected)} input paths",
        )
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise PagesClassifierError(
            "pages classifier path mismatch: "
            f"missing={missing!r}, unexpected={unexpected!r}",
        )
