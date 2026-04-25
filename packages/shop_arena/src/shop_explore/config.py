"""Public configuration and result types for ``shop_explore``.

This module defines the typed I/O contract documented in
``docs/specs/shop_arena/shop_explore.md`` §4.1 and §8.1:

* :class:`ExploreConfig` — the inputs accepted by :func:`shop_explore.explore`
  and the ``shop-explore`` CLI.
* :class:`ExploreResult` — the published artifact paths and the harness
  ``final_status`` returned to callers.
* :data:`RuntimeName` — the literal name of the agent runtime to use
  (resolved through ``harness.get_runtime``).

The module is import-safe: it performs no I/O at import time. Filesystem
checks happen only when a config is *constructed* and explicitly opt
into validating ``out_dir``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from harness.config import FinalStatus

RuntimeName = Literal["pi", "claude_code"]
"""Name of the agent runtime to drive the plan/exec loop."""

DEFAULT_MAX_ITERS = 12
"""Default executor budget (spec §4.1)."""

DEFAULT_TIMEOUT_SECONDS = 600.0
"""Default per-iteration timeout in seconds (spec §4.1)."""


class ExploreConfig(BaseModel):
    """Inputs for one ``shop_explore`` run.

    Attributes:
        url: Public storefront base URL. Must be ``http://`` or
            ``https://``.
        out_dir: Run workspace directory. ``None`` (default) lets the
            pipeline compute ``outputs/shop_manuals/<domain>/<run_id>/``.
            When supplied, the directory must be empty or non-existent.
        runtime: Agent runtime to drive the plan/exec loop.
        max_iters: Executor iteration budget. Strictly positive.
        timeout: Per-iteration timeout in seconds. Strictly positive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    out_dir: Path | None = None
    runtime: RuntimeName = "pi"
    max_iters: int = Field(default=DEFAULT_MAX_ITERS, gt=0)
    timeout: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        """Reject anything that is not an ``http`` / ``https`` URL."""
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"url must start with http:// or https://, got: {value!r}")
        # Disallow an empty authority (e.g. "https://").
        scheme, _, rest = value.partition("://")
        if not rest or rest.startswith("/"):
            raise ValueError(f"url must include a host, got: {value!r}")
        _ = scheme  # purely for clarity; unused
        return value

    @field_validator("out_dir")
    @classmethod
    def _validate_out_dir(cls, value: Path | None) -> Path | None:
        """Require ``out_dir`` to be empty or non-existent.

        Mirrors §4.1 of the spec: the run workspace must be a fresh
        directory so the harness can own its layout. We accept a
        missing path, an existing empty directory, but reject anything
        else (a non-empty directory, or a file).
        """
        if value is None:
            return value
        if not value.exists():
            return value
        if not value.is_dir():
            raise ValueError(f"out_dir must be a directory or non-existent, got file: {value}")
        if any(value.iterdir()):
            raise ValueError(f"out_dir must be empty, got non-empty directory: {value}")
        return value


class ExploreResult(BaseModel):
    """Published outputs of one ``shop_explore`` run.

    All paths are absolute. They point at artifacts on disk after a
    successful (or partial) run. Callers that only need a subset of
    artifacts can ignore the rest.

    Attributes:
        run_dir: Run workspace, equal to ``ExploreConfig.out_dir`` (or
            the pipeline-computed default).
        manual_path: ``<run_dir>/artifact/manual.md``.
        capabilities_path: ``<run_dir>/artifact/capabilities.json``.
        stats_path: ``<run_dir>/artifact/stats.json``.
        manifest_path: ``<run_dir>/artifact/manifest.json``.
        prefetch_dir: ``<run_dir>/artifact/prefetch/``.
        final_status: Harness terminal status returned by
            ``run_plan_exec_loop``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_dir: Path
    manual_path: Path
    capabilities_path: Path
    stats_path: Path
    manifest_path: Path
    prefetch_dir: Path
    final_status: FinalStatus
