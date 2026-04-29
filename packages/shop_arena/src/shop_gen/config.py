"""Public configuration and result types for ``shop_gen``.

This module defines the typed I/O contract documented in
``docs/specs/shop_arena/shop_gen.md`` §4.1:

* :class:`CatalogConfig` — scale knobs for Phase 2 data synthesis
  (collection / product / image counts).
* :class:`ShopGenConfig` — the inputs accepted by :func:`shop_gen.run`
  and the ``shop-gen`` CLI.
* :class:`ShopGenResult` — the published artifact paths returned to
  callers after a successful (or partial) run.
* :data:`RuntimeName` and :data:`ImageBackend` — closed-set literals for
  the agent runtime and image-generation backend.

The module is import-safe: it performs no I/O at import time. Filesystem
checks happen only when a config is *constructed*.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.runtimes import validate_model_grammar

RuntimeName = Literal["pi", "claude_code"]
"""Name of the agent runtime to drive the build-loop plan/exec phase."""

ImageBackend = Literal["placeholder", "ai"]
"""Image-generation backend selector.

``placeholder`` (v0.1 default) emits deterministic SVGs from the
synthesis stage. ``ai`` is a v0.2 concern (M8) and will land behind
this same flag.
"""

DEFAULT_RUNTIME: Final[RuntimeName] = "pi"
"""Default agent runtime forwarded to the build harness loop."""

DEFAULT_MODEL_BY_RUNTIME: Final[Mapping[RuntimeName, str]] = {
    "pi": "anthropic/claude-opus-4-7",
    "claude_code": "opus",
}
"""Per-runtime default model identifier in each runtime's native grammar.

``pi`` uses provider-prefixed IDs (``anthropic/...``); the ``claude_code``
CLI uses bare aliases (``opus``, ``sonnet``) or pinned IDs
(``claude-opus-4-5``). The mapping pins the same Opus tier across both,
expressed in the grammar each runtime expects — a single-grammar default
would silently break the other runtime's CLI three layers downstream.

Pinned at the application layer (not the harness runtimes) so the
repo-wide defaults are visible at the user-facing entrypoint and the
harness package stays unopinionated about which model each runtime
drives. Override per-run via :attr:`ShopGenConfig.model` or the
``--model`` CLI flag; pass ``--model ""`` to skip the flag and let the
runtime apply its own default.
"""


def default_model_for(runtime: RuntimeName) -> str:
    """Return the repo-wide default agent model for ``runtime``.

    Args:
        runtime: Target agent runtime name.

    Returns:
        The default model identifier in ``runtime``'s native grammar.
    """
    return DEFAULT_MODEL_BY_RUNTIME[runtime]


def _to_absolute(path: Path) -> Path:
    """Return ``path`` made absolute against the cwd; absolute paths pass through.

    Uses :meth:`pathlib.Path.absolute` rather than
    :meth:`pathlib.Path.resolve` because we only need the path to *be*
    absolute (so :func:`shop_gen.steps.state._resolve_input_path` does
    not re-root it under ``out_dir``). We do not want symlink
    dereferencing or ``..`` normalisation here — that would rewrite
    user-typed paths in surprising ways (e.g. macOS ``/tmp`` →
    ``/private/tmp``) and require filesystem access at config-construction
    time.
    """
    return path if path.is_absolute() else path.absolute()


DEFAULT_MAX_ITERS: Final[int] = 30
"""Default executor budget for the build-loop (spec §4.1)."""

DEFAULT_IMAGE_BACKEND: Final[ImageBackend] = "placeholder"
"""Default image backend (spec §4.1)."""

DEFAULT_COLLECTIONS: Final[int] = 10
"""Default number of synthesised collections (spec §4.1)."""

DEFAULT_PRODUCTS_PER_COLLECTION: Final[int] = 20
"""Default products per collection (spec §4.1, v0.1 small scale)."""

DEFAULT_IMAGES_PER_PRODUCT: Final[int] = 2
"""Default images per product (spec §4.1, v0.1 small scale)."""

DEFAULT_VISUAL_RETRY_BUDGET: Final[int] = 3
"""Default per-task ``visual_judge`` retry budget (spec §5.4).

Caps the number of consecutive ``visual_judge`` FAILs the verifier
tolerates against the same task before downgrading to ADVISORY. ``0``
disables the budget entirely.
"""

DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD: Final[float] = 7.0
"""Default ``visual_judge`` score-coercion floor (spec §9.3).

An agent-emitted ``pass`` verdict is coerced to ``fail`` when the
overall ``score`` is strictly below this threshold. The default of
``7.0`` matches the spec table entry in §4.1.
"""

DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY: Final[int] = 3
"""Default page-bucket fan-out worker count (spec §5.2.1 step 5, §5.6).

