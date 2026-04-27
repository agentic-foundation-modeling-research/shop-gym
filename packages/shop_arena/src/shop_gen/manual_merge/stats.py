"""``compute_merge_stats`` — Phase 1 multi-seed stats merge (spec §5.2).

Deterministic recomputation of the published ``manual/stats.json``
priors from the per-seed ``stats.json`` summaries (the
:func:`shop_explore.stats.compute` output) plus the merged
:class:`~shop_explore.capabilities.Capabilities` document. Pure
function — no LLM, no network, no env reads.

The output mirrors the closed :class:`shop_explore.stats.Stats` schema
so downstream consumers (Phase 2 ``synth_collections`` + ``synth_*``
steps) can read it via the same model the seeds use. Per spec §5.5
"Stats faithfulness", the values are *priors*, not targets — they
describe the typical scale and shape of the seeds, not what the
synthesized catalog must reproduce.

Aggregation rules:

* ``products_total`` / ``collections_total``: median across seeds
  (rounded to int). The merged shop is one storefront, so summing
  would inflate the count beyond any single seed's reality.
* ``products_per_collection``:
    * ``avg``: mean of seed averages.
    * ``median``: median of seed medians.
    * ``max``: max of seed maxes.
* ``price``: min-of-mins, max-of-maxes, median-of-medians across
  seeds with a non-zero price signal. Seeds whose ``PriceStats`` are
  the all-zero default (no prices observed) are excluded so they do
  not collapse the merged ``min`` to ``0``. ``currency`` prefers
  ``capabilities.shop.currency``; falls back to the first non-empty
  seed currency.
* ``products_with_variants_pct``: arithmetic mean across seeds.
* ``variant_axes_observed``: union preserving first-seen order across
  seeds. Names are already normalized by
  :func:`shop_explore.stats.compute`.
* ``navigation_depth_max`` / ``homepage_section_count`` /
  ``info_pages_count`` / ``feature_count``: re-derived from the
  merged capabilities — same recipe as
  :func:`shop_explore.stats.compute`. The seeds' values are
  ignored for these fields because the merged capabilities are the
  single source of truth (spec §5.2 "treat merged capabilities as
  ground truth").

Step contract (spec §5.7.1):

* ``id``: ``compute_merge_stats``.
* ``phase``: ``manual_merge``.
* ``inputs``: one :class:`~shop_gen.steps.base.FileInput` per seed
  ``stats.json`` plus a :class:`~shop_gen.steps.base.StepInput` for
  ``merge_capabilities``.
* ``outputs``: ``manual/stats.json``.
* ``depends_on``: ``[merge_capabilities]``.

Module is import-safe: no I/O, no env reads, no side effects at import.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from pydantic import ValidationError

from shop_explore.capabilities import Capabilities, CapabilitiesValidationError
from shop_explore.stats import PriceStats, ProductsPerCollection, Stats
from shop_gen.steps.base import FileInput, InputRef, StepContext, StepInput

_PHASE: Final[str] = "manual_merge"
_STEP_ID: Final[str] = "compute_merge_stats"
_UPSTREAM_ID: Final[str] = "merge_capabilities"
_STEP_VERSION: Final[int] = 1

_OUT_STATS: Final[Path] = Path("manual") / "stats.json"
_IN_CAPABILITIES: Final[Path] = Path("manual") / "capabilities.json"


def merge_stats_seeds(
    seed_stats_paths: Sequence[Path],
    *,
    capabilities: Capabilities,
) -> Stats:
    """Merge per-seed ``stats.json`` files into a single :class:`Stats`.

    Args:
        seed_stats_paths: One ``stats.json`` per seed, in the user's
            seed order.
        capabilities: Merged capabilities document (Phase 1
            ``merge_capabilities`` output). Drives the
            capability-derived leaves (``navigation_depth_max``,
            ``homepage_section_count``, ``info_pages_count``,
            ``feature_count``) and the ``price.currency`` fallback.

    Returns:
        A :class:`Stats` instance ready to be serialized to
        ``manual/stats.json``.

    Raises:
        ValueError: ``seed_stats_paths`` is empty.
        FileNotFoundError: A seed path does not exist.
        StatsValidationError: A seed file is malformed JSON, is not a
            JSON object, or fails closed-schema validation.
    """
    if not seed_stats_paths:
        raise ValueError("seed_stats_paths must contain at least one path")

    seeds = [_load_seed(path) for path in seed_stats_paths]

    return Stats(
        products_total=_median_int([seed.products_total for seed in seeds]),
        collections_total=_median_int([seed.collections_total for seed in seeds]),
        products_per_collection=_merge_products_per_collection(seeds),
        price=_merge_price(seeds, capabilities),
        products_with_variants_pct=_mean(
            [seed.products_with_variants_pct for seed in seeds],
        ),
        variant_axes_observed=_union_axes(seeds),
        navigation_depth_max=capabilities.site_shell.nav_depth or 0,
        homepage_section_count=capabilities.homepage.section_count or 0,
        info_pages_count=len(capabilities.info_pages_present),
        feature_count=_count_features(capabilities.model_dump()),
    )


class ComputeMergeStatsStep:
    """Phase 1 ``compute_merge_stats`` step (spec §5.2).

    Reads each seed's ``stats.json`` and the merged capabilities written
    by the upstream ``merge_capabilities`` step, recomputes the merged
    priors via :func:`merge_stats_seeds`, and writes the result to
    ``manual/stats.json``.

    Attributes:
        id: Step id (``compute_merge_stats``).
        phase: ``manual_merge``.
        inputs: One :class:`FileInput` per seed ``stats.json`` plus a
            :class:`StepInput` for ``merge_capabilities``.
        outputs: ``manual/stats.json``.
        depends_on: ``[merge_capabilities]``.
        version: Bumped when the merge behaviour changes (spec §5.7.1).
    """

    def __init__(self, seed_stats_paths: Sequence[Path]) -> None:
        """Build the step from the per-seed ``stats.json`` paths.

        Args:
            seed_stats_paths: One path per seed, in the user's seed
                order. May be empty, in which case the step lists only
                its id / phase (used by
                :func:`shop_gen.pipeline.list_steps`).
        """
        self.id: str = _STEP_ID
        self.phase: str = _PHASE
        self.inputs: list[InputRef] = [
            *(FileInput(path=path) for path in seed_stats_paths),
            StepInput(step_id=_UPSTREAM_ID),
        ]
        self.outputs: list[Path] = [_OUT_STATS]
        self.depends_on: list[str] = [_UPSTREAM_ID]
        self.version: int = _STEP_VERSION
        self._seed_paths: tuple[Path, ...] = tuple(seed_stats_paths)

    def run(self, ctx: StepContext) -> None:
        """Recompute the merged stats into ``manual/stats.json``.

        Args:
            ctx: Execution context. ``ctx.runtime`` is ignored — the
                step is fully deterministic.

        Raises:
            ValueError: ``seed_stats_paths`` is empty.
            FileNotFoundError: A seed path is missing, or the upstream
                ``manual/capabilities.json`` has not been written yet.
            CapabilitiesValidationError: The upstream merged
                capabilities file fails closed-schema validation.
            StatsValidationError: A seed file fails closed-schema
                validation.
        """
        capabilities_path = ctx.out_dir / _IN_CAPABILITIES
        if not capabilities_path.exists():
            raise FileNotFoundError(
                f"merged capabilities not found at {capabilities_path}; "
                "run merge_capabilities first",
            )
        capabilities = _load_capabilities(capabilities_path)

        merged = merge_stats_seeds(self._seed_paths, capabilities=capabilities)

        out_path = ctx.out_dir / _OUT_STATS
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(merged.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class StatsValidationError(ValueError):
    """Raised when a seed ``stats.json`` cannot be parsed or does not match the schema."""


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _load_seed(path: Path) -> Stats:
    """Read and validate one seed ``stats.json``.

    Validates against the closed :class:`Stats` schema so a seed with
    extra/unknown fields raises :class:`StatsValidationError` immediately
    rather than leaking through the merge.
    """
    if not path.exists():
        raise FileNotFoundError(f"seed stats file not found: {path}")
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StatsValidationError(f"seed {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise StatsValidationError(
            f"seed {path} must be a JSON object, got {type(raw).__name__}",
        )
    try:
        return Stats.model_validate(raw)
    except ValidationError as exc:
        raise StatsValidationError(
            f"seed {path} does not match the closed stats schema: {exc}",
        ) from exc


def _load_capabilities(path: Path) -> Capabilities:
    """Read and validate ``manual/capabilities.json``."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilitiesValidationError(
            f"merged capabilities at {path} is not valid JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise CapabilitiesValidationError(
            f"merged capabilities at {path} must be a JSON object, got {type(raw).__name__}",
        )
    try:
        return Capabilities.model_validate(raw)
    except ValidationError as exc:
        raise CapabilitiesValidationError(
            f"merged capabilities at {path} does not match the closed schema: {exc}",
        ) from exc


