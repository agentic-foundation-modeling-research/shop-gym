"""``merge_capabilities`` — Phase 1 multi-seed capability merge.

Implements the step from spec §5.2 and the per-area rules in spec §9.2:

* Booleans (``has_*``): union (any true ⇒ true).
* Lists: union, dedup, order-preserving (``shop.tone`` capped at 3;
  ``homepage.section_types`` capped at the maximum seed
  ``homepage.section_count``).
* Scalars: majority; ties fall through to the first seed.
* Layout / style enums (``*_layout`` / ``*_style``): majority; ties fall
  through to an LLM completion conditioned on the merged descriptor.
* ``shop.descriptor``: LLM completion conditioned on the merged tone
  list. Brand-free.
* ``site_shell.nav_depth``: max across seeds.

The merge is deterministic per rule and only delegates to the LLM on
genuine ties (descriptor merges across distinct non-empty descriptors,
layout/style enums with no clear majority).

Step contract (spec §5.7.1):

* ``id``: ``merge_capabilities``.
* ``phase``: ``manual_merge``.
* ``inputs``: one :class:`~shop_arena.gen.steps.base.FileInput` per seed
  ``capabilities.json``.
* ``outputs``: ``manual/capabilities.json`` (validated against the
  closed :class:`shop_arena.explore.capabilities.Capabilities` schema) and
  ``.shop_gen/stage_cache/capability_conflicts.json`` (per-leaf
  conflict log consumed by ``write_merge_manifest`` in T2.4).

Module is import-safe — no I/O, no env reads, no side effects at
import.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from harness.runtimes import LLMCompleter
from shop_arena.explore.capabilities import Capabilities, CapabilitiesValidationError
from shop_arena.gen.manual_merge.prompts import load_capabilities_tiebreak_templates
from shop_arena.gen.steps.base import FileInput, InputRef, StepContext

_PHASE: Final[str] = "manual_merge"
_STEP_ID: Final[str] = "merge_capabilities"
_STEP_VERSION: Final[int] = 1

_OUT_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"
_OUT_CONFLICTS: Final[Path] = Path(".shop_gen") / "stage_cache" / "capability_conflicts.json"

_LLM_TIMEOUT_S: Final[float] = 360.0
_TONE_CAP: Final[int] = 3

_RULE_BOOL_UNION: Final[str] = "bool_union"
_RULE_SCALAR_MAJORITY: Final[str] = "scalar_majority"
_RULE_MAX: Final[str] = "max"
_RULE_LIST_UNION: Final[str] = "list_union"
_RULE_LIST_UNION_CAP_TONE: Final[str] = "list_union_cap_tone"
_RULE_LIST_UNION_CAP_SECTION_TYPES: Final[str] = "list_union_cap_section_types"
_RULE_LAYOUT_STYLE_ENUM: Final[str] = "layout_style_enum"
_RULE_LLM_DESCRIPTOR: Final[str] = "llm_descriptor"

# Per-leaf merge rules from spec §9.2. Keys are dotted paths into the
# closed :class:`Capabilities` schema; if a new field is added to the
# schema without an entry here, ``test_every_leaf_has_a_rule`` fails
# loudly so the §9.2 dispatch table is kept in lock-step.
_RULES: Final[dict[str, str]] = {
    # shop
    "shop.descriptor": _RULE_LLM_DESCRIPTOR,
    "shop.category": _RULE_SCALAR_MAJORITY,
    "shop.currency": _RULE_SCALAR_MAJORITY,
    "shop.tone": _RULE_LIST_UNION_CAP_TONE,
    # site_shell
    "site_shell.has_announcement_bar": _RULE_BOOL_UNION,
    "site_shell.header_style": _RULE_LAYOUT_STYLE_ENUM,
    "site_shell.has_mega_menu": _RULE_BOOL_UNION,
    "site_shell.nav_depth": _RULE_MAX,
    "site_shell.footer_groups": _RULE_SCALAR_MAJORITY,
    # homepage
    "homepage.section_types": _RULE_LIST_UNION_CAP_SECTION_TYPES,
    "homepage.section_count": _RULE_SCALAR_MAJORITY,
    "homepage.has_popup_modal": _RULE_BOOL_UNION,
    # collection
    "collection.layout": _RULE_LAYOUT_STYLE_ENUM,
    "collection.columns_desktop": _RULE_SCALAR_MAJORITY,
    "collection.filters": _RULE_LIST_UNION,
    "collection.sort": _RULE_LIST_UNION,
    "collection.pagination": _RULE_SCALAR_MAJORITY,
    # product
    "product.gallery_style": _RULE_LAYOUT_STYLE_ENUM,
    "product.variant_selectors": _RULE_LIST_UNION,
    "product.has_quantity_selector": _RULE_BOOL_UNION,
    "product.description_layout": _RULE_LAYOUT_STYLE_ENUM,
    "product.has_reviews": _RULE_BOOL_UNION,
    "product.has_recommendations": _RULE_BOOL_UNION,
    "product.has_personalization": _RULE_BOOL_UNION,
    # cart
    "cart.type": _RULE_SCALAR_MAJORITY,
    "cart.has_promo_input": _RULE_BOOL_UNION,
    "cart.has_upsells": _RULE_BOOL_UNION,
    "cart.has_shipping_estimate": _RULE_BOOL_UNION,
    # search
    "search.trigger": _RULE_SCALAR_MAJORITY,
    "search.has_predictive": _RULE_BOOL_UNION,
    "search.predictive_types": _RULE_LIST_UNION,
    "search.results_layout": _RULE_LAYOUT_STYLE_ENUM,
    # floating
    "floating.has_chat_widget": _RULE_BOOL_UNION,
    "floating.has_age_gate": _RULE_BOOL_UNION,
    "floating.has_cookie_banner": _RULE_BOOL_UNION,
    "floating.has_newsletter_popup": _RULE_BOOL_UNION,
    # intl
    "intl.has_locale_switcher": _RULE_BOOL_UNION,
    "intl.has_currency_switcher": _RULE_BOOL_UNION,
    # top-level
    "info_pages_present": _RULE_LIST_UNION,
}

# Order in which leaves are merged. ``shop.tone`` runs first so the
# descriptor LLM call sees the merged tone; ``shop.descriptor`` runs
# next so layout/style tiebreaks can condition on it.
_PRIORITY_ORDER: Final[tuple[str, ...]] = ("shop.tone", "shop.descriptor")


class MergeConflict(BaseModel):
    """One per-leaf disagreement recorded during multi-seed capability merge.

    Recorded only when at least two seeds supplied differing values for
    the leaf. Leaves where every seed agreed (or only one seed
    contributed a value) are merged silently.

    Attributes:
        path: Dotted path of the leaf, e.g. ``shop.currency``.
        rule: Name of the §9.2 rule used to resolve the leaf.
        seed_values: Mapping of seed identifier (``seed_<i>``) to the
            value that seed contributed. Seeds that supplied ``None``
            for the leaf are omitted.
        chosen_value: The value the merge selected.
        tiebreak: ``"first_seed"`` / ``"max"`` / ``"llm"`` / ``None``.
            ``None`` means the rule produced a clear winner (e.g.
            majority with a unique mode); the other values name the
            tiebreaker that was invoked.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    rule: str
    seed_values: dict[str, Any]
    chosen_value: Any
    tiebreak: str | None = None