Caps the ``ThreadPoolExecutor`` width used by the ``consolidate``
page-bucket fan-out and the final-eval visual sweep. Values must
be strictly positive.
"""

KNOWN_JUDGES: Final[frozenset[str]] = frozenset(
    {"visual_judge", "quality_judge", "cross_task_consistency"},
)
"""Closed set of LLM-judge verifier names selectable via
``ShopGenConfig.judges`` (spec §5.5). Rule verifiers are not
selectable in v0.1 — every one is required for a valid build.
"""

DEFAULT_JUDGES: Final[frozenset[str]] = KNOWN_JUDGES
"""Default judge set: every known LLM judge enabled (spec §5.5)."""


class CatalogConfig(BaseModel):
    """Scale knobs for Phase 2 data synthesis.

    Defaults match spec §4.1 v0.1 small scale (200 products / 400
    images). All counts are strictly positive; pydantic raises
    ``ValidationError`` on zero or negative values.

    Attributes:
        collections: Number of collections to synthesise. Default 10.
        products_per_collection: Products synthesised per collection.
            Default 20. Total catalog size is
            ``collections * products_per_collection``.
        images_per_product: Image / alt-text pairs generated per
            product. Default 2.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    collections: int = Field(default=DEFAULT_COLLECTIONS, gt=0)
    products_per_collection: int = Field(default=DEFAULT_PRODUCTS_PER_COLLECTION, gt=0)
    images_per_product: int = Field(default=DEFAULT_IMAGES_PER_PRODUCT, gt=0)


