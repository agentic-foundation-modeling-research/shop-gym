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

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

DEFAULT_MODEL: Final[str] = "anthropic/claude-opus-4-7"
"""Default model identifier forwarded to the runtime.

Pinned at the application layer (not the harness `PiRuntime`) so the
repo-wide default is visible at the user-facing entrypoint and the
harness package stays unopinionated about which model `pi` drives.
Override per-run via :attr:`ShopGenConfig.model` or the ``--model``
CLI flag.
"""

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
        model: Model identifier forwarded to the runtime as
            ``--model``. Defaults to :data:`DEFAULT_MODEL`. Set to
            ``None`` to skip the flag and let the runtime pick its
            own default.
        catalog: Scale knobs (see :class:`CatalogConfig`).
        max_iters: Executor iteration budget for the build loop.
            Strictly positive.
        image_backend: ``placeholder`` (v0.1 default) or ``ai`` (v0.2,
            stubbed in v0.1).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seeds: tuple[Path, ...] = Field(min_length=1)
    out_dir: Path | None = None
    name: str | None = None
    runtime: RuntimeName = DEFAULT_RUNTIME
    model: str | None = DEFAULT_MODEL
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    max_iters: int = Field(default=DEFAULT_MAX_ITERS, gt=0)
    image_backend: ImageBackend = DEFAULT_IMAGE_BACKEND

    @field_validator("seeds", mode="before")
    @classmethod
    def _coerce_seeds(cls, value: object) -> object:
        """Accept a single ``Path`` / ``str`` or any iterable of them.

        Tuples are required for hashability under ``frozen=True``;
        coerce lists/tuples/iterables of ``str``/``Path`` into a
        ``tuple[Path, ...]``. Pydantic enforces ``min_length=1``.
        """
        if value is None:
            return value
        if isinstance(value, (str, Path)):
            return (Path(value),)
        if isinstance(value, (list, tuple)):
            items: list[object] = list(value)  # type: ignore[arg-type]
            return tuple(Path(item) if isinstance(item, str) else item for item in items)
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