def _median_int(values: Sequence[int]) -> int:
    """Return ``round(median(values))`` as an int, or ``0`` for empty input."""
    if not values:
        return 0
    return round(statistics.median(values))


def _mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean, or ``0.0`` for empty input."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _merge_products_per_collection(seeds: Sequence[Stats]) -> ProductsPerCollection:
    """Aggregate the per-collection distribution across seeds."""
    avgs = [seed.products_per_collection.avg for seed in seeds]
    medians = [seed.products_per_collection.median for seed in seeds]
    maxes = [seed.products_per_collection.max for seed in seeds]
    if not seeds:
        return ProductsPerCollection()
    return ProductsPerCollection(
        avg=_mean(avgs),
        median=float(statistics.median(medians)),
        max=max(maxes),
    )


def _merge_price(seeds: Sequence[Stats], capabilities: Capabilities) -> PriceStats:
    """Aggregate variant-price distributions across seeds.

    Seeds whose :class:`PriceStats` is the all-zero default (no prices
    observed) are excluded from the min/max/median aggregation so they
    do not collapse the merged ``min`` to ``0``. Currency prefers the
    merged capabilities, then falls back to the first non-empty seed
    currency.
    """
    contributing = [seed.price for seed in seeds if seed.price.max > 0]
    currency = capabilities.shop.currency or _first_currency(seeds)
    if not contributing:
        return PriceStats(currency=currency)
    return PriceStats(
        min=min(price.min for price in contributing),
        max=max(price.max for price in contributing),
        median=float(statistics.median(price.median for price in contributing)),
        currency=currency,
    )


def _first_currency(seeds: Sequence[Stats]) -> str:
    """Return the first non-empty ``price.currency`` across seeds, else ``""``."""
    for seed in seeds:
        if seed.price.currency:
            return seed.price.currency
    return ""


def _union_axes(seeds: Sequence[Stats]) -> list[str]:
    """Union of ``variant_axes_observed`` across seeds, preserving first-seen order."""
    seen: dict[str, None] = {}
    for seed in seeds:
        for axis in seed.variant_axes_observed:
            if axis not in seen:
                seen[axis] = None
    return list(seen)


def _count_features(value: Any) -> int:
    """Count truthy bools and non-empty list lengths inside a capabilities dict.

    Matches :func:`shop_explore.stats._count_features` so the merged
    ``feature_count`` is computed by the same recipe the seeds used.
    Numeric and string leaves are excluded.
    """
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, list):
        return len(cast("list[Any]", value))
    if isinstance(value, dict):
        return sum(_count_features(child) for child in cast("dict[str, Any]", value).values())
    return 0


__all__ = [
    "ComputeMergeStatsStep",
    "StatsValidationError",
    "merge_stats_seeds",
]
