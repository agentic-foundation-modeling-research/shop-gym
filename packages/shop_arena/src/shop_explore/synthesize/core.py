"""§5.10 post-loop synthesis entrypoint.

Pure function modulo a single ``llm.complete`` call: reads the harness
artifact tree, writes the four published files, and returns a
:class:`SynthesisResult` summary.

The single LLM call is the *only* network egress; any exception raised
by the client is swallowed (in :func:`shop_explore.synthesize.manual.render_manual`)
and treated as an empty response so we always emit a ``manual.md``
(spec §5.10 fallback).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from shop_explore.capabilities import (
    CapabilitiesValidationError,
    Conflict,
    merge_fragments,
)
from shop_explore.stats import compute as compute_stats
from shop_explore.synthesize.manifest import build_manifest
from shop_explore.synthesize.manual import concat_parts, render_manual


class SynthesisError(ValueError):
    """Raised when synthesis cannot produce a published Shop Manual.

    Wraps both layout errors (missing ``parts/`` or ``prefetch/``) and
    schema errors (capabilities fragments fail to merge into a valid
    :class:`~shop_explore.capabilities.Capabilities`). Either is fatal:
    callers should surface a non-zero exit code.
    """


class LLMClient(Protocol):
    """Minimal contract for the synthesis-time LLM call (spec §5.10).

    A single ``complete(prompt) -> str`` method. Implementations are
    free to talk to any provider; tests inject a stub. Exceptions
    raised by ``complete`` are caught by :func:`synthesize` and
    treated as an empty response (triggers fallback, not a failure).
    """

    def complete(self, prompt: str) -> str:
        """Return the model's text completion for ``prompt``."""
        ...


class SynthesisResult(BaseModel):
    """Outputs of :func:`synthesize`.

    All paths are absolute and rooted under ``<run_dir>/artifact/``.

    Attributes:
        manual_path: ``manual.md`` (prose).
        capabilities_path: ``capabilities.json`` (structured tags).
        stats_path: ``stats.json`` (analysis statistics).
        manifest_path: ``manifest.json`` (run summary).
        manual_fallback: ``True`` iff the LLM response was empty or
            shorter than
            :data:`shop_explore.synthesize.manual.MANUAL_MIN_CHARS` and
            we fell back to deterministic concatenation of
            ``parts/*.md``.
        capability_conflicts: Leaf-level merge conflicts recorded by
            :func:`shop_explore.capabilities.merge_fragments`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manual_path: Path
    capabilities_path: Path
    stats_path: Path
    manifest_path: Path
    manual_fallback: bool
    capability_conflicts: tuple[Conflict, ...]


def synthesize(
    run_dir: Path,
    *,
    llm: LLMClient,
    manual_prompt: str,
) -> SynthesisResult:
    """Run the post-loop synthesis (spec §5.10) over a populated ``run_dir``.

    Pure function modulo a single ``llm.complete`` call. Reads
    ``<run_dir>/artifact/parts/``, ``<run_dir>/artifact/prefetch/``,
    ``<run_dir>/plan.md``, and (best-effort) ``<run_dir>/run.json``;
    writes the four published artifacts under ``<run_dir>/artifact/``.

    Args:
        run_dir: Harness run workspace; equal to
            :attr:`shop_explore.config.ExploreConfig.out_dir` when the
            caller supplied one. Must already contain the harness
            ``artifact/`` tree.
        llm: Client used for the single manual-merge call. Any
            exception raised by ``complete`` is treated as an empty
            response and triggers the fallback path.
        manual_prompt: Merge prompt body (the ``synthesize_manual.md``
            resource owned by ``shop_explore.prompts``). Sent verbatim
            ahead of the capabilities document and per-task parts.

    Returns:
        A :class:`SynthesisResult` recording the four published paths,
        the ``manual_fallback`` flag, and any capability merge
        conflicts.

    Raises:
        SynthesisError: ``<run_dir>/artifact/parts`` or
            ``<run_dir>/artifact/prefetch`` is missing, or the merged
            capabilities fragments fail schema validation.
    """
    artifact_dir = run_dir / "artifact"
    parts_dir = artifact_dir / "parts"
    prefetch_dir = artifact_dir / "prefetch"
    if not parts_dir.is_dir():
        raise SynthesisError(f"missing parts dir: {parts_dir}")
    if not prefetch_dir.is_dir():
        raise SynthesisError(f"missing prefetch dir: {prefetch_dir}")

    try:
        capabilities, conflicts = merge_fragments(parts_dir)
    except CapabilitiesValidationError as exc:
        raise SynthesisError(f"capabilities validation failed: {exc}") from exc

    stats = compute_stats(prefetch_dir, capabilities)

    capabilities_path = artifact_dir / "capabilities.json"
    stats_path = artifact_dir / "stats.json"
    manual_path = artifact_dir / "manual.md"
    manifest_path = artifact_dir / "manifest.json"

    capabilities_path.write_text(capabilities.model_dump_json(indent=2) + "\n", encoding="utf-8")
    stats_path.write_text(stats.model_dump_json(indent=2) + "\n", encoding="utf-8")

    parts_concat = concat_parts(parts_dir)
    manual_text, manual_fallback = render_manual(
        llm=llm,
        manual_prompt=manual_prompt,
        capabilities=capabilities,
        parts_concat=parts_concat,
    )
    manual_path.write_text(manual_text, encoding="utf-8")

    manifest = build_manifest(
        run_dir=run_dir,
        conflicts=conflicts,
        manual_fallback=manual_fallback,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return SynthesisResult(
        manual_path=manual_path,
        capabilities_path=capabilities_path,
        stats_path=stats_path,
        manifest_path=manifest_path,
        manual_fallback=manual_fallback,
        capability_conflicts=tuple(conflicts),
    )