def merge_capabilities_seeds(
    seed_paths: Sequence[Path],
    *,
    completer: LLMCompleter | None = None,
) -> tuple[Capabilities, list[MergeConflict]]:
    """Merge per-seed ``capabilities.json`` files into one closed schema.

    Implements spec §5.2 + §9.2. Each seed file is validated against
    the closed :class:`shop_arena.explore.capabilities.Capabilities` schema
    on load (unknown fields raise immediately so a bad seed never
    silently leaks through), then per-leaf rules from §9.2 produce the
    merged document. Genuine ties on layout/style enums and the
    ``shop.descriptor`` field delegate to ``completer``; every other
    rule is deterministic.

    Args:
        seed_paths: Per-seed ``capabilities.json`` files. The first
            path's value wins on scalar-majority ties (spec §9.2
            ``ties → first seed``).
        completer: Optional one-shot LLM. Required only when at least
            one descriptor or layout/style tie has to be broken.

    Returns:
        Tuple of the merged :class:`Capabilities` and the list of
        :class:`MergeConflict` records.

    Raises:
        ValueError: ``seed_paths`` is empty, or an LLM tiebreak was
            needed but ``completer`` is ``None``.
        FileNotFoundError: A seed path does not exist.
        CapabilitiesValidationError: A seed file is malformed JSON,
            does not match the closed :class:`Capabilities` schema, or
            the merged document fails schema validation.
    """
    if not seed_paths:
        raise ValueError("seed_paths must contain at least one path")

    seeds = [_load_seed(path) for path in seed_paths]
    seed_names = [f"seed_{index}" for index in range(len(seeds))]

    section_types_cap = _section_types_cap(seeds)

    leaves = (*_PRIORITY_ORDER, *sorted(p for p in _RULES if p not in _PRIORITY_ORDER))

    merged_tone: list[str] = []
    merged_descriptor: str | None = None
    sections: dict[str, dict[str, Any]] = {}
    top_level: dict[str, Any] = {"version": "0.1"}
    conflicts: list[MergeConflict] = []

    for path in leaves:
        rule = _RULES[path]
        per_seed = [_get_path(seed, path) for seed in seeds]
        chosen, conflict = _merge_leaf(
            path=path,
            rule=rule,
            seed_names=seed_names,
            per_seed_values=per_seed,
            completer=completer,
            descriptor=merged_descriptor,
            tone=merged_tone,
            section_types_cap=section_types_cap,
        )
        if path == "shop.tone" and isinstance(chosen, list):
            merged_tone = [str(item) for item in cast("list[Any]", chosen)]
        if path == "shop.descriptor" and isinstance(chosen, str):
            merged_descriptor = chosen
        if conflict is not None:
            conflicts.append(conflict)
        _assign_leaf(top_level, sections, path, chosen)

    merged_dict: dict[str, Any] = {**top_level, **sections}
    try:
        capabilities = Capabilities.model_validate(merged_dict)
    except ValidationError as exc:
        raise CapabilitiesValidationError(
            f"merged capabilities failed schema validation: {exc}",
        ) from exc
    return capabilities, conflicts