class ShopGenConfig(BaseModel):
    """Inputs for one ``shop_gen`` run.

    Mirrors the I/O contract in spec §4.1.

    Attributes:
        seeds: One or more paths to ``shop_manuals/<domain>/<run_id>/``
            directories. At least one seed is required; a single seed
            takes the manual-merge fast path (§5.2).
        out_dir: Run workspace directory. ``None`` (default) lets the
            pipeline compute ``outputs/shops/<name>/``. When supplied,
            the directory must be empty, non-existent, or a prior
            ``shop_gen`` run dir (validated by the orchestrator at run
            time, not here).
        name: Slug for the SandboxShop. ``None`` (default) lets the
            pipeline derive a name from the seed domain (single seed)
            or from ``identity.descriptor`` (multi-seed).
        runtime: Agent runtime to drive the Phase 4 build loop.
        model: Model identifier forwarded to the runtime as ``--model``.
            ``None`` (the default) means "skip the flag and let the
            runtime apply its own default". The CLI fills in
            :func:`default_model_for` per ``runtime`` when ``--model`` is
            omitted; programmatic callers can do the same or pass an
            explicit value. Grammar is runtime-specific (see
            :data:`DEFAULT_MODEL_BY_RUNTIME`); supplying a ``pi``-grammar
            string with ``runtime="claude_code"`` (or vice versa) raises
            ``ValidationError`` at config-construction time.
        catalog: Scale knobs (see :class:`CatalogConfig`).
        max_iters: Executor iteration budget for the build loop.
            Strictly positive.
        image_backend: ``placeholder`` (v0.1 default) or ``ai`` (v0.2,
            stubbed in v0.1).
        visual_retry_budget: Per-task cap on consecutive ``visual_judge``
            FAILs before the verifier downgrades to ADVISORY (spec
            §5.4). ``0`` disables the budget entirely. Non-negative.
        judges: Set of LLM-judge verifier names to enable for the run
            (spec §5.5). Defaults to :data:`DEFAULT_JUDGES` (every
            known judge). Unknown tokens raise ``ValidationError`` at
            config-construction time. Pass ``frozenset()`` to disable
            every LLM judge; rule verifiers always run.
        visual_judge_pass_threshold: Score floor below which an agent-
            emitted ``visual_judge`` ``pass`` verdict is coerced to
            ``fail`` (spec §9.3). Defaults to
            :data:`DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD`. Must be
            non-negative.
        visual_judge_max_concurrency: Page-bucket fan-out worker count
            for the ``consolidate`` task and the final-eval visual sweep
            (spec §5.2.1 step 5, §5.6). Defaults to
            :data:`DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY`. Strictly
            positive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seeds: tuple[Path, ...] = Field(min_length=1)
    out_dir: Path | None = None
    name: str | None = None
    runtime: RuntimeName = DEFAULT_RUNTIME
    model: str | None = None
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    max_iters: int = Field(default=DEFAULT_MAX_ITERS, gt=0)
    image_backend: ImageBackend = DEFAULT_IMAGE_BACKEND
    visual_retry_budget: int = Field(default=DEFAULT_VISUAL_RETRY_BUDGET, ge=0)
    judges: frozenset[str] = Field(default=DEFAULT_JUDGES)
    visual_judge_pass_threshold: float = Field(
        default=DEFAULT_VISUAL_JUDGE_PASS_THRESHOLD,
        ge=0,
    )
    visual_judge_max_concurrency: int = Field(
        default=DEFAULT_VISUAL_JUDGE_MAX_CONCURRENCY,
        gt=0,
    )

    @field_validator("seeds", mode="before")
    @classmethod
    def _coerce_seeds(cls, value: object) -> object:
        """Accept a single ``Path`` / ``str`` or any iterable of them.

        Tuples are required for hashability under ``frozen=True``;
        coerce lists/tuples/iterables of ``str``/``Path`` into a
        ``tuple[Path, ...]``. Pydantic enforces ``min_length=1``.

        Relative paths are made absolute against the caller's cwd at
        construction time (see :func:`_to_absolute`) so
        :func:`shop_gen.steps.state._resolve_input_path` does not later
        re-join them onto ``out_dir`` (which would yield
        ``<out_dir>/<relative seed>`` and crash at fingerprint time).
        """

        def _coerce_one(item: object) -> object:
            return _to_absolute(Path(item)) if isinstance(item, (str, Path)) else item

        if value is None:
            return value
        if isinstance(value, (str, Path)):
            return (_coerce_one(value),)
        if isinstance(value, (list, tuple)):
            items: list[object] = list(value)  # type: ignore[arg-type]
            return tuple(_coerce_one(item) for item in items)
        return value

    @field_validator("judges", mode="before")
    @classmethod
    def _coerce_judges(cls, value: object) -> object:
        """Accept any iterable of judge names; coerce to ``frozenset[str]``.

        ``frozenset`` is required for hashability under ``frozen=True``.
        Pydantic's default coercion rejects ``set``/``list`` inputs for
        ``frozenset[str]`` fields under strict mode, so coerce eagerly.
        """
        if value is None:
            return value
        if isinstance(value, frozenset):
            return value
        if isinstance(value, (set, list, tuple)):
            return frozenset(value)  # type: ignore[arg-type]
        return value

    @field_validator("judges")
    @classmethod
    def _validate_judges(cls, value: frozenset[str]) -> frozenset[str]:
        """Reject unknown judge names against :data:`KNOWN_JUDGES`.

        Spec §5.5: only the closed set of LLM-judge verifier names
        is selectable. The error message names the offending tokens
        so CLI / library callers see exactly which entry is wrong.
        """
        unknown = value - KNOWN_JUDGES
        if unknown:
            offending = ", ".join(sorted(unknown))
            raise ValueError(
                f"unknown judge name(s): {offending}; known judges are {sorted(KNOWN_JUDGES)}",
            )
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        """Reject an empty / whitespace-only ``name``."""
        if value is None:
            return value
        if not value.strip():
            raise ValueError("name must be non-empty when provided")
        return value

    @model_validator(mode="after")
    def _validate_seed_paths(self) -> ShopGenConfig:
        """Reject seed paths that point at a regular file.

        A missing path is allowed at construction time (the orchestrator
        re-checks before reading), but a path that exists *and* is not a
        directory is unrecoverable and fails fast.
        """
        for seed in self.seeds:
            if seed.exists() and not seed.is_dir():
                raise ValueError(f"seed must be a directory, got file: {seed}")
        return self

    @model_validator(mode="after")
    def _validate_model_grammar(self) -> ShopGenConfig:
        """Reject ``model`` strings that don't match ``runtime``'s grammar.

        Catches the common foot-gun of pairing a ``pi``-grammar model
        (``anthropic/...``) with ``--runtime claude_code`` — the `claude`
        CLI silently rejects the provider prefix three layers downstream.
        Delegates to :func:`harness.runtimes.validate_model_grammar`.
        """
        validate_model_grammar(self.model, self.runtime)
        return self


class ShopGenResult(BaseModel):
    """Published outputs of one ``shop_gen`` run.

    All paths are absolute. They point at artifacts on disk after the
    pipeline's stale steps run to completion. Callers that only need a
    subset of artifacts can ignore the rest.

    Attributes:
        out_dir: Run workspace, equal to the resolved
            :attr:`ShopGenConfig.out_dir`.
        manual_dir: ``<out_dir>/manual/`` — composite-or-passthrough
            manual fed into the build loop.
        identity_path: ``<out_dir>/identity.json``.
        data_dir: ``<out_dir>/data/`` — SandboxShop dataset accepted by
            ``shop_backend.loadShopData``.
        hydrogen_dir: ``<out_dir>/hydrogen/`` — generated Hydrogen app.
        data_validation_path: ``<out_dir>/data_validation.json``.
        final_eval_path: ``<out_dir>/final_eval.json`` — advisory.
        build_run_dir: ``<out_dir>/runs/build/`` — harness run workspace
            for the build phase (debugging surface).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    out_dir: Path
    manual_dir: Path
    identity_path: Path
    data_dir: Path
    hydrogen_dir: Path
    data_validation_path: Path
    final_eval_path: Path
    build_run_dir: Path
