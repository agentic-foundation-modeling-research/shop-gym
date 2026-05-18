"""Artifact-existence checks for the run-directory cache (spec §5.7, M6).

EnvEval's reuse model is intentionally literal: the filesystem run directory
*is* the cache.  Before each pipeline step, the orchestrator asks "are the
files this step would otherwise produce already on disk?".  If they all are,
the step is skipped; if any is missing, the step runs and overwrites only
its own artifacts.  No content hash, TTL, or HTTP freshness check exists in
v0.1.

This module owns the two helpers the orchestrator (and tests) consume:

* :func:`expected_artifacts` — enumerate the required files per step for a
  given ``run_dir`` + discovered :class:`PagesDoc`.
* :func:`can_skip` — answer "are all files for this step present on disk?".

The mapping intentionally lives separately from the per-layer reuse logic
(``observation/rubric.py``, ``transition/`` graph reload, …): those layers
do their own finer-grained checks (e.g. "is the rubric artifact a stub?").
The resume layer is the coarse, uniform "files exist?" gate that backs
:data:`Manifest.steps` accounting in M6.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, Literal, cast, get_args

from shop_arena.env_eval.errors import ResumeError
from shop_arena.env_eval.pages import (
    PAGES_JSON_FILENAME,
    PageOk,
    PagesDoc,
    SearchPageOk,
)
from shop_arena.env_eval.transition import node_artifacts as node_artifacts_mod

__all__ = [
    "STEPS",
    "Step",
    "can_skip",
    "expected_artifacts",
    "measurable_buckets",
]

#: Pipeline-step identifier used as the key of :func:`expected_artifacts`.
#:
#: Order mirrors the orchestrator's execution order in
#: :func:`shop_arena.env_eval.pipeline.evaluate` (page selection →
#: transition graph capture → node observation → node action → metrics
#: aggregation). ``metrics`` is the final write that depends on every
#: upstream layer (spec §5.7).
Step = Literal["pages", "transition", "observation", "action", "metrics"]

#: Tuple of every :data:`Step` literal in execution order.
STEPS: Final[tuple[Step, ...]] = get_args(Step)

#: Filename constants for run-directory artifacts.  ``pages.json`` already
#: lives on :mod:`shop_arena.env_eval.pages`; the rest are inlined here so
#: this module is the single source of truth for the §5.7 reuse table.
_OBSERVATION_DIR: Final[str] = "observation"
_ACTION_DIR: Final[str] = "action"
_TRANSITION_DIR: Final[str] = "transition"
_GRAPH_JSON: Final[str] = "graph.json"
_TRACE_JSONL: Final[str] = "trace.jsonl"
_NODE_DIR: Final[str] = node_artifacts_mod.NODE_DIRNAME
_NODE_INDEX_JSON: Final[str] = node_artifacts_mod.NODE_INDEX_FILENAME
_METRICS_JSON: Final[str] = "metrics.json"

#: Shared index file written by the node-driven observation/action layers.
_INDEX_JSON: Final[str] = "index.json"

#: Per-node observation suffixes. File stems are transition-node folder names
#: rather than the five page-bucket labels.
_OBSERVATION_INDEX_KEYS: Final[tuple[str, ...]] = (
    "screenshot",
    "axtree_json",
    "axtree_text",
    "rubric",
)

#: Per-node action-space artifact key in ``action/index.json``.
_ACTION_INDEX_KEYS: Final[tuple[str, ...]] = ("action_space",)


def measurable_buckets(pages: PagesDoc) -> list[str]:
    """Return the ordered bucket names that produce per-page artifacts.

    Mirrors the iteration order used by
    :func:`shop_arena.env_eval.pipeline._capture_observation` and
    :func:`shop_arena.env_eval.pipeline._capture_action` so artifact
    enumeration here matches what the orchestrator actually writes.
    ``not_found`` buckets are dropped — they neither write artifacts nor
    are required for reuse.

    Args:
        pages: Discovered or loaded :class:`PagesDoc`.

    Returns:
        List of bucket-name strings.  ``"homepage"`` is always first because
        :class:`PagesDoc.homepage` is :class:`PageOk` by construction
        (the run aborts otherwise; spec §5.2).
    """
    buckets: list[str] = ["homepage"]
    for name, entry in (
        ("collection", pages.collection),
        ("product", pages.product),
        ("policy", pages.policy),
    ):
        if isinstance(entry, PageOk):
            buckets.append(name)
    if isinstance(pages.cart_and_search.cart, PageOk):
        buckets.append("cart_and_search.cart")
    if isinstance(pages.cart_and_search.search, SearchPageOk):
        buckets.append("cart_and_search.search")
    return buckets


def expected_artifacts(
    run_dir: Path,
    pages: PagesDoc | None,
    *,
    no_rubric: bool,
) -> dict[Step, list[Path]]:
    """Enumerate the files required for each step's reuse (spec §5.7).

    The mapping is total: every :data:`Step` is a key, even for steps that
    cannot be evaluated yet because their upstream index does not exist. In
    that case the step's value contains only the expected ``index.json`` path,
    which makes :func:`can_skip` return ``False`` until the step has actually
    run. Node-level observation/action artifacts are enumerated from the
    layer's own ``index.json`` once present, because graph-node filenames are
    unknown until the transition step has captured ``transition/node/index.json``.

    The ``no_rubric`` flag is part of the documented signature (impl-plan
    M6) but does **not** change which files are required: the rubric step
    writes a stub artifact under ``--no-rubric`` so the path set is the
    same either way (spec §5.3). The flag is preserved for forward-
    compatibility — future work may want to differentiate stub-vs-real
    rubric files at this layer.

    Args:
        run_dir: Resolved run directory (parent of ``pages.json``).
        pages: Loaded :class:`PagesDoc`, or ``None`` when discovery has
            not yet run. Retained for the pages-aware public signature; the
            node-driven observation/action paths come from layer indexes.
        no_rubric: Whether the run is in stub-rubric mode.  Currently
            informational; see the note above.

    Returns:
        Mapping from step name to the list of files that must all exist
        on disk for the step to be skippable.
    """
    del no_rubric  # documented but path-irrelevant in v0.1; see docstring.

    artifacts: dict[Step, list[Path]] = {step: [] for step in STEPS}
    artifacts["pages"].append(run_dir / PAGES_JSON_FILENAME)
    artifacts["transition"].append(run_dir / _TRANSITION_DIR / _GRAPH_JSON)
    artifacts["transition"].append(run_dir / _TRANSITION_DIR / _TRACE_JSONL)
    artifacts["transition"].append(
        run_dir / _TRANSITION_DIR / _NODE_DIR / _NODE_INDEX_JSON,
    )
    artifacts["metrics"].append(run_dir / _METRICS_JSON)

    obs_dir = run_dir / _OBSERVATION_DIR
    action_dir = run_dir / _ACTION_DIR
    artifacts["observation"].extend(
        _indexed_layer_artifacts(obs_dir, _OBSERVATION_INDEX_KEYS),
    )
    artifacts["action"].extend(
        _indexed_layer_artifacts(action_dir, _ACTION_INDEX_KEYS),
    )
    return artifacts


def _indexed_layer_artifacts(step_dir: Path, filename_keys: tuple[str, ...]) -> list[Path]:
    """Return required files for a node-indexed layer.

    The layer index is always required. Once it exists, every string filename
    recorded under ``filename_keys`` in every node entry is required too.
    Malformed indexes deliberately add a missing sentinel path so
    :func:`can_skip` returns ``False`` rather than silently accepting a corrupt
    cache entry.
    """
    index_path = step_dir / _INDEX_JSON
    paths: list[Path] = [index_path]
    if not index_path.is_file():
        return paths
    try:
        payload = cast("object", json.loads(index_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return [index_path, step_dir / ".invalid-index"]
    if not isinstance(payload, dict):
        return [index_path, step_dir / ".invalid-index"]
    raw_nodes = cast("dict[str, Any]", payload).get("nodes")
    if not isinstance(raw_nodes, list):
        return [index_path, step_dir / ".invalid-index"]
    for raw_node in cast("list[object]", raw_nodes):
        if not isinstance(raw_node, dict):
            return [index_path, step_dir / ".invalid-index"]
        node = cast("dict[str, Any]", raw_node)
        for key in filename_keys:
            value = node.get(key)
            if isinstance(value, str) and value:
                paths.append(step_dir / value)
    return paths


def can_skip(step: Step, expected: dict[Step, list[Path]]) -> bool:
    """Return ``True`` iff every required file for ``step`` exists on disk.

    A step with an empty path list returns ``False``: the resume table
    leaves a step "empty" only when its dependency (``pages.json``) has
    not been resolved yet, which is exactly when the step must run.

    Args:
        step: One of :data:`STEPS`.
        expected: The mapping returned by :func:`expected_artifacts`.

    Returns:
        ``True`` when every path under ``expected[step]`` is a regular
        file; ``False`` otherwise (including the empty-list case).

    Raises:
        ResumeError: ``step`` is not a known :data:`Step` literal.
    """
    if step not in expected:
        raise ResumeError(
            f"unknown step {step!r}; expected one of {STEPS}",
        )
    paths = expected[step]
    if not paths:
        return False
    return all(path.is_file() for path in paths)
