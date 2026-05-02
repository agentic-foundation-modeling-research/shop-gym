"""``cross_task_consistency`` build-loop verifier (spec §5.5.3 + §5.5.4, T5.5).

Asks the configured runtime's :class:`~harness.runtimes.LLMCompleter`
to do a whole-app sweep after the mandatory ``visual_fix`` task: are
all generated components mutually consistent (shared design tokens,
shared types, no orphan imports, navigation paths matching collection
handles)?

Applicability matches the spec table: post ``visual_fix`` only. The
verifier exists because the slice-owned ``gen_*`` tasks cannot re-open
each other; ``visual_fix`` is the seam where cross-task drift gets
repaired (spec §5.5.4) and this judge is its gating signal.

The verifier reads:

* ``ctx.artifact_dir / "data" / "collections.json"`` — the canonical
  list of collection handles. Used as ground truth for the
  navigation-vs-collections rule.
* ``ctx.artifact_dir / "hydrogen" / "app" / **`` — the source files
  the consolidator just edited.

A missing collections file or hydrogen tree is reported as ``FAIL`` so
the loop can recover by re-running the upstream step. LLM transport
failures (timeout, malformed response) also surface as ``FAIL`` with
explanatory feedback rather than crashing the harness.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Final, cast

from harness.verifiers import Verdict, VerifierContext, VerifierResult
from shop_arena.gen.build.prompts import load_cross_task_consistency_prompt
from shop_arena.gen.build.verifiers._judge import (
    JudgeOutput,
    dispatch_judge,
    render_source_blocks,
    require_completer,
)

_NAME: Final[str] = "cross_task_consistency"
"""Verifier name (filesystem-safe; matches the spec table)."""

_HYDROGEN_APP_DIR: Final[str] = "hydrogen/app"
"""Path of the hydrogen ``app/`` tree relative to ``VerifierContext.artifact_dir``."""

_COLLECTIONS_FILE: Final[str] = "data/collections.json"
"""Path of the collections document relative to ``VerifierContext.artifact_dir``."""

_DEFAULT_TIMEOUT_S: Final[float] = 240.0
"""Wall-clock budget for the LLM judge call.

Conservative: the visual_fix sweep typically reviews more files than
``quality_judge`` (whole-app rather than task-scoped), so the default
budget is a minute longer than the per-task quality judge.
"""

_DEFAULT_MAX_BYTES_PER_FILE: Final[int] = 8_000
"""Per-file source-byte cap (truncation defended in the body)."""

_DEFAULT_MAX_TOTAL_BYTES: Final[int] = 120_000
"""Aggregate source-byte cap across all reviewed files.

