"""§5.10 post-loop synthesis entrypoint.

Pure function modulo a single ``llm.complete`` call: reads the harness
artifact tree, writes the four published files, and returns a
:class:`SynthesisResult` summary.

The single LLM call is the *only* network egress. Failures — wire-level
exceptions or sub-:data:`shop_explore.synthesize.manual.MANUAL_MIN_CHARS`
responses — surface as :class:`SynthesisError` and abort the run; no
``manual.md`` is written. Earlier revisions silently fell back to a
deterministic concatenation of ``parts/*.md``, which masked LLM-client
misconfiguration; that fallback was removed deliberately (spec §5.10).
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
from shop_explore.synthesize.manual import (
    ManualRenderError,
    concat_parts,
    render_manual,
)


class SynthesisError(ValueError):
    """Raised when synthesis cannot produce a published Shop Manual.

    Wraps layout errors (missing ``parts/`` or ``prefetch/``), schema
    errors (capabilities fragments fail to merge), and manual-render
    failures (LLM call raises or returns a sub-threshold response).
    Either is fatal: callers should surface a non-zero exit code.
    """


class LLMClient(Protocol):
    """Minimal contract for the synthesis-time LLM call (spec §5.10).

    A single ``complete(prompt) -> str`` method. Implementations are
    free to talk to any provider; tests inject a stub. Exceptions
    raised by ``complete`` propagate as :class:`SynthesisError` —
    synthesis does not retry or fall back.
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
        capability_conflicts: Leaf-level merge conflicts recorded by
            :func:`shop_explore.capabilities.merge_fragments`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manual_path: Path
    capabilities_path: Path
    stats_path: Path
    manifest_path: Path
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
        llm: Client used for the single manual-merge call. Exceptions
            from ``complete`` propagate as :class:`SynthesisError`;
            sub-:data:`shop_explore.synthesize.manual.MANUAL_MIN_CHARS`
            responses do the same.
        manual_prompt: Merge prompt body (the ``synthesize_manual.md``
            resource owned by ``shop_explore.prompts``). Sent verbatim
            ahead of the capabilities document and per-task parts.

    Returns:
        A :class:`SynthesisResult` recording the four published paths
        and any capability merge conflicts.

    Raises:
        SynthesisError: ``<run_dir>/artifact/parts`` or
            ``<run_dir>/artifact/prefetch`` is missing, the merged
            capabilities fragments fail schema validation, or the
            manual-merge LLM call fails / returns an unusable response.
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
    try:
        manual_text = render_manual(
            llm=llm,
            manual_prompt=manual_prompt,
            capabilities=capabilities,
            parts_concat=parts_concat,
        )
    except ManualRenderError as exc:
        raise SynthesisError(f"manual render failed: {exc}") from exc
    except Exception as exc:
        raise SynthesisError(f"manual render failed: {exc}") from exc
    manual_path.write_text(manual_text, encoding="utf-8")

    manifest = build_manifest(run_dir=run_dir, conflicts=conflicts)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return SynthesisResult(
        manual_path=manual_path,
        capabilities_path=capabilities_path,
        stats_path=stats_path,
        manifest_path=manifest_path,
        capability_conflicts=tuple(conflicts),
    )