class MergeCapabilitiesStep:
    """Phase 1 ``merge_capabilities`` step (spec §5.2 + §9.2).

    Reads each seed's ``capabilities.json``, applies the §9.2 per-leaf
    rules via :func:`merge_capabilities_seeds`, and writes the merged
    document plus a per-leaf conflict log to the run workspace.

    Attributes:
        id: Step id (``merge_capabilities``).
        phase: ``manual_merge``.
        inputs: One :class:`FileInput` per seed ``capabilities.json``.
        outputs: ``manual/capabilities.json`` and
            ``.shop_gen/stage_cache/capability_conflicts.json``.
        depends_on: Empty (the step's only inputs are the seed files).
        version: Bumped when the merge behaviour changes (spec §5.7.1).
    """

    def __init__(self, seed_capabilities_paths: Sequence[Path]) -> None:
        """Build the step from the per-seed ``capabilities.json`` paths.

        Args:
            seed_capabilities_paths: One path per seed, in the user's
                seed order. May be empty, in which case the step lists
                only its id / phase (used by
                :func:`shop_arena.gen.pipeline.list_steps`).
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [FileInput(path=path) for path in seed_capabilities_paths]
        self.outputs: list[Path] = [_OUT_CAPABILITIES, _OUT_CONFLICTS]
        self.depends_on: list[str] = []
        self.version: int = _STEP_VERSION
        self._seed_paths: tuple[Path, ...] = tuple(seed_capabilities_paths)

    def run(self, ctx: StepContext) -> None:
        """Merge the seed capabilities files into ``manual/capabilities.json``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is forwarded as the
                LLM completer for descriptor / layout-style tiebreaks.

        Raises:
            ValueError: ``seed_paths`` is empty, or an LLM tiebreak was
                needed but ``ctx.runtime`` is ``None``.
            FileNotFoundError: A seed path does not exist.
            CapabilitiesValidationError: A seed file or the merged
                document fails closed-schema validation.
        """
        capabilities, conflicts = merge_capabilities_seeds(
            self._seed_paths,
            completer=ctx.runtime,
        )
        caps_path = ctx.out_dir / _OUT_CAPABILITIES
        caps_path.parent.mkdir(parents=True, exist_ok=True)
        caps_path.write_text(
            json.dumps(capabilities.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        conflicts_path = ctx.out_dir / _OUT_CONFLICTS
        conflicts_path.parent.mkdir(parents=True, exist_ok=True)
        conflicts_path.write_text(
            json.dumps(
                [c.model_dump(mode="json") for c in conflicts],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_seed(path: Path) -> dict[str, Any]:
    """Read and validate one seed ``capabilities.json``.

    Validates against the closed :class:`Capabilities` schema so a seed
    with extra/unknown fields raises :class:`CapabilitiesValidationError`
    immediately rather than leaking through the merge.

    Args:
        path: ``<seed>/artifact/capabilities.json``.

    Returns:
        The raw decoded JSON object.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        CapabilitiesValidationError: ``path`` is not valid JSON, is not
            a JSON object, or fails closed-schema validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"seed capabilities file not found: {path}")
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilitiesValidationError(
            f"seed {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise CapabilitiesValidationError(
            f"seed {path} must be a JSON object, got {type(raw).__name__}",
        )
    try:
        Capabilities.model_validate(raw)
    except ValidationError as exc:
        raise CapabilitiesValidationError(
            f"seed {path} does not match the closed capabilities schema: {exc}",
        ) from exc
    return cast("dict[str, Any]", raw)


