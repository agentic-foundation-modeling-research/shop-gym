"""Post-loop synthesis for ``shop_explore``.

Implements §5.10 of the ShopExplore spec
(``docs/specs/shop_arena/shop_explore.md``): one deterministic Python
step that runs after the harness ``plan_exec_loop`` returns. Reads the
per-task fragments and prefetch evidence under ``run_dir/artifact/``,
writes the four published files of the Shop Manual:

1. ``capabilities.json`` — deterministic deep-merge of every
   ``parts/*.caps.json`` fragment, validated against the v0.1 schema.
2. ``stats.json`` — deterministic statistics computed from prefetch
   data + the merged capabilities.
3. ``manual.md`` — single LLM call that merges ``parts/*.md`` and the
   capabilities document into one prose document. On an empty / short
   response we fall back to deterministic concatenation of
   ``parts/*.md`` and flag ``manifest.manual_fallback=true``.
4. ``manifest.json`` — run summary (run_id, domain, harness status,
   iteration counts, plan task tallies, omitted areas, capability
   conflicts, fallback flag, paths).

Public surface:

* :class:`SynthesisError` — raised on missing/invalid run_dir layout
  or when the merged capabilities fail schema validation.
* :class:`LLMClient` — minimal protocol the manual-merge call uses.
* :class:`SynthesisResult` — closed pydantic model returned by
  :func:`synthesize`.
* :func:`synthesize` — the post-loop entrypoint.

The module is import-safe — no I/O at import time. The single LLM call
is the *only* network egress; any exception raised by the client is
swallowed and treated as an empty response so we always emit a
``manual.md`` (spec §5.10 fallback).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict

from shop_explore.capabilities import (
    Capabilities,
    CapabilitiesValidationError,
    Conflict,
    merge_fragments,
)
from shop_explore.stats import compute as compute_stats

MANUAL_MIN_CHARS = 200
"""Minimum stripped length of an LLM-rendered manual; shorter falls back (spec §5.10)."""


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
            shorter than :data:`MANUAL_MIN_CHARS` and we fell back to
            deterministic concatenation of ``parts/*.md``.
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

    parts_concat = _concat_parts(parts_dir)
    manual_text, manual_fallback = _render_manual(
        llm=llm,
        manual_prompt=manual_prompt,
        capabilities=capabilities,
        parts_concat=parts_concat,
    )
    manual_path.write_text(manual_text, encoding="utf-8")

    manifest = _build_manifest(
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


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _concat_parts(parts_dir: Path) -> str:
    """Return ``parts/*.md`` concatenated in sorted filename order.

    Each part is right-trimmed of trailing newlines and joined with a
    blank line so the result reads as a single document. The output
    always ends with a single newline.
    """
    chunks: list[str] = []
    for path in sorted(parts_dir.glob("*.md")):
        chunks.append(path.read_text(encoding="utf-8").rstrip("\n"))
    if not chunks:
        return ""
    return "\n\n".join(chunks).rstrip("\n") + "\n"


def _render_manual(
    *,
    llm: LLMClient,
    manual_prompt: str,
    capabilities: Capabilities,
    parts_concat: str,
) -> tuple[str, bool]:
    """One LLM call; on short / empty / failed response, fall back.

    Returns the manual text plus a boolean indicating whether we used
    the deterministic fallback. ``True`` matches
    ``manifest.manual_fallback`` per spec §5.10.
    """
    full_prompt = (
        manual_prompt.rstrip("\n")
        + "\n\n## Capabilities\n\n```json\n"
        + capabilities.model_dump_json(indent=2)
        + "\n```\n\n## Per-task parts\n\n"
        + parts_concat
    )
    try:
        response = llm.complete(full_prompt)
    except Exception:  # fall back on any LLM client failure
        # Spec §5.10 only enumerates the "empty / < 200 chars" case
        # explicitly, but a raised exception is the same observable
        # outcome (no usable manual text). Surface it through the
        # fallback path so we always emit ``manual.md``.
        return parts_concat, True

    if len(response.strip()) < MANUAL_MIN_CHARS:
        return parts_concat, True
    if not response.endswith("\n"):
        response = response + "\n"
    return response, False


def _build_manifest(
    *,
    run_dir: Path,
    conflicts: list[Conflict],
    manual_fallback: bool,
) -> dict[str, Any]:
    """Assemble the ``manifest.json`` payload (spec §5.10 step 4)."""
    plan_md_path = run_dir / "plan.md"
    plan_md = plan_md_path.read_text(encoding="utf-8") if plan_md_path.is_file() else ""
    plan_tasks_total, plan_tasks_done, plan_tasks_blocked = _count_plan_tasks(plan_md)
    omitted_areas = _parse_omitted_areas(plan_md)
    run_summary = _read_run_summary(run_dir)

    return {
        "run_id": run_dir.name,
        "domain": run_dir.parent.name,
        "runtime": run_summary.get("runtime", ""),
        "harness_status": run_summary.get("final_status", ""),
        "iters": {
            "plan": int(run_summary.get("plan_iter_count", 0) or 0),
            "exec": int(run_summary.get("exec_iter_count", 0) or 0),
        },
        "plan_tasks_total": plan_tasks_total,
        "plan_tasks_done": plan_tasks_done,
        "plan_tasks_blocked": plan_tasks_blocked,
        "omitted_areas": omitted_areas,
        "capability_conflicts": [c.model_dump(mode="json") for c in conflicts],
        "manual_fallback": manual_fallback,
        "synthesized_at": _utc_now_iso(),
        "paths": {
            "manual": "artifact/manual.md",
            "capabilities": "artifact/capabilities.json",
            "stats": "artifact/stats.json",
            "manifest": "artifact/manifest.json",
            "prefetch": "artifact/prefetch",
        },
    }


def _read_run_summary(run_dir: Path) -> dict[str, Any]:
    """Best-effort read of ``run.json``.

    Missing or malformed ``run.json`` collapses to ``{}`` so synthesis
    can still emit a manifest (e.g. when called via
    ``--synthesize-only`` against a run_dir that pre-dates a harness
    crash). The harness itself is the source of truth for the run
    summary; we only mirror selected fields into the manifest.
    """
    path = run_dir / "run.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, Any], raw)


def _count_plan_tasks(plan_md: str) -> tuple[int, int, int]:
    """Count task rows under the ``## Tasks`` section of ``plan.md``.

    Returns ``(total, done, blocked)`` where ``done`` is ``[x]`` and
    ``blocked`` is ``[!]``. Pending and in-progress rows are counted in
    ``total`` only.
    """
    total = done = blocked = 0
    in_tasks = False
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_tasks = stripped.lower().startswith("## tasks")
            continue
        if not in_tasks:
            continue
        if not stripped.startswith("- ["):
            continue
        marker = stripped[3:4]
        total += 1
        if marker == "x":
            done += 1
        elif marker == "!":
            blocked += 1
    return total, done, blocked


def _parse_omitted_areas(plan_md: str) -> list[dict[str, str]]:
    """Read the ``## Omitted Areas`` block of ``plan.md`` into records.

    Each line of the form ``- <area> — <reason>`` (em dash or hyphen)
    becomes ``{"area": ..., "reason": ...}``. Lines with no separator
    yield ``{"area": ..., "reason": ""}``.
    """
    items: list[dict[str, str]] = []
    in_block = False
    for line in plan_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_block = stripped.lower().startswith("## omitted")
            continue
        if not in_block or not stripped.startswith("- "):
            continue
        body = stripped[2:].strip()
        if " — " in body:
            area, _, reason = body.partition(" — ")
        elif " - " in body:
            area, _, reason = body.partition(" - ")
        else:
            area, reason = body, ""
        items.append({"area": area.strip(), "reason": reason.strip()})
    return items


def _utc_now_iso() -> str:
    """Return ``datetime.now(UTC)`` as an RFC 3339 ``Z`` timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