Higher than ``quality_judge``'s default because this verifier reviews
the whole app rather than one task slice.
"""

_DEFAULT_TASKS: Final[frozenset[str]] = frozenset({"visual_fix"})
"""Tasks this verifier applies to per spec §5.5.4."""


class CrossTaskConsistencyVerifier:
    """Asks the runtime's LLM completer to sweep for cross-task drift.

    Attributes:
        name: ``"cross_task_consistency"`` — used as the per-verifier
            telemetry filename and the markdown section heading in
            ``feedback.md``.
    """

    name: str = _NAME

    def __init__(
        self,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_bytes_per_file: int = _DEFAULT_MAX_BYTES_PER_FILE,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
        applicable_tasks: Iterable[str] | None = None,
    ) -> None:
        """Build the verifier with optional injection seams.

        Args:
            timeout_s: Wall-clock budget for the LLM judge call.
                Defaults to :data:`_DEFAULT_TIMEOUT_S`.
            max_bytes_per_file: Per-file source-byte cap; longer files
                are truncated with an elision marker. Defaults to
                :data:`_DEFAULT_MAX_BYTES_PER_FILE`.
            max_total_bytes: Aggregate source-byte cap; files past the
                cap are dropped. Defaults to
                :data:`_DEFAULT_MAX_TOTAL_BYTES`.
            applicable_tasks: Override the default applicability set.
                Defaults to :data:`_DEFAULT_TASKS` (``{"visual_fix"}``
                per spec §5.5.4).
        """
        self._timeout_s = timeout_s
        self._max_bytes_per_file = max_bytes_per_file
        self._max_total_bytes = max_total_bytes
        self._applicable_tasks: frozenset[str] = (
            _DEFAULT_TASKS if applicable_tasks is None else frozenset(applicable_tasks)
        )

    def applies_to(self, task_id: str) -> bool:
        """Match the spec §5.5.4 task list (``visual_fix`` only by default).

        Args:
            task_id: Selected task id.

        Returns:
            ``True`` when the verifier should run for ``task_id``.
        """
        return task_id in self._applicable_tasks

    def run(self, ctx: VerifierContext) -> VerifierResult:
        """Render the judge prompt, call the LLM, and translate its verdict.

        Args:
            ctx: Verifier context. Reads ``ctx.artifact_dir`` to locate
                the hydrogen tree + ``data/collections.json``; uses
                ``ctx.runtime`` (narrowed to ``LLMCompleter``) for the
                judge call.

        Returns:
            ``PASS`` when the LLM emits ``{"verdict": "pass", ...}``;
            ``FAIL`` with the LLM's feedback otherwise. Workspace
            problems (missing collections / hydrogen tree) and LLM
            transport errors (timeout, malformed response) also surface
            as ``FAIL`` with explanatory feedback.
        """
        collections_path = ctx.artifact_dir / _COLLECTIONS_FILE
        if not collections_path.is_file():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`cross_task_consistency` could not read "
                    f"`{_COLLECTIONS_FILE}`. Did Phase 2 `assemble_data` run?"
                ),
                details={"collections_path": str(collections_path), "exists": False},
            )

        app_dir = ctx.artifact_dir / _HYDROGEN_APP_DIR
        if not app_dir.is_dir():
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`cross_task_consistency` could not find the hydrogen "
                    f"app tree at `{_HYDROGEN_APP_DIR}/`. Did `clone_template` run?"
                ),
                details={"app_dir": str(app_dir), "exists": False},
            )

        try:
            collections_text = collections_path.read_text(encoding="utf-8")
            collections_payload: Any = json.loads(collections_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return VerifierResult(
                verdict=Verdict.FAIL,
                feedback=(
                    f"`cross_task_consistency` could not parse "
                    f"`{_COLLECTIONS_FILE}`: {type(exc).__name__}: {exc}"
                ),
                details={"collections_path": str(collections_path), "error": str(exc)},
            )

        handles = _extract_handles(collections_payload)
        completer = require_completer(ctx.runtime, verifier_name=_NAME)

        source_blocks, files_reviewed, files_elided = render_source_blocks(
            app_dir,
            max_bytes_per_file=self._max_bytes_per_file,
            max_total_bytes=self._max_total_bytes,
        )
        prompt = load_cross_task_consistency_prompt().format(
            collection_handles=json.dumps(handles, indent=2, sort_keys=True),
            source_blocks=source_blocks,
        )

        outcome = dispatch_judge(
            completer,
            prompt=prompt,
            timeout_s=self._timeout_s,
            verifier_name=_NAME,
        )
        if not isinstance(outcome, JudgeOutput):
            return outcome  # Pre-rendered FAIL from dispatch_judge.
        parsed = outcome

        return VerifierResult(
            verdict=parsed.verdict,
            feedback=parsed.feedback,
            details={
                "files_reviewed": files_reviewed,
                "files_elided": files_elided,
                "collection_handles": handles,
            },
        )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _extract_handles(collections_payload: Any) -> list[str]:
    """Pull the ``handle`` field out of every collection record.

    The full ``data/collections.json`` schema lives in
    :mod:`shop_arena.gen.data_synth.schema`; this helper deliberately stays
    structurally permissive — a payload that diverges from the schema
    is the upstream verifier's problem, not ours.

    Args:
        collections_payload: Decoded JSON body. Expected to be a list
            of objects with a ``handle: str`` field.

    Returns:
        Sorted list of handle strings. Non-string handles and entries
        without the field are silently skipped.
    """
    if not isinstance(collections_payload, list):
        return []
    raw_entries = cast("list[Any]", collections_payload)
    handles: list[str] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        entry_dict = cast("dict[str, Any]", entry)
        handle = entry_dict.get("handle")
        if isinstance(handle, str) and handle:
            handles.append(handle)
    return sorted(handles)


__all__ = ["CrossTaskConsistencyVerifier"]