def _get_path(seed: dict[str, Any], dotted: str) -> Any:
    """Walk a dotted path through a seed dict; missing leaves return ``None``."""
    current: Any = seed
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = cast("dict[str, Any]", current).get(part)
        if current is None:
            return None
    return current


def _section_types_cap(seeds: Sequence[dict[str, Any]]) -> int | None:
    """Return ``max(seed.homepage.section_count)`` per spec §9.2.

    Falls back to ``None`` (uncapped) when no seed supplies a section
    count.
    """
    counts = [
        value
        for seed in seeds
        if isinstance(value := _get_path(seed, "homepage.section_count"), int)
    ]
    return max(counts) if counts else None


def _assign_leaf(
    top_level: dict[str, Any],
    sections: dict[str, dict[str, Any]],
    path: str,
    chosen: Any,
) -> None:
    """Insert ``chosen`` into the merged result at ``path``.

    ``None`` leaves are skipped so the merged JSON omits fields no seed
    contributed to (the closed schema's defaults supply the value).
    """
    if chosen is None:
        return
    if "." in path:
        section, leaf = path.split(".", 1)
        sections.setdefault(section, {})[leaf] = chosen
    else:
        top_level[path] = chosen


def _merge_leaf(  # noqa: PLR0911 - one branch per spec §9.2 rule, intentionally explicit
    *,
    path: str,
    rule: str,
    seed_names: Sequence[str],
    per_seed_values: Sequence[Any],
    completer: LLMCompleter | None,
    descriptor: str | None,
    tone: Sequence[str],
    section_types_cap: int | None,
) -> tuple[Any, MergeConflict | None]:
    """Apply one §9.2 rule to one leaf and return ``(chosen, conflict)``."""
    contributions = [
        (name, value)
        for name, value in zip(seed_names, per_seed_values, strict=True)
        if value is not None
    ]
    if not contributions:
        return None, None

    if rule == _RULE_BOOL_UNION:
        return _bool_union(path=path, rule=rule, contributions=contributions)
    if rule == _RULE_SCALAR_MAJORITY:
        return _scalar_majority(path=path, rule=rule, contributions=contributions)
    if rule == _RULE_MAX:
        return _max_int(path=path, rule=rule, contributions=contributions)
    if rule == _RULE_LIST_UNION:
        return _list_union(path=path, rule=rule, contributions=contributions, cap=None)
    if rule == _RULE_LIST_UNION_CAP_TONE:
        return _list_union(path=path, rule=rule, contributions=contributions, cap=_TONE_CAP)
    if rule == _RULE_LIST_UNION_CAP_SECTION_TYPES:
        return _list_union(
            path=path,
            rule=rule,
            contributions=contributions,
            cap=section_types_cap,
        )
    if rule == _RULE_LAYOUT_STYLE_ENUM:
        return _layout_style_enum(
            path=path,
            rule=rule,
            contributions=contributions,
            descriptor=descriptor,
            completer=completer,
        )
    if rule == _RULE_LLM_DESCRIPTOR:
        return _llm_descriptor(
            path=path,
            rule=rule,
            contributions=contributions,
            tone=tone,
            completer=completer,
        )
    raise ValueError(f"unknown merge rule for {path!r}: {rule!r}")


