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

from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.config import FinalStatus
from harness.runtimes import validate_model_grammar

RuntimeName = Literal["pi", "claude_code"]
"""Name of the agent runtime to drive the plan/exec loop."""

DEFAULT_MAX_ITERS = 20
"""Default executor budget (spec §4.1)."""

DEFAULT_TIMEOUT_SECONDS = 1800.0
"""Default per-iteration timeout in seconds (spec §4.1)."""

DEFAULT_MODEL_BY_RUNTIME: Final[Mapping[RuntimeName, str]] = {
    "pi": "anthropic/claude-opus-4-7",
    "claude_code": "opus",
}
"""Per-runtime default model identifier in each runtime's native grammar.

``pi`` uses provider-prefixed IDs (``anthropic/...``); the ``claude_code``
CLI uses bare aliases (``opus``, ``sonnet``) or pinned IDs
(``claude-opus-4-5``). The mapping pins the same Opus tier across both,
expressed in the grammar each runtime expects. The single-grammar
default that lived here previously broke ``--runtime claude_code`` runs
because the ``claude`` CLI rejects the ``anthropic/`` prefix.

Pinned at the application layer (not the harness runtimes) so the
repo-wide defaults are visible at the user-facing entrypoint and the
harness package stays unopinionated about which model each runtime
drives. Override per-run via ``ExploreConfig.model`` or the ``--model``
CLI flag; pass ``--model ""`` to skip the flag and let the runtime
apply its own default.
"""


def default_model_for(runtime: RuntimeName) -> str:
    """Return the repo-wide default agent model for ``runtime``.

    Args:
        runtime: Target agent runtime name.

    Returns:
        The default model identifier in ``runtime``'s native grammar.
    """
    return DEFAULT_MODEL_BY_RUNTIME[runtime]


class ExploreConfig(BaseModel):
    """Inputs for one ``shop_explore`` run.

    Attributes:
        url: Public storefront base URL. Must be ``http://`` or
            ``https://``.
        out_dir: Run workspace directory. ``None`` (default) lets the
            pipeline compute ``outputs/shop_manuals/<domain>/<run_id>/``.
            When supplied, the directory must be either empty (or
            non-existent) for a fresh run, or contain a prior harness
            workspace for resume (resume.md §5.6). The harness validates
            the resume identity tuple before any subprocess is spawned.
        runtime: Agent runtime to drive the plan/exec loop.
        model: Model identifier forwarded to the runtime as ``--model``.
            ``None`` (the default) means "skip the flag and let the
            runtime apply its own default". The CLI fills in
            :func:`default_model_for` per ``runtime`` when ``--model`` is
            omitted; programmatic callers can do the same or pass an
            explicit value. The grammar is runtime-specific: ``pi`` uses
            patterns like ``sonnet:high`` or provider-prefixed IDs
            (``anthropic/claude-opus-4-7``); ``claude_code`` uses the
            ``claude`` CLI's grammar (``opus``, ``claude-opus-4-5``, …).
        max_iters: Executor iteration budget. Strictly positive. On
            resume this is the *additional* budget granted to the new
            attempt (resume.md §5).
        timeout: Per-iteration timeout in seconds. Strictly positive.
        force_resume: When ``True``, override
            :class:`harness.loop.ResumeRefusedError` for bad-state
            prior runs (resume.md §5.5). Has no effect on a fresh run.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    out_dir: Path | None = None
    runtime: RuntimeName = "pi"
    model: str | None = None
    max_iters: int = Field(default=DEFAULT_MAX_ITERS, gt=0)
    timeout: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    force_resume: bool = False

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
        """Reject a path that points at a regular file.

        A missing path or an existing directory (empty or not) are both
        accepted; the harness decides between fresh-mode
        (`Workspace.create`, requires empty) and resume-mode
        (`Workspace.open`, requires the resume identity tuple to match)
        once it inspects on-disk content. See resume.md §5.6 — pointing
        ``--out`` at an existing run directory is the resume affordance.
        """
        if value is None:
            return value
        if not value.exists():
            return value
        if not value.is_dir():
            raise ValueError(f"out_dir must be a directory or non-existent, got file: {value}")
        return value

    @model_validator(mode="after")
    def _validate_model_grammar(self) -> ExploreConfig:
        """Reject ``model`` strings that don't match ``runtime``'s grammar.

        Catches the common foot-gun of pairing a ``pi``-grammar model
        (``anthropic/...``) with ``--runtime claude_code`` — the `claude`
        CLI silently rejects the provider prefix three layers downstream.
        Delegates to :func:`harness.runtimes.validate_model_grammar`.
        """
        validate_model_grammar(self.model, self.runtime)
        return self


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
