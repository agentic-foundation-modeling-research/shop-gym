"""Deterministic deep-merge of ``*.caps.json`` fragments (spec §5.5).

Reads every fragment under a ``parts/`` directory in sorted filename
order and merges them into one :class:`~shop_arena.explore.capabilities.schema.Capabilities`.

Merge semantics (spec §5.5):

* Dicts merge recursively.
* Lists union, deduplicated, order-preserving (existing items first,
  then new items not already present).
* Scalar leaves overwrite (last writer wins). Non-equal overwrites are
  recorded as :class:`Conflict` entries.

Fragments may be partial — every top-level section and every leaf is
optional. The merged result is validated as a complete
:class:`~shop_arena.explore.capabilities.schema.Capabilities`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from shop_arena.explore.capabilities.schema import Capabilities


class CapabilitiesValidationError(ValueError):
    """Raised when a fragment is malformed or the merged document is invalid.

    Wraps both ``json.JSONDecodeError`` (bad fragment file) and
    ``pydantic.ValidationError`` (unknown fields, type mismatch, …) so
    callers have one error class to catch.
    """


class Conflict(BaseModel):
    """One leaf-level overwrite recorded during fragment merge.

    Attributes:
        path: Dotted path of the conflicting leaf, e.g. ``cart.type``.
        previous_value: Value present before the overwrite.
        previous_source: Filename of the fragment that set
            ``previous_value``.
        new_value: Value that overwrote ``previous_value``.
        new_source: Filename of the fragment that set ``new_value``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    previous_value: Any
    previous_source: str
    new_value: Any
    new_source: str


def merge_fragments(parts_dir: Path) -> tuple[Capabilities, list[Conflict]]:
    """Merge every ``*.caps.json`` under ``parts_dir`` into one schema.

    Fragments are read in sorted filename order so the merge is
    deterministic. The result is validated as a :class:`Capabilities`;
    schema violations (unknown fields, wrong types) raise
    :class:`CapabilitiesValidationError`.

    An empty (or fragment-less) ``parts_dir`` yields a default
    :class:`Capabilities` and an empty conflict list.

    Args:
        parts_dir: Directory containing ``<task_id>.caps.json`` fragments.

    Returns:
        Tuple of the merged :class:`Capabilities` and the list of
        leaf-level :class:`Conflict` entries recorded during the merge.

    Raises:
        CapabilitiesValidationError: A fragment was malformed JSON, was
            not a JSON object, or the merged document failed schema
            validation.
        FileNotFoundError: ``parts_dir`` does not exist.
    """
    if not parts_dir.exists():
        raise FileNotFoundError(f"parts_dir does not exist: {parts_dir}")
    if not parts_dir.is_dir():
        raise NotADirectoryError(f"parts_dir is not a directory: {parts_dir}")

    merged: dict[str, Any] = {}
    sources: dict[str, str] = {}
    conflicts: list[Conflict] = []

    for fragment_path in sorted(parts_dir.glob("*.caps.json")):
        fragment = _load_fragment(fragment_path)
        _deep_merge(
            merged,
            fragment,
            source=fragment_path.name,
            sources=sources,
            conflicts=conflicts,
        )

    try:
        capabilities = Capabilities.model_validate(merged)
    except ValidationError as exc:
        raise CapabilitiesValidationError(
            f"merged capabilities failed schema validation: {exc}"
        ) from exc

    return capabilities, conflicts


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _hashable_key(value: Any) -> Any:
    """Return a hashable key for list-union dedup.

    Scalars hash directly; dicts / lists are JSON-encoded with sorted
    keys so structurally equal items collapse.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _seed_sources(value: Any, *, source: str, sources: dict[str, str], path: str) -> None:
    """Record ``source`` for every leaf path inside a freshly-adopted subtree.

    When a new key is added wholesale to the merge target, future merges
    that recurse into the subtree may overwrite individual leaves; we
    need to know which fragment first set them so :class:`Conflict` can
    name a real ``previous_source``.
    """
    if isinstance(value, dict):
        children = cast("dict[str, Any]", value)
        for key, sub in children.items():
            child_path = f"{path}.{key}" if path else key
            _seed_sources(sub, source=source, sources=sources, path=child_path)
        return
    # Lists have no single source (union semantics); only scalar leaves
    # carry an attributable source.
    if isinstance(value, list):
        return
    sources[path] = source


def _deep_merge(
    target: dict[str, Any],
    addition: dict[str, Any],
    *,
    source: str,
    sources: dict[str, str],
    conflicts: list[Conflict],
    path: str = "",
) -> None:
    """Merge ``addition`` into ``target`` in-place per spec §5.5.

    Updates ``sources`` (path → fragment that set the leaf) and appends
    to ``conflicts`` whenever a non-equal scalar leaf is overwritten.
    """
    for key, value in addition.items():
        full_path = f"{path}.{key}" if path else key

        if key not in target:
            target[key] = value
            _seed_sources(value, source=source, sources=sources, path=full_path)
            continue

        existing = target[key]

        if isinstance(existing, dict) and isinstance(value, dict):
            _deep_merge(
                cast("dict[str, Any]", existing),
                cast("dict[str, Any]", value),
                source=source,
                sources=sources,
                conflicts=conflicts,
                path=full_path,
            )
            continue

        if isinstance(existing, list) and isinstance(value, list):
            existing_items = cast("list[Any]", existing)
            value_items = cast("list[Any]", value)
            seen: set[Any] = {_hashable_key(item) for item in existing_items}
            merged: list[Any] = list(existing_items)
            for item in value_items:
                key_for_dedupe = _hashable_key(item)
                if key_for_dedupe not in seen:
                    seen.add(key_for_dedupe)
                    merged.append(item)
            target[key] = merged
            # List union has no single "winner"; do not touch sources.
            continue

        # Scalar leaf (or type-mismatched merge): last writer wins.
        if existing != value:
            conflicts.append(
                Conflict(
                    path=full_path,
                    previous_value=existing,
                    previous_source=sources.get(full_path, "<unknown>"),
                    new_value=value,
                    new_source=source,
                )
            )
        target[key] = value
        sources[full_path] = source


def _load_fragment(path: Path) -> dict[str, Any]:
    """Load one ``*.caps.json`` fragment; raise on bad JSON or non-object."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilitiesValidationError(f"fragment {path.name} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CapabilitiesValidationError(
            f"fragment {path.name} must be a JSON object, got {type(raw).__name__}"
        )
    return cast("dict[str, Any]", raw)