def _bool_union(
    *,
    path: str,
    rule: str,
    contributions: Sequence[tuple[str, Any]],
) -> tuple[bool, MergeConflict | None]:
    chosen = any(bool(value) for _, value in contributions)
    if _has_disagreement(value for _, value in contributions):
        return chosen, MergeConflict(
            path=path,
            rule=rule,
            seed_values=dict(contributions),
            chosen_value=chosen,
            tiebreak=None,
        )
    return chosen, None


def _scalar_majority(
    *,
    path: str,
    rule: str,
    contributions: Sequence[tuple[str, Any]],
) -> tuple[Any, MergeConflict | None]:
    chosen, tiebreak = _majority_with_first_seed_tiebreak(contributions)
    if not _has_disagreement(value for _, value in contributions):
        return chosen, None
    return chosen, MergeConflict(
        path=path,
        rule=rule,
        seed_values=dict(contributions),
        chosen_value=chosen,
        tiebreak=tiebreak,
    )


def _max_int(
    *,
    path: str,
    rule: str,
    contributions: Sequence[tuple[str, Any]],
) -> tuple[int, MergeConflict | None]:
    values: list[int] = []
    for _, value in contributions:
        if not isinstance(value, int) or isinstance(value, bool):
            raise CapabilitiesValidationError(
                f"{path}: max rule expects int values, got {type(value).__name__}",
            )
        values.append(value)
    chosen = max(values)
    if not _has_disagreement(values):
        return chosen, None
    return chosen, MergeConflict(
        path=path,
        rule=rule,
        seed_values=dict(contributions),
        chosen_value=chosen,
        tiebreak="max",
    )


def _list_union(
    *,
    path: str,
    rule: str,
    contributions: Sequence[tuple[str, Any]],
    cap: int | None,
) -> tuple[list[Any], MergeConflict | None]:
    seen: set[Any] = set()
    merged: list[Any] = []
    for _, value in contributions:
        if not isinstance(value, list):
            raise CapabilitiesValidationError(
                f"{path}: list_union rule expects list values, got {type(value).__name__}",
            )
        for item in cast("list[Any]", value):
            key = _hashable(item)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    if cap is not None and cap >= 0:
        merged = merged[:cap]
    if not _list_disagreement([value for _, value in contributions]):
        return merged, None
    return merged, MergeConflict(
        path=path,
        rule=rule,
        seed_values={name: list(value) for name, value in contributions},
        chosen_value=list(merged),
        tiebreak=None,
    )


def _layout_style_enum(
    *,
    path: str,
    rule: str,
    contributions: Sequence[tuple[str, Any]],
    descriptor: str | None,
    completer: LLMCompleter | None,
) -> tuple[Any, MergeConflict | None]:
    """Majority; ties fall through to an LLM choice keyed on descriptor."""
    chosen, tiebreak = _majority_with_first_seed_tiebreak(contributions)
    if not _has_disagreement(value for _, value in contributions):
        return chosen, None
    if tiebreak is None:
        # Clear majority — record the conflict but no LLM call needed.
        return chosen, MergeConflict(
            path=path,
            rule=rule,
            seed_values=dict(contributions),
            chosen_value=chosen,
            tiebreak=None,
        )
    # Tie — delegate to the LLM, conditioned on the merged descriptor.
    candidates = sorted({str(value) for _, value in contributions})
    llm_choice = _ask_layout_tiebreak(
        path=path,
        candidates=candidates,
        descriptor=descriptor,
        completer=completer,
    )
    final = llm_choice if llm_choice in candidates else chosen
    final_tiebreak = "llm" if llm_choice in candidates else "first_seed"
    return final, MergeConflict(
        path=path,
        rule=rule,
        seed_values=dict(contributions),
        chosen_value=final,
        tiebreak=final_tiebreak,
    )


def _llm_descriptor(
    *,
    path: str,
    rule: str,
    contributions: Sequence[tuple[str, Any]],
    tone: Sequence[str],
    completer: LLMCompleter | None,
) -> tuple[str, MergeConflict | None]:
    """Merge non-empty descriptors via the LLM, conditioned on the merged tone."""
    descriptors = [
        (name, str(value).strip())
        for name, value in contributions
        if isinstance(value, str) and value.strip()
    ]
    if not descriptors:
        # Should be unreachable: caller filters None contributions, so
        # the only way to land here is every seed providing an empty
        # string, which is not a descriptor we can merge.
        raise CapabilitiesValidationError(
            f"{path}: descriptor merge requires at least one non-empty seed value",
        )
    distinct = {value for _, value in descriptors}
    if len(distinct) == 1:
        return descriptors[0][1], None
    if completer is None:
        raise ValueError(
            f"{path}: descriptor disagreement requires a runtime with LLMCompleter; got None",
        )
    prompt = load_capabilities_tiebreak_templates()["descriptor"].format(
        tone=", ".join(tone) if tone else "(none)",
        descriptors="\n".join(f"- {value}" for _, value in descriptors),
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S).strip()
    if not raw:
        raise ValueError(f"{path}: LLM returned an empty descriptor")
    chosen = raw.splitlines()[0].strip()
    return chosen, MergeConflict(
        path=path,
        rule=rule,
        seed_values=dict(descriptors),
        chosen_value=chosen,
        tiebreak="llm",
    )


def _ask_layout_tiebreak(
    *,
    path: str,
    candidates: Sequence[str],
    descriptor: str | None,
    completer: LLMCompleter | None,
) -> str | None:
    """Run the layout/style tiebreak prompt; return the LLM's choice or ``None``.

    Returns ``None`` (caller falls back to first-seed) when no completer
    is configured, no descriptor context is available yet, or the LLM
    returns a value outside the candidate set.
    """
    if completer is None or descriptor is None:
        return None
    prompt = load_capabilities_tiebreak_templates()["layout"].format(
        path=path,
        candidates=", ".join(candidates),
        descriptor=descriptor,
    )
    raw = completer.complete(prompt, timeout=_LLM_TIMEOUT_S).strip()
    if not raw:
        return None
    return raw.splitlines()[0].strip()


def _majority_with_first_seed_tiebreak(
    contributions: Sequence[tuple[str, Any]],
) -> tuple[Any, str | None]:
    """Return ``(winner, tiebreak)`` where ``tiebreak`` is ``"first_seed"`` on tie.

    ``tiebreak`` is ``None`` when one value strictly outvotes the rest;
    ``"first_seed"`` when two or more values are tied at the top vote
    count, in which case the winner is the first contributing seed's
    value among the top-voted candidates (spec §9.2).
    """
    counts: dict[Any, int] = {}
    for _, value in contributions:
        key = _hashable(value)
        counts[key] = counts.get(key, 0) + 1
    top_count = max(counts.values())
    winners = {key for key, count in counts.items() if count == top_count}
    if len(winners) == 1:
        # Recover the original (non-hashable-coerced) value from the
        # first contribution that mapped to the winning key.
        winning_key = next(iter(winners))
        for _, value in contributions:
            if _hashable(value) == winning_key:
                return value, None
    for _, value in contributions:
        if _hashable(value) in winners:
            return value, "first_seed"
    raise AssertionError("unreachable: winners drawn from contributions")


def _hashable(value: Any) -> Any:
    """Return a hashable key for ``value`` suitable for set / dict use."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _has_disagreement(values: Any) -> bool:
    """Return ``True`` iff ``values`` contains two or more distinct entries."""
    keys = {_hashable(value) for value in values}
    return len(keys) > 1


def _list_disagreement(values: Sequence[list[Any]]) -> bool:
    """Return ``True`` iff two seeds contributed lists with different contents."""
    if len(values) < 2:  # noqa: PLR2004 - 2 is a minimum, not a magic number
        return False
    reference = {_hashable(item) for item in values[0]}
    return any({_hashable(item) for item in other} != reference for other in values[1:])


__all__ = [
    "MergeCapabilitiesStep",
    "MergeConflict",
    "merge_capabilities_seeds",
]
